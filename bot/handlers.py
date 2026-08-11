"""Telegram bot handlers for job-hunter.
Commands: /start, /help, /jobs, /collect, /firecrawl, /profile, /resume,
          /outreach, /status, /firecrawl_list"""
import asyncio, aiosqlite, json, re, os
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ConversationHandler, ContextTypes, filters,
)
from config.settings import DB_PATH, TELEGRAM_BOT_TOKEN, TELEGRAM_TOPIC_DAILY_DIGEST, TELEGRAM_TOPIC_UPDATES
from core.database import init_db, get_active_profile, get_profiles, get_jobs, get_stats
from core.database import get_api_usage, get_resumes, get_outreach, get_companies, upsert_company
from core.database import add_firecrawl_url, get_pending_firecrawl, complete_firecrawl
from core.collector import run_collection, run_firecrawl_url
from core.hunter import build_linkedin_searches, generate_dm_template

# Conversation states
(ASK_PROFILE, ASK_RESUME_ROLE, ASK_FIRECRAWL_URL,
 ASK_PROFILE_FIELD, ASK_COMPANY_NAME) = range(5)


def log(msg):
    print(f"[TELEGRAM BOT] {msg}", flush=True)


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "Welcome to *Job Hunter Bot*!\n\n"
        "Available commands:\n"
        "/jobs — Show top jobs\n"
        "/collect — Run job collection now\n"
        "/firecrawl — Scrape a company career page\n"
        "/firecrawl_list — List companies for Firecrawl\n"
        "/profile — View/edit your profile\n"
        "/resume — Manage resumes per role\n"
        "/outreach — Generate outreach for a job\n"
        "/status — API usage and stats\n"
        "/help — Full command reference"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "*Job Hunter Bot — Full Help*\n\n"
        "`/jobs [n]` — Show top n jobs (default 10)\n"
        "`/collect` — Trigger full job collection now\n"
        "`/firecrawl <url>` — Scrape a company career page directly\n"
        "`/firecrawl_list` — List companies ready for Firecrawl scrape\n"
        "`/firecrawl_add <company> <url>` — Add company to Firecrawl queue\n"
        "`/profile` — View active profile\n"
        "`/profile list` — List all profiles\n"
        "`/profile set <id>` — Switch active profile\n"
        "`/profile edit <id> <field> <value>` — Edit profile field\n"
        "`/profile yaml <id>` — Get profile as YAML\n"
        "`/resume list` — List uploaded resumes\n"
        "`/resume upload` — Upload resume for a role\n"
        "`/outreach <job_id>` — Generate outreach for a job\n"
        "`/status` — API usage, JSearch limits, last run\n"
        "`/add_company <name>` — Add a company for ATS scraping"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db = await aiosqlite.connect(DB_PATH)
    await init_db()

    jsearch = await get_api_usage(db, "jsearch")
    stats = await get_stats(db)
    active_profile = await get_active_profile(db)
    runs_cursor = await db.execute(
        "SELECT * FROM daily_runs ORDER BY run_at DESC LIMIT 3"
    )
    runs = await runs_cursor.fetchall()
    await db.close()

    last_run = runs[0] if runs else None
    last_run_str = last_run[1] if last_run else "Never"

    text = (
        "*Status*\n\n"
        f"*JSearch:* {jsearch['daily']}/18 today | {jsearch['monthly']}/180 this month\n"
        f"*Jobs DB:* {stats['total']} total | {stats['new']} new\n"
        f"*Last run:* {last_run_str}\n"
        f"*Active profile:* {active_profile.get('name', 'None') if active_profile else 'None'}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_jobs(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db = await aiosqlite.connect(DB_PATH)
    await init_db()

    limit = 10
    if ctx.args and ctx.args[0].isdigit():
        limit = min(int(ctx.args[0]), 50)

    jobs = await get_jobs(db, min_score=30, limit=limit)
    await db.close()

    if not jobs:
        await update.message.reply_text("No jobs found. Run /collect first.")
        return

    for i, job in enumerate(jobs, 1):
        score = job.get("relevance_score", 0)
        title = job.get("title", "")
        company = job.get("company", "")
        location = job.get("location", "Remote")
        india = job.get("india_friendly", "unknown")
        url = job.get("url", "")
        job_id = job.get("id", "")

        text = (
            f"*{i}. {title}*\n"
            f"Company: {company}\n"
            f"Location: {location}\n"
            f"Score: {score} | India: {india}\n"
            f"{url}\n"
            f"`/outreach {job_id}`"
        )
        await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_collect(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("Running collection...")
    db = await aiosqlite.connect(DB_PATH)
    await init_db()
    profile = await get_active_profile(db)
    await db.close()

    if not profile:
        await msg.edit_text("No active profile. Create one via the web UI first.")
        return

    try:
        stats = await run_collection(profile["config"])
        text = (
            f"*Collection done!*\n\n"
            f"Fetched: {stats['fetched']}\n"
            f"New: {stats['new']} | Updated: {stats['updated']}\n"
            f"Filtered: {stats['filtered_out']}\n"
            f"JSearch reqs: {stats['jsearch_used']}"
        )
    except Exception as e:
        text = f"Collection failed: {e}"
    await msg.edit_text(text, parse_mode="Markdown")


async def cmd_firecrawl_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db = await aiosqlite.connect(DB_PATH)
    await init_db()
    companies = await get_companies(db, crawl_status="firecrawl_pending")
    if not companies:
        companies = await get_companies(db)
        companies = [c for c in companies if c.get("crawl_status") in ("active", "paused")][:20]
    await db.close()

    if not companies:
        await update.message.reply_text("No companies found. Add companies first.")
        return

    text = "*Companies for Firecrawl scrape:*\n\n"
    for c in companies:
        name = c.get("name", "")
        domain = c.get("domain", "")
        careers = c.get("careers_url", "")
        text += f"• {name}\n  {domain or careers}\n\n"

    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_firecrawl_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args or len(ctx.args) < 2:
        await update.message.reply_text("Usage: /firecrawl_add <company_name> <career_page_url>")
        return

    company_name = ctx.args[0]
    url = ctx.args[1]
    if not url.startswith("http"):
        await update.message.reply_text("URL must start with http:// or https://")
        return

    db = await aiosqlite.connect(DB_PATH)
    await init_db()
    await upsert_company(db, {
        "name": company_name,
        "careers_url": url,
        "ats_platform": "firecrawl",
        "crawl_status": "active",
    })
    await db.close()
    await update.message.reply_text(f"Added *{company_name}* to Firecrawl queue.", parse_mode="Markdown")


async def cmd_firecrawl(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: /firecrawl <career_page_url>\nOr: /firecrawl_list to see queued companies")
        return

    url = ctx.args[0]
    if not url.startswith("http"):
        await update.message.reply_text("URL must start with http:// or https://")
        return

    company_name = url.split("/")[2].replace("www.", "").split(".")[0].title()

    msg = await update.message.reply_text(f"Scraping {url}...")
    db = await aiosqlite.connect(DB_PATH)
    await init_db()
    profile = await get_active_profile(db)
    await db.close()

    if not profile:
        await msg.edit_text("No active profile. Create one first.")
        return

    try:
        stats = await run_firecrawl_url(url, company_name, profile["config"], db)
        text = f"*Firecrawl done!*\nJobs found: {stats['fetched']}\nNew: {stats['new']}"
    except Exception as e:
        text = f"Firecrawl failed: {e}"
    await msg.edit_text(text, parse_mode="Markdown")


async def cmd_profile(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db = await aiosqlite.connect(DB_PATH)
    await init_db()

    if ctx.args and ctx.args[0] == "list":
        profiles = await get_profiles(db)
        await db.close()
        text = "*Profiles:*\n"
        for p in profiles:
            active = " (ACTIVE)" if p.get("is_active") else ""
            text += f"• `{p['id']}` — {p['name']}{active}\n"
        await update.message.reply_text(text, parse_mode="Markdown")
        return

    if ctx.args and ctx.args[0] == "set" and len(ctx.args) >= 2:
        pid = int(ctx.args[1])
        from core.database import set_active_profile
        await set_active_profile(db, pid)
        await db.close()
        await update.message.reply_text(f"Profile {pid} is now active.")
        return

    if ctx.args and ctx.args[0] == "yaml" and len(ctx.args) >= 2:
        pid = int(ctx.args[1])
        profiles = await get_profiles(db)
        await db.close()
        p = next((x for x in profiles if x["id"] == pid), None)
        if p:
            import yaml
            yaml_text = yaml.dump(p.get("config", {}), default_flow_style=False)
            await update.message.reply_text(f"```yaml\n{yaml_text}\n```", parse_mode="Markdown")
        return

    profile = await get_active_profile(db)
    await db.close()

    if not profile:
        await update.message.reply_text("No active profile. Create one via the web UI.")
        return

    name = profile.get("name", "")
    desc = profile.get("description", "")
    search = profile.get("config", {}).get("search", {})
    queries = search.get("jsearch_default_queries", [])
    text = (
        f"*Profile: {name}*\n"
        f"_{desc}_\n\n"
        f"Active queries ({len(queries)}):\n"
    )
    for q in queries[:5]:
        text += f"• {q.get('query', '')} ({q.get('country', '')}, {q.get('date_posted', '')}, remote={q.get('remote_jobs_only', False)})\n"

    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_resume(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    db = await aiosqlite.connect(DB_PATH)
    await init_db()
    resumes = await get_resumes(db)
    await db.close()

    if not resumes:
        await update.message.reply_text("No resumes uploaded. Use the web UI to upload resumes.")
        return

    text = "*Uploaded Resumes:*\n"
    for r in resumes:
        text += f"• `{r['role_name']}` — {r['original_filename']} ({r['file_size']} bytes)\n"

    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_outreach(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: /outreach <job_id>\nFind job IDs with /jobs")
        return

    job_id = ctx.args[0]
    db = await aiosqlite.connect(DB_PATH)
    await init_db()

    jobs = await get_jobs(db, limit=500)
    job = next((j for j in jobs if j.get("id") == job_id), None)

    if not job:
        await db.close()
        await update.message.reply_text(f"Job `{job_id}` not found.", parse_mode="Markdown")
        return

    profile = await get_active_profile(db)
    await db.close()

    if not profile:
        await update.message.reply_text("No active profile.")
        return

    outreach_cfg = profile.get("config", {}).get("outreach", {})
    searches = build_linkedin_searches(job.get("company", ""), outreach_cfg)
    dms = generate_dm_template(job, outreach_cfg)

    text = (
        f"*Outreach for: {job.get('title')} @ {job.get('company')}*\n\n"
        f"*Short DM:*\n{dms['short']}\n\n"
        f"*LinkedIn Searches:*\n"
    )
    for s in searches[:4]:
        text += f"• [{s['label']}]({s['url']})\n"

    text += f"\n*Apply:* {job.get('url', 'N/A')}"
    await update.message.reply_text(text, parse_mode="Markdown", disable_web_page_preview=True)


async def cmd_add_company(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text(
            "Usage: /add_company <name> [domain] [careers_url]\n"
            "Example: /add_company OpenZeppelin openzeppelin.com https://openzeppelin.com/jobs"
        )
        return

    name = ctx.args[0]
    domain = ctx.args[1] if len(ctx.args) > 1 else ""
    careers_url = ctx.args[2] if len(ctx.args) > 2 else ""

    db = await aiosqlite.connect(DB_PATH)
    await init_db()
    await upsert_company(db, {
        "name": name,
        "domain": domain,
        "careers_url": careers_url,
        "ats_platform": "unknown",
        "crawl_status": "active",
    })
    await db.close()
    await update.message.reply_text(f"Added company: *{name}*", parse_mode="Markdown")


async def error_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    log(f"Telegram error: {ctx.error}")


def setup_bot() -> Application:
    """Build and return the telegram bot application."""
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN not set in .env")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("jobs", cmd_jobs))
    app.add_handler(CommandHandler("collect", cmd_collect))
    app.add_handler(CommandHandler("firecrawl_list", cmd_firecrawl_list))
    app.add_handler(CommandHandler("firecrawl_add", cmd_firecrawl_add))
    app.add_handler(CommandHandler("firecrawl", cmd_firecrawl))
    app.add_handler(CommandHandler("profile", cmd_profile))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("outreach", cmd_outreach))
    app.add_handler(CommandHandler("add_company", cmd_add_company))
    app.add_error_handler(error_handler)

    return app
