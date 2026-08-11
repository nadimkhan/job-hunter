"""Job collection orchestrator.
Two tracks: job boards (free APIs + JSearch) + company ATS crawl.
JSearch is capped at 3 queries per run. Free sources run every time."""
import asyncio, aiosqlite, json
from datetime import datetime
from config.settings import DB_PATH
from core.database import (
    insert_job, init_db, get_companies, update_job_status,
    get_api_usage, increment_api_usage, log_daily_run,
)
from core.scorer import score_job
from sources.remotive import RemotiveSource
from sources.remoteok import RemoteOKSource
from sources.arbeitnow import ArbeitnowSource
from sources.jsearch import JSearchSource, can_use_jsearch, set_usage
from sources.greenhouse import GreenhouseSource
from sources.lever import LeverSource
from sources.ashby import AshbySource
from sources.firecrawl_scraper import FirecrawlSource
from sources.websearch import WebSearchSource


COMPANY_CRAWL_CONCURRENCY = 5
STALE_JOB_DAYS = 14


def log(msg):
    print(f"[COLLECTOR] {msg}", flush=True)


async def _score_and_store(jobs: list, profile_config: dict, stats: dict, db):
    min_store = int(profile_config.get("scoring", {}).get("min_score_to_store", 20))
    for job in jobs:
        result = score_job(job.title, job.description, job.location, profile_config=profile_config)
        if result["score"] < min_store:
            stats["filtered_out"] += 1
            if stats["filtered_out"] <= 3:
                log(f"  FILTERED [{result['score']}] {job.title[:50]}")
            continue

        job.relevance_score = result["score"]
        job.experience_level = result["experience_level"]
        job.india_friendly = result["india_friendly"]
        job.location_note = result["location_note"]

        existing_tech = set(t.strip() for t in job.tech_stack.split(",") if t.strip())
        existing_tech.update(result["tech_stack"])
        job.tech_stack = ", ".join(sorted(existing_tech))

        if not job.company_domain:
            job.company_domain = job.extract_domain()

        job_dict = job.model_dump()
        job_dict["id"] = job.id or job.make_fingerprint()
        job_dict["discovered_at"] = datetime.utcnow().isoformat()

        try:
            result_status = await insert_job(db, job_dict)
            if result_status == "inserted":
                stats["new"] += 1
                log(f"  NEW JOB [{result['score']}] {job.title[:60]}")
            elif result_status == "updated":
                stats["updated"] += 1
        except Exception as e:
            log(f"DB error storing job: {e}")


def _load_jsearch_usage():
    import sqlite3
    from datetime import date
    conn = sqlite3.connect(DB_PATH)
    today = date.today().isoformat()
    month_start = date.today().replace(day=1).isoformat()
    cur = conn.execute(
        "SELECT daily_count, monthly_count FROM api_usage WHERE source='jsearch' AND date=?",
        (today,)
    )
    row = cur.fetchone()
    if row:
        set_usage(row[0], row[1])
    else:
        cur2 = conn.execute(
            "SELECT SUM(daily_count) FROM api_usage WHERE source='jsearch' AND date>=?",
            (month_start,)
        )
        monthly = cur2.fetchone()[0] or 0
        set_usage(0, monthly)
    conn.close()


async def _fetch_from_source(source) -> list:
    try:
        jobs = await source.fetch()
        log(f"  [OK] {source.name}: {len(jobs)} jobs")
        return jobs
    except Exception as e:
        log(f"  [FAIL] {source.name}: {e}")
        return []


async def _scrape_job_boards(profile_config: dict) -> list:
    """Scrape blockchain job board listing pages via Firecrawl.
    These are the most reliable source of actual blockchain/web3 jobs."""
    boards = [
        {"url": "https://web3.career/blockchain-jobs", "name": "Web3Career"},
        {"url": "https://web3.career/solidity-jobs", "name": "Web3Career"},
        {"url": "https://web3.career/remote-jobs", "name": "Web3Career"},
        {"url": "https://cryptocurrencyjobs.co/web3/", "name": "CryptoJobsList"},
        {"url": "https://cryptocurrencyjobs.co/remote/", "name": "CryptoJobsList"},
    ]
    jobs = []
    for board in boards:
        try:
            src = FirecrawlSource(url=board["url"], company_name=board["name"])
            board_jobs = await src.fetch()
            jobs.extend(board_jobs)
            log(f"  [OK] {board['name']}: {len(board_jobs)} jobs from {board['url']}")
        except Exception as e:
            log(f"  [FAIL] {board['name']}: {e}")
    return jobs


async def run_job_boards(profile_config: dict, db) -> dict:
    _load_jsearch_usage()

    sources = [
        RemotiveSource(),
        RemoteOKSource(),
        ArbeitnowSource(),
        WebSearchSource(),
    ]

    jsearch_queries = profile_config.get("search", {}).get("jsearch_default_queries", [])
    if jsearch_queries and can_use_jsearch():
        sources.append(JSearchSource(queries=jsearch_queries))

    tasks = [_fetch_from_source(src) for src in sources]
    board_task = _scrape_job_boards(profile_config)
    results = await asyncio.gather(*tasks)
    board_jobs = await board_task

    all_jobs = []
    jsearch_count = 0
    for src, jobs in zip(sources, results):
        if src.name == "jsearch":
            jsearch_count = len(jobs)
        all_jobs.extend(jobs)
    all_jobs.extend(board_jobs)

    stats = {"fetched": len(all_jobs), "new": 0, "updated": 0, "filtered_out": 0, "jsearch_used": jsearch_count}
    await _score_and_store(all_jobs, profile_config, stats, db)

    # Update API usage in DB
    if jsearch_count > 0:
        await increment_api_usage(db, "jsearch", jsearch_count)

    return stats


async def run_company_crawl(db, profile_config: dict, company_ids: list = None) -> dict:
    companies = await get_companies(db, crawl_status="active")
    if company_ids:
        companies = [c for c in companies if c["id"] in company_ids]
    if not companies:
        log("No active companies to crawl")
        return {"fetched": 0, "new": 0, "updated": 0, "filtered_out": 0}

    log(f"Crawling {len(companies)} companies...")
    semaphore = asyncio.Semaphore(COMPANY_CRAWL_CONCURRENCY)

    async def crawl_one(company: dict) -> list:
        ats = company.get("ats_platform", "unknown")
        if ats == "greenhouse":
            src = GreenhouseSource(company)
        elif ats == "lever":
            src = LeverSource(company)
        elif ats == "ashby":
            src = AshbySource(company)
        elif ats == "firecrawl":
            if company.get("careers_url"):
                src = FirecrawlSource(url=company["careers_url"], company_name=company["name"])
            else:
                return []
        else:
            return []

        async with semaphore:
            return await _fetch_from_source(src)

    tasks = [crawl_one(c) for c in companies]
    results = await asyncio.gather(*tasks)

    all_jobs = [j for batch in results for j in batch]
    stats = {"fetched": len(all_jobs), "new": 0, "updated": 0, "filtered_out": 0}
    await _score_and_store(all_jobs, profile_config, stats, db)
    return stats


async def run_firecrawl_url(url: str, company_name: str, profile_config: dict, db) -> dict:
    src = FirecrawlSource(url=url, company_name=company_name)
    jobs = await _fetch_from_source(src)
    stats = {"fetched": len(jobs), "new": 0, "updated": 0, "filtered_out": 0}
    await _score_and_store(jobs, profile_config, stats, db)
    return stats


async def run_collection(profile_config: dict, include_companies: bool = True) -> dict:
    db = await aiosqlite.connect(DB_PATH)
    await init_db()

    log("=" * 50)
    log("Starting full collection...")

    # Job boards
    board_stats = await run_job_boards(profile_config, db)

    # Company crawl
    company_stats = {"fetched": 0, "new": 0, "updated": 0, "filtered_out": 0}
    if include_companies:
        company_stats = await run_company_crawl(db, profile_config)

    # Cleanup stale jobs
    deleted = await cleanup_old_jobs(db, days=STALE_JOB_DAYS)
    log(f"  Deleted {deleted} stale jobs")

    total = {
        "fetched": board_stats["fetched"] + company_stats["fetched"],
        "new": board_stats["new"] + company_stats["new"],
        "updated": board_stats["updated"] + company_stats["updated"],
        "filtered_out": board_stats["filtered_out"] + company_stats["filtered_out"],
        "deleted_stale": deleted,
        "jsearch_used": board_stats.get("jsearch_used", 0),
    }

    await log_daily_run(
        db,
        source="full_collection",
        fetched=total["fetched"],
        new=total["new"],
        updated=total["updated"],
        filtered_out=total["filtered_out"],
        jsearch_used=total.get("jsearch_used", 0),
    )

    await db.close()

    log(f"  Total fetched: {total['fetched']}")
    log(f"  New: {total['new']} | Updated: {total['updated']} | Filtered: {total['filtered_out']}")
    log(f"  JSearch reqs used: {total['jsearch_used']}")
    log("Collection complete!")
    return total


async def cleanup_old_jobs(db, days=14):
    from datetime import datetime, timedelta
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    cursor = await db.execute(
        "DELETE FROM jobs WHERE discovered_at < ? AND status IN ('new', 'stale')",
        (cutoff,)
    )
    await db.commit()
    return cursor.rowcount
