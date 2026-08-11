"""
Job Hunter — Main Entry Point
FastAPI app + Telegram bot (co-running) + APScheduler cron jobs.

Run:
  python main.py              — starts everything
  python main.py --web-only  — FastAPI only (no bot/cron)
  python main.py --bot-only  — Telegram bot only
"""
import asyncio, argparse, logging, os, sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

import aiosqlite
import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from telegram import Bot
from telegram.error import Forbidden

# ── Local imports ──────────────────────────────────────────────────────────────
from config.settings import (
    BASE_DIR, DB_PATH, RESUME_DIR, TELEGRAM_BOT_TOKEN,
    TELEGRAM_TOPIC_DAILY_DIGEST, TELEGRAM_TOPIC_UPDATES, TELEGRAM_CHAT_ID,
)
from core.database import (
    init_db, get_jobs, get_stats, get_profiles, get_active_profile,
    create_profile, update_profile, set_active_profile, delete_profile,
    get_resumes, insert_resume, delete_resume,
    get_outreach, insert_outreach, update_outreach_status, outreach_exists_for_job,
    upsert_company, get_companies, get_api_usage, get_last_runs,
    log_daily_run, get_cron_toggles, set_cron_toggle,
)
from core.collector import run_collection, run_firecrawl_url
from core.hunter import build_linkedin_searches, generate_dm_template

# ── Logging ─────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("job-hunter")

# ── Scheduler ─────────────────────────────────────────────────────────────────
scheduler = AsyncIOScheduler()
BOT_INSTANCE = None
_telegram_topic_digest = str(TELEGRAM_TOPIC_DAILY_DIGEST) if TELEGRAM_TOPIC_DAILY_DIGEST else ""
_telegram_topic_updates = str(TELEGRAM_TOPIC_UPDATES) if TELEGRAM_TOPIC_UPDATES else ""

# ── Telegram sender (safe — no error if topic not set) ───────────────────────
async def send_telegram(text: str, topic_id: str = None):
    """Send a Telegram message. topic_id enables thread targeting."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram not configured — skipping message")
        return
    try:
        bot = Bot(token=TELEGRAM_BOT_TOKEN)
        kwargs: dict = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
        if topic_id:
            kwargs["message_thread_id"] = int(topic_id)
        await bot.send_message(**kwargs)
    except Forbidden:
        log.warning("Telegram bot not in group — add it to the group first")
    except Exception as e:
        log.error(f"Telegram send error: {e}")


# ── Cron: Daily job digest to Telegram ────────────────────────────────────────
async def cron_daily_digest():
    """Run every morning, post top jobs to Telegram Daily Digest thread."""
    log("[CRON] Daily digest starting...")
    db = await aiosqlite.connect(DB_PATH)
    await init_db()
    profile = await get_active_profile(db)

    if not profile:
        log("[CRON] No active profile, skipping digest")
        await db.close()
        return

    # Get top new jobs from last 24h
    yesterday = (datetime.utcnow() - timedelta(hours=24)).isoformat()
    jobs = await get_jobs(db, min_score=40, seen_after=yesterday, limit=15)
    await db.close()

    if not jobs:
        msg = "Good morning! No new highly-relevant jobs in the last 24h. Run /collect to refresh."
    else:
        lines = [f"*Good morning! {len(jobs)} new/relevant jobs:*\n"]
        for i, job in enumerate(jobs, 1):
            score = job.get("relevance_score", 0)
            india = job.get("india_friendly", "?")
            lines.append(
                f"{i}. *{job['title']}* @ {job['company']}\n"
                f"   Score:{score} | India:{india} | {job.get('location', 'Remote')}\n"
                f"   {job.get('url', '')[:80]}"
            )
        msg = "\n".join(lines)

    await send_telegram(msg, topic_id=_telegram_topic_digest)
    log(f"[CRON] Digest sent: {len(jobs)} jobs")


# ── Cron: Job collection (every 8h, 3 JSearch reqs max) ───────────────────────
async def cron_collect():
    """Run every 8 hours. JSearch capped at 3 queries inside run_collection."""
    log("[CRON] Collection starting...")
    db = await aiosqlite.connect(DB_PATH)
    await init_db()
    profile = await get_active_profile(db)
    await db.close()

    if not profile:
        log("[CRON] No active profile, skipping collection")
        return

    try:
        stats = await run_collection(profile["config"], include_companies=True)
        msg = (
            f"[CRON] Collection done — "
            f"fetched:{stats['fetched']} new:{stats['new']} "
            f"updated:{stats['updated']} jsearch:{stats.get('jsearch_used', 0)}"
        )
    except Exception as e:
        msg = f"[CRON] Collection failed: {e}"
        log.error(msg)

    await send_telegram(msg, topic_id=_telegram_topic_digest)
    log("[CRON] Collection done")


# ── Lifespan: startup / shutdown ───────────────────────────────────────────────
def _apply_cron_toggles():
    """Read DB toggles and apply pause/resume to APScheduler jobs."""
    import sqlite3
    from config.settings import DB_PATH
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute("SELECT job_id, enabled FROM cron_toggles").fetchall()
        conn.close()
        for job_id, enabled in rows:
            job = scheduler.get_job(job_id)
            if job:
                if enabled and job.next_run_time is None:
                    job.resume()
                    log.info(f"Cron job '{job_id}' resumed from DB state")
                elif not enabled and job.next_run_time is not None:
                    job.pause()
                    log.info(f"Cron job '{job_id}' paused from DB state")
    except Exception as e:
        log.warning(f"Could not read cron toggles: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    log.info("Database initialised")

    # Schedule cron jobs (all added paused, then DB state applied)
    scheduler.add_job(cron_daily_digest, CronTrigger(hour=8, minute=0),
                      id="daily_digest", replace_existing=True, paused=True)
    scheduler.add_job(cron_collect, IntervalTrigger(hours=8),
                      id="collect_8h", replace_existing=True, paused=True)
    scheduler.start()
    _apply_cron_toggles()
    log.info("Scheduler started (daily_digest at 08:00 UTC, collection every 8h)")

    # Start Telegram bot in background (PTB v21 uses initialize/start/stop, not run)
    if TELEGRAM_BOT_TOKEN:
        from bot.handlers import setup_bot
        global BOT_INSTANCE
        bot_app = setup_bot()
        await bot_app.initialize()
        asyncio.create_task(bot_app.start())
        BOT_INSTANCE = bot_app
        log.info("Telegram bot started")

    yield

    # Shutdown
    scheduler.shutdown(wait=False)
    if BOT_INSTANCE:
        await BOT_INSTANCE.stop()
        await BOT_INSTANCE.shutdown()
    log.info("Scheduler stopped")


# ── FastAPI App ─────────────────────────────────────────────────────────────────
app = FastAPI(title="Job Hunter", lifespan=lifespan)

# Static + templates
STATIC_DIR = BASE_DIR / "web" / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "web" / "templates"))


# ── Helpers ────────────────────────────────────────────────────────────────────
def render(template_name: str, request: Request, **kwargs):
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context=kwargs,
    )


def parse_bool(val) -> bool:
    return str(val).lower() in ("1", "true", "yes", "on")


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return RedirectResponse(url="/web/dashboard")


# ══════════════════════════════════════════════════════════════
#  WEB ROUTES
# ══════════════════════════════════════════════════════════════

# ── Dashboard ──────────────────────────────────────────────
@app.get("/web/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    db = await aiosqlite.connect(DB_PATH)
    await init_db()
    stats = await get_stats(db)
    jsearch = await get_api_usage(db, "jsearch")
    profile = await get_active_profile(db)
    last_runs = await get_last_runs(db, limit=5)
    toggles = await get_cron_toggles(db)
    await db.close()

    return render("dashboard.html", request,
        page="dashboard",
        stats=stats,
        jsearch=jsearch,
        active_profile=profile,
        last_runs=last_runs,
        cron_toggles=toggles,
    )


# ── Jobs ───────────────────────────────────────────────────
@app.get("/web/jobs", response_class=HTMLResponse)
async def jobs_page(request: Request,
                    source: str = None,
                    status: str = None,
                    search: str = None,
                    india: str = None,
                    min_score: int = 0,
                    limit: int = 50,
                    offset: int = 0):
    db = await aiosqlite.connect(DB_PATH)
    await init_db()
    jobs = await get_jobs(db, source=source, status=status, search=search,
                          india_friendly=india, min_score=min_score,
                          limit=limit, offset=offset)
    total_count = len(jobs)  # simple, not paginated count
    await db.close()
    return render("jobs.html", request,
        page="jobs", jobs=jobs, filters={
            "source": source or "", "status": status or "",
            "search": search or "", "india": india or "",
            "min_score": min_score, "limit": limit, "offset": offset,
        })


@app.post("/web/jobs/{job_id}/status")
async def update_job_web(job_id: str, status: str = Form(...)):
    db = await aiosqlite.connect(DB_PATH)
    await init_db()
    from core.database import update_job_status as _update
    await _update(db, job_id, status)
    await db.close()
    return RedirectResponse(url="/web/jobs", status_code=303)


# ── Profiles ───────────────────────────────────────────────
@app.get("/web/profiles", response_class=HTMLResponse)
async def profiles_page(request: Request):
    db = await aiosqlite.connect(DB_PATH)
    await init_db()
    profiles = await get_profiles(db)
    await db.close()
    return render("profiles.html", request, page="profiles", profiles=profiles)


@app.get("/web/profiles/new", response_class=HTMLResponse)
async def new_profile_page(request: Request):
    return render("profile_edit.html", request, page="profiles", profile=None, is_new=True)


@app.post("/web/profiles/new")
async def create_profile_web(request: Request,
                               name: str = Form(...),
                               description: str = Form(""),
                               yaml_config: str = Form("")):
    db = await aiosqlite.connect(DB_PATH)
    await init_db()
    try:
        if yaml_config.strip():
            config = yaml.safe_load(yaml_config) or {}
        else:
            config = {
                "search": {
                    "title_keywords_positive": [],
                    "title_keywords_negative": [],
                    "relevant_tech": [],
                    "jsearch_default_queries": [],
                },
                "scoring": {
                    "weights": {"title": 35, "tech": 35, "experience": 15, "signal": 15},
                    "core_tech": [],
                    "backend_signals": [],
                    "experience_bonuses": {},
                },
                "location": {
                    "india_positive": ["india", "remote", "worldwide"],
                    "india_negative": [],
                    "timezone_compatible": [],
                    "timezone_incompatible": [],
                },
                "outreach": {
                    "candidate_name": "Nadim Khan",
                    "candidate_core_tech": [],
                    "candidate_extra_tech": [],
                    "linkedin_search_titles": [],
                    "dm_short_template": "",
                    "dm_long_template": "",
                },
            }
        pid = await create_profile(db, name, description, config)
        # Set as active if first profile
        profiles = await get_profiles(db)
        if len(profiles) == 1:
            await set_active_profile(db, pid)
        await db.close()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse(url="/web/profiles", status_code=303)


@app.get("/web/profiles/{profile_id}/edit", response_class=HTMLResponse)
async def edit_profile_page(request: Request, profile_id: int):
    db = await aiosqlite.connect(DB_PATH)
    await init_db()
    profiles = await get_profiles(db)
    profile = next((p for p in profiles if p["id"] == profile_id), None)
    await db.close()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return render("profile_edit.html", request, page="profiles",
                  profile=profile, is_new=False)


@app.post("/web/profiles/{profile_id}/edit")
async def edit_profile_web(request: Request, profile_id: int,
                             name: str = Form(...),
                             description: str = Form(""),
                             yaml_config: str = Form("")):
    db = await aiosqlite.connect(DB_PATH)
    await init_db()
    try:
        config = yaml.safe_load(yaml_config) if yaml_config.strip() else {}
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid YAML")
    await update_profile(db, profile_id, name, description, config)
    await db.close()
    return RedirectResponse(url="/web/profiles", status_code=303)


@app.post("/web/profiles/{profile_id}/activate")
async def activate_profile(profile_id: int):
    db = await aiosqlite.connect(DB_PATH)
    await init_db()
    await set_active_profile(db, profile_id)
    await db.close()
    return RedirectResponse(url="/web/profiles", status_code=303)


@app.post("/web/profiles/{profile_id}/delete")
async def delete_profile_web(profile_id: int):
    db = await aiosqlite.connect(DB_PATH)
    await init_db()
    await delete_profile(db, profile_id)
    await db.close()
    return RedirectResponse(url="/web/profiles", status_code=303)


# ── Resumes ────────────────────────────────────────────────
@app.get("/web/resumes", response_class=HTMLResponse)
async def resumes_page(request: Request):
    db = await aiosqlite.connect(DB_PATH)
    await init_db()
    resumes = await get_resumes(db)
    profiles = await get_profiles(db)
    await db.close()
    return render("resumes.html", request, page="resumes",
                  resumes=resumes, profiles=profiles)


@app.post("/web/resumes/upload")
async def upload_resume_web(
        request: Request,
        role_name: str = Form(...),
        profile_id: int = Form(1),
        file: UploadFile = File(...)):
    if not file.filename.lower().endswith((".pdf", ".docx", ".doc")):
        raise HTTPException(status_code=400, detail="Only PDF or DOCX files")

    RESUME_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(c for c in role_name if c.isalnum() or c in (" ", "-", "_")).strip()
    safe_name = safe_name.replace(" ", "_")[:50]
    ext = Path(file.filename).suffix.lower()
    dest = RESUME_DIR / f"{safe_name}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{ext}"

    with open(dest, "wb") as f:
        content = await file.read()
        f.write(content)

    db = await aiosqlite.connect(DB_PATH)
    await init_db()
    await insert_resume(db, profile_id, role_name, str(dest), file.filename, len(content))
    await db.close()

    return RedirectResponse(url="/web/resumes", status_code=303)


@app.post("/web/resumes/{resume_id}/delete")
async def delete_resume_web(resume_id: int):
    db = await aiosqlite.connect(DB_PATH)
    await init_db()
    # Get path before deleting
    resumes = await get_resumes(db)
    resume = next((r for r in resumes if r["id"] == resume_id), None)
    if resume and resume.get("file_path"):
        try:
            os.remove(resume["file_path"])
        except Exception:
            pass
    await delete_resume(db, resume_id)
    await db.close()
    return RedirectResponse(url="/web/resumes", status_code=303)


# ── Companies ──────────────────────────────────────────────
@app.get("/web/companies", response_class=HTMLResponse)
async def companies_page(request: Request, search: str = None):
    db = await aiosqlite.connect(DB_PATH)
    await init_db()
    companies = await get_companies(db, search=search)
    await db.close()
    return render("companies.html", request, page="companies",
                  companies=companies, search=search or "")


@app.post("/web/companies/add")
async def add_company_web(request: Request,
                           name: str = Form(...),
                           domain: str = Form(""),
                           careers_url: str = Form(""),
                           ats_platform: str = Form("unknown"),
                           ats_slug: str = Form("")):
    db = await aiosqlite.connect(DB_PATH)
    await init_db()
    await upsert_company(db, {
        "name": name, "domain": domain, "careers_url": careers_url,
        "ats_platform": ats_platform, "ats_slug": ats_slug,
        "crawl_status": "active",
    })
    await db.close()
    return RedirectResponse(url="/web/companies", status_code=303)


# ── Outreach ───────────────────────────────────────────────
@app.get("/web/outreach", response_class=HTMLResponse)
async def outreach_page(request: Request, status: str = None, job_id: str = None):
    db = await aiosqlite.connect(DB_PATH)
    await init_db()

    # If job_id provided, show outreach for that specific job
    target_job = None
    if job_id:
        cur = await db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = await cur.fetchone()
        if row:
            cols = [d[0] for d in cur.description]
            target_job = dict(zip(cols, row))

    outreach = await get_outreach(db, status=status)
    # Filter to just the target job's outreach if job_id was passed
    if job_id and target_job:
        outreach = [o for o in outreach if o.get("job_id") == job_id]
        if not outreach:
            # No outreach yet for this job — show a generate prompt
            outreach = []

    jobs_cursor = await db.execute(
        "SELECT id, title, company FROM jobs ORDER BY discovered_at DESC LIMIT 200"
    )
    jobs = [dict(zip([d[0] for d in jobs_cursor.description], r))
            for r in await jobs_cursor.fetchall()]
    await db.close()
    return render("outreach.html", request, page="outreach",
                  outreach=outreach, jobs=jobs, filter_status=status or "",
                  target_job=target_job)


@app.post("/web/outreach/generate/{job_id}")
async def generate_outreach_web(job_id: str, profile_id: int = Form(0)):
    db = await aiosqlite.connect(DB_PATH)
    await init_db()

    job = await get_jobs(db, limit=1000)
    job = next((j for j in job if j.get("id") == job_id), None)
    if not job:
        await db.close()
        raise HTTPException(status_code=404, detail="Job not found")

    profile = await get_active_profile(db) if not profile_id else None
    if not profile:
        if profile_id:
            profiles = await get_profiles(db)
            profile = next((p for p in profiles if p["id"] == profile_id), None)
    await db.close()

    if not profile:
        raise HTTPException(status_code=400, detail="No active profile")

    outreach_cfg = profile.get("config", {}).get("outreach", {})
    searches = build_linkedin_searches(job.get("company", ""), outreach_cfg)
    dms = generate_dm_template(job, outreach_cfg)

    db = await aiosqlite.connect(DB_PATH)
    await init_db()

    # Check for existing outreach for this job
    existing = await db.execute(
        "SELECT id FROM outreach WHERE job_id = ? LIMIT 1", (job_id,)
    )
    if await existing.fetchone():
        await db.close()
        return RedirectResponse(url="/web/outreach?status=pending", status_code=303)

    await insert_outreach(db, {
        "job_id": job_id,
        "job_title": job.get("title", ""),
        "company": job.get("company", ""),
        "company_domain": job.get("company_domain", ""),
        "contact_name": "[Search LinkedIn]",
        "contact_linkedin": searches[0]["url"] if searches else "",
        "dm_short": dms["short"],
        "dm_long": dms["long"],
        "profile_id": profile.get("id", 0),
    })
    await db.close()
    return RedirectResponse(url="/web/outreach?status=pending", status_code=303)


@app.post("/web/outreach/{outreach_id}/status")
async def update_outreach_web(outreach_id: int, status: str = Form(...)):
    db = await aiosqlite.connect(DB_PATH)
    await init_db()
    await update_outreach_status(db, outreach_id, status)
    await db.close()
    return RedirectResponse(url="/web/outreach", status_code=303)


# ── Collect (manual trigger) ──────────────────────────────
@app.get("/web/collect")
async def trigger_collect_page(request: Request):
    db = await aiosqlite.connect(DB_PATH)
    await init_db()
    stats = await get_stats(db)
    await db.close()
    return render("collect.html", request, page="collect", stats=stats)

@app.post("/web/collect")
async def trigger_collect_web(request: Request):
    db = await aiosqlite.connect(DB_PATH)
    await init_db()
    profile = await get_active_profile(db)
    await db.close()

    if not profile:
        raise HTTPException(status_code=400, detail="No active profile")

    stats = await run_collection(profile["config"])
    return render("collect_result.html", request, page="collect",
                  stats=stats)


# ── Firecrawl (manual trigger) ────────────────────────────
@app.post("/web/firecrawl")
async def trigger_firecrawl_web(request: Request,
                                 url: str = Form(...),
                                 company_name: str = Form("")):
    db = await aiosqlite.connect(DB_PATH)
    await init_db()
    profile = await get_active_profile(db)
    await db.close()

    if not profile:
        raise HTTPException(status_code=400, detail="No active profile")

    name = company_name or url.split("/")[2].replace("www.", "").split(".")[0].title()
    stats = await run_firecrawl_url(url, name, profile["config"], db)
    return render("collect_result.html", request, page="firecrawl", stats=stats)


# ── Cron Toggle API ───────────────────────────────────────
@app.get("/api/cron/toggles")
async def api_cron_toggles():
    db = await aiosqlite.connect(DB_PATH)
    await init_db()
    toggles = await get_cron_toggles(db)
    await db.close()
    # Enrich with APScheduler state
    result = {}
    for job_id, db_enabled in toggles.items():
        job = scheduler.get_job(job_id)
        result[job_id] = {
            "enabled": db_enabled,
            "scheduled": job is not None,
            "paused": job.next_run_time is None if job else True,
            "next_run": str(job.next_run_time) if job and job.next_run_time else None,
        }
    return result


@app.post("/api/cron/toggle/{job_id}")
async def api_cron_toggle(job_id: str, enabled: bool):
    db = await aiosqlite.connect(DB_PATH)
    await init_db()
    await set_cron_toggle(db, job_id, enabled)
    await db.close()

    job = scheduler.get_job(job_id)
    if job:
        if enabled:
            job.resume()
        else:
            job.pause()
        return {"job_id": job_id, "enabled": enabled, "next_run": str(job.next_run_time) if job.next_run_time else None}
    return {"job_id": job_id, "enabled": enabled, "scheduled": False}


# ── Status API ────────────────────────────────────────────
@app.get("/api/stats")
async def api_stats():
    db = await aiosqlite.connect(DB_PATH)
    await init_db()
    stats = await get_stats(db)
    jsearch = await get_api_usage(db, "jsearch")
    await db.close()
    return {**stats, "jsearch": jsearch}


@app.get("/api/jobs")
async def api_jobs(source: str = None, status: str = None,
                   search: str = None, min_score: int = 0,
                   limit: int = 50, offset: int = 0):
    db = await aiosqlite.connect(DB_PATH)
    await init_db()
    jobs = await get_jobs(db, source=source, status=status, search=search,
                          min_score=min_score, limit=limit, offset=offset)
    await db.close()
    return {"count": len(jobs), "jobs": jobs}


@app.post("/api/jobs/bulk-delete")
async def bulk_delete_jobs(job_ids: list[str]):
    db = await aiosqlite.connect(DB_PATH)
    await init_db()
    deleted = 0
    for job_id in job_ids:
        cur = await db.execute("SELECT id FROM jobs WHERE id = ?", (job_id,))
        if await cur.fetchone():
            await db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            deleted += 1
    await db.commit()
    await db.close()
    return {"deleted": deleted}


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str):
    db = await aiosqlite.connect(DB_PATH)
    await init_db()
    cur = await db.execute("SELECT id FROM jobs WHERE id = ?", (job_id,))
    row = await cur.fetchone()
    if not row:
        await db.close()
        raise HTTPException(status_code=404, detail="Job not found")
    await db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    await db.commit()
    await db.close()
    return {"deleted": job_id}


# ── CLI-mode runner ────────────────────────────────────────
def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--web-only", action="store_true")
    parser.add_argument("--bot-only", action="store_true")
    args = parser.parse_args()

    if args.bot_only:
        if not TELEGRAM_BOT_TOKEN:
            print("TELEGRAM_BOT_TOKEN not set in .env")
            sys.exit(1)
        from bot.handlers import setup_bot
        app_bot = setup_bot()
        print("Starting Telegram bot...")
        app_bot.run()
    else:
        import uvicorn
        port = int(os.getenv("PORT", 8000))
        uvicorn.run("main:app", host="0.0.0.0", port=port,
                    reload=os.getenv("DEBUG", "0") == "1")


if __name__ == "__main__":
    run()
