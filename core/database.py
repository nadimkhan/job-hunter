import aiosqlite, json, sqlite3
from datetime import datetime, date
from typing import Optional
from config.settings import DB_PATH, RESUME_DIR

# ─── Init ─────────────────────────────────────────────────────────────────────

INIT_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT DEFAULT 'Remote',
    description TEXT DEFAULT '',
    url TEXT DEFAULT '',
    source TEXT DEFAULT '',
    posted_date TEXT,
    discovered_at TEXT,
    tech_stack TEXT DEFAULT '',
    experience_level TEXT DEFAULT 'mid',
    relevance_score INTEGER DEFAULT 0,
    status TEXT DEFAULT 'new',
    company_domain TEXT DEFAULT '',
    salary TEXT DEFAULT '',
    job_type TEXT DEFAULT 'full-time',
    india_friendly TEXT DEFAULT 'unknown',
    location_note TEXT DEFAULT '',
    resume_id TEXT,
    UNIQUE(id)
);

CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    is_active INTEGER DEFAULT 0,
    config TEXT DEFAULT '{}',
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS resumes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id INTEGER DEFAULT 1,
    role_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    file_size INTEGER DEFAULT 0,
    uploaded_at TEXT,
    FOREIGN KEY (profile_id) REFERENCES profiles(id)
);

CREATE TABLE IF NOT EXISTS outreach (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    job_title TEXT NOT NULL,
    company TEXT NOT NULL,
    company_domain TEXT DEFAULT '',
    contact_name TEXT DEFAULT '[Search LinkedIn]',
    contact_position TEXT DEFAULT '',
    contact_linkedin TEXT DEFAULT '',
    dm_short TEXT DEFAULT '',
    dm_long TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    notes TEXT DEFAULT '[]',
    created_at TEXT,
    messaged_at TEXT DEFAULT '',
    replied_at TEXT DEFAULT '',
    followed_up_at TEXT DEFAULT '',
    emailed_at TEXT DEFAULT '',
    profile_id INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    domain TEXT DEFAULT '',
    careers_url TEXT DEFAULT '',
    ats_platform TEXT DEFAULT 'unknown',
    ats_slug TEXT DEFAULT '',
    founded_year INTEGER DEFAULT 0,
    employee_count TEXT DEFAULT '',
    tags TEXT DEFAULT '',
    india_friendly TEXT DEFAULT 'unknown',
    last_crawled TEXT DEFAULT '',
    crawl_status TEXT DEFAULT 'active',
    notes TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS api_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    date TEXT NOT NULL,
    daily_count INTEGER DEFAULT 0,
    monthly_count INTEGER DEFAULT 0,
    UNIQUE(source, date)
);

CREATE TABLE IF NOT EXISTS firecrawl_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL,
    url TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at TEXT,
    completed_at TEXT,
    jobs_found INTEGER DEFAULT 0,
    error TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS email_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipient TEXT NOT NULL,
    subject TEXT NOT NULL,
    jobs_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'sent',
    error TEXT DEFAULT '',
    sent_at TEXT
);

CREATE TABLE IF NOT EXISTS daily_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT NOT NULL,
    source TEXT DEFAULT '',
    fetched INTEGER DEFAULT 0,
    new INTEGER DEFAULT 0,
    updated INTEGER DEFAULT 0,
    filtered_out INTEGER DEFAULT 0,
    jsearch_used INTEGER DEFAULT 0,
    error TEXT DEFAULT ''
);
"""

DEFAULT_PROFILE_CONFIG = {
    "search": {
        "default_terms": [
            "blockchain developer",
            "smart contract developer",
            "web3 developer",
            "solidity developer",
            "content creator blockchain",
        ],
        "title_keywords_positive": [
            "blockchain", "web3", "solidity", "smart contract",
            "content", "video creator", "community manager",
            "technical writer", "developer relations",
        ],
        "title_keywords_negative": [
            "frontend", "ios", "android", "mobile", "intern",
            "junior", "senior only", "us only",
        ],
        "relevant_tech": [
            "solidity", "rust", "web3.js", "ethers.js", "hardhat",
            "foundry", "nft", "defi", "dao", "ethereum", "polygon",
            "javascript", "python", "react", "node", "ipfs",
            "chainlink", "openzeppelin", "figma", "motion design",
            "after effects", "premiere pro", "blender", "ue5",
        ],
        "jsearch_default_queries": [
            {"query": "blockchain developer remote", "country": "us", "date_posted": "3days", "remote_jobs_only": True},
            {"query": "web3 solidity developer", "country": "us", "date_posted": "3days", "remote_jobs_only": True},
            {"query": "blockchain content creator", "country": "us", "date_posted": "week", "remote_jobs_only": False},
        ],
    },
    "scoring": {
        "experience_target": "mid",
        "min_relevance_score": 50,
        "min_score_to_store": 20,
        "weights": {"title": 35, "tech": 35, "experience": 15, "signal": 15},
        "core_tech": ["solidity", "rust", "web3.js", "ethers.js", "hardhat", "foundry"],
        "backend_signals": ["defi", "dao", "nft", "smart contract", "gas optimization", "token"],
    },
    "location": {
        "india_positive": ["india", "asia", "worldwide", "global", "anywhere", "remote", "apac"],
        "india_negative": ["us only", "usa only", "uk only", "eu only", "canada only"],
        "timezone_compatible": ["ist", "gmt", "utc", "cet", "flexible", "async", "remote"],
        "timezone_incompatible": ["pst only", "est only", "us timezone required"],
    },
    "outreach": {
        "candidate_name": "Nadim Khan",
        "candidate_core_tech": ["solidity", "web3.js", "blockchain"],
        "candidate_extra_tech": ["react", "python", "node"],
        "linkedin_search_titles": [
            {"title": "Engineering Manager", "label": "Eng Manager", "category": "engineering"},
            {"title": "Tech Lead", "label": "Tech Lead", "category": "engineering"},
            {"title": "Head of Engineering", "label": "Head of Eng", "category": "engineering"},
            {"title": "CTO", "label": "CTO", "category": "executive"},
            {"title": "Founder CEO", "label": "CEO / Founder", "category": "executive"},
            {"title": "Technical Recruiter", "label": "Tech Recruiter", "category": "hr"},
            {"title": "HR Manager", "label": "HR Manager", "category": "hr"},
        ],
        "bio_short": "3+ years in {stack}",
        "achievements": [
            "Built blockchain content channel with 10K+ subscribers.",
            "Deployed Solidity smart contracts on Ethereum mainnet.",
            "Created developer tooling and technical documentation for DeFi protocols.",
        ],
        "dm_short_template": "{greeting}, I noticed {company} is hiring for {title}. I have {bio_short} — built on-chain voting dApps and DeFi dashboards. Would love to connect.",
        "dm_long_template": "{greeting},\n\nNoticed {company} is hiring for {title}. I've been working in the blockchain space for 3+ years, mostly with Solidity, Web3.js, and Ethereum.\n\n{achievements}\n\nOpen to a 15-min chat?\n\nThanks,\n{candidate_name}",
        "email_digest_subject_role": "blockchain/web3",
        "email_greeting": "Your Daily Job Digest",
        "recipient_email": "",
    },
}


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(INIT_SQL)
        await db.execute("""CREATE TABLE IF NOT EXISTS cron_toggles (
            job_id TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )""")
        await db.execute("""INSERT OR IGNORE INTO cron_toggles (job_id, enabled) VALUES
            ('collect_8h', 1), ('daily_digest', 1)""")
        await db.commit()

        # Seed default profile if none exist
        cursor = await db.execute("SELECT COUNT(*) FROM profiles")
        count = (await cursor.fetchone())[0]
        if count == 0:
            await db.execute(
                """INSERT INTO profiles (name, description, is_active, config, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    "Blockchain / Web3 Default",
                    "Default profile for blockchain, web3, and content roles",
                    1,
                    json.dumps(DEFAULT_PROFILE_CONFIG),
                    datetime.utcnow().isoformat(),
                    datetime.utcnow().isoformat(),
                )
            )
            await db.commit()


def get_sync_db():
    """For non-async contexts like Flask/file uploads."""
    return sqlite3.connect(DB_PATH, check_same_thread=False)


# ─── Jobs ─────────────────────────────────────────────────────────────────────

def insert_job_sync(job_dict: dict) -> str:
    """Sync version for use in async-to-sync bridge."""
    conn = get_sync_db()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO jobs
            (id, title, company, location, description, url, source, posted_date,
             discovered_at, tech_stack, experience_level, relevance_score, status,
             company_domain, salary, job_type, india_friendly, location_note, resume_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            job_dict.get("id"), job_dict.get("title"), job_dict.get("company"),
            job_dict.get("location"), job_dict.get("description"), job_dict.get("url"),
            job_dict.get("source"), job_dict.get("posted_date"),
            job_dict.get("discovered_at"), job_dict.get("tech_stack"),
            job_dict.get("experience_level"), job_dict.get("relevance_score"),
            job_dict.get("status"), job_dict.get("company_domain"),
            job_dict.get("salary"), job_dict.get("job_type"),
            job_dict.get("india_friendly"), job_dict.get("location_note"),
            job_dict.get("resume_id"),
        ))
        conn.commit()
        return "inserted"
    except Exception as e:
        if "UNIQUE" in str(e):
            conn.execute("""
                UPDATE jobs SET relevance_score=?, status='new', discovered_at=?,
                tech_stack=?, india_friendly=?, location_note=?, experience_level=?,
                resume_id=?
                WHERE id=?
            """, (
                job_dict.get("relevance_score"), job_dict.get("discovered_at"),
                job_dict.get("tech_stack"), job_dict.get("india_friendly"),
                job_dict.get("location_note"), job_dict.get("experience_level"),
                job_dict.get("resume_id"), job_dict.get("id"),
            ))
            conn.commit()
            return "updated"
        return "error"
    finally:
        conn.close()


async def insert_job(db, job_dict: dict) -> str:
    """Async version for use inside async contexts."""
    try:
        await db.execute("""
            INSERT OR REPLACE INTO jobs
            (id, title, company, location, description, url, source, posted_date,
             discovered_at, tech_stack, experience_level, relevance_score, status,
             company_domain, salary, job_type, india_friendly, location_note, resume_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            job_dict.get("id"), job_dict.get("title"), job_dict.get("company"),
            job_dict.get("location"), job_dict.get("description"), job_dict.get("url"),
            job_dict.get("source"), job_dict.get("posted_date"),
            job_dict.get("discovered_at"), job_dict.get("tech_stack"),
            job_dict.get("experience_level"), job_dict.get("relevance_score"),
            job_dict.get("status"), job_dict.get("company_domain"),
            job_dict.get("salary"), job_dict.get("job_type"),
            job_dict.get("india_friendly"), job_dict.get("location_note"),
            job_dict.get("resume_id"),
        ))
        await db.commit()
        return "inserted"
    except Exception as e:
        if "UNIQUE" in str(e):
            await db.execute("""
                UPDATE jobs SET relevance_score=?, status='new', discovered_at=?,
                tech_stack=?, india_friendly=?, location_note=?, experience_level=?,
                resume_id=?
                WHERE id=?
            """, (
                job_dict.get("relevance_score"), job_dict.get("discovered_at"),
                job_dict.get("tech_stack"), job_dict.get("india_friendly"),
                job_dict.get("location_note"), job_dict.get("experience_level"),
                job_dict.get("resume_id"), job_dict.get("id"),
            ))
            await db.commit()
            return "updated"
        return f"error: {e}"


async def get_jobs(db, source=None, status=None, min_score=0,
                   search=None, location=None, tech=None,
                   india_friendly=None, company_domain=None,
                   limit=50, offset=0, seen_after=None):
    where, params = [], []
    if source:       where.append("source LIKE ?");       params.append(f"%{source}%")
    if status:       where.append("status=?");            params.append(status)
    if min_score:    where.append("relevance_score>=?");  params.append(min_score)
    if search:       where.append("(title LIKE ? OR company LIKE ? OR description LIKE ?)"); params.extend([f"%{search}%"]*3)
    if location:     where.append("location LIKE ?");     params.append(f"%{location}%")
    if tech:         where.append("tech_stack LIKE ?");    params.append(f"%{tech}%")
    if india_friendly: where.append("india_friendly=?");   params.append(india_friendly)
    if company_domain: where.append("company_domain=?");   params.append(company_domain)
    if seen_after:   where.append("discovered_at>=?");    params.append(seen_after)

    sql = "SELECT * FROM jobs"
    if where: sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY relevance_score DESC, discovered_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor = await db.execute(sql, params)
    rows = await cursor.fetchall()
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, r)) for r in rows]


async def get_job_by_id(db, job_id: str):
    cursor = await db.execute("SELECT * FROM jobs WHERE id=?", (job_id,))
    row = await cursor.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cursor.description]
    return dict(zip(cols, row))


async def update_job_status(db, job_id: str, status: str):
    await db.execute("UPDATE jobs SET status=? WHERE id=?", (status, job_id))
    await db.commit()


async def get_stats(db):
    cursor = await db.execute("""
        SELECT status, COUNT(*) as count FROM jobs GROUP BY status
    """)
    rows = await cursor.fetchall()
    status_counts = dict(rows)
    total = sum(status_counts.values())

    cursor2 = await db.execute("SELECT COUNT(*) FROM jobs WHERE status='new'")
    new_count = (await cursor2.fetchone())[0]

    cursor3 = await db.execute("""
        SELECT date(discovered_at) as d, COUNT(*) FROM jobs
        WHERE discovered_at >= date('now', '-7 days')
        GROUP BY d ORDER BY d DESC
    """)
    week_rows = await cursor3.fetchall()

    return {
        "total": total,
        "new": new_count,
        "by_status": status_counts,
        "last_7_days": [{"date": r[0], "count": r[1]} for r in week_rows],
    }


# ─── Profiles ─────────────────────────────────────────────────────────────────

async def get_profiles(db):
    cursor = await db.execute("SELECT * FROM profiles ORDER BY is_active DESC, name ASC")
    rows = await cursor.fetchall()
    cols = [d[0] for d in cursor.description]
    result = []
    for r in rows:
        d = dict(zip(cols, r))
        if isinstance(d.get("config"), str):
            d["config"] = json.loads(d["config"])
        result.append(d)
    return result


async def get_active_profile(db):
    cursor = await db.execute("SELECT * FROM profiles WHERE is_active=1 LIMIT 1")
    row = await cursor.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cursor.description]
    d = dict(zip(cols, row))
    if isinstance(d.get("config"), str):
        d["config"] = json.loads(d["config"])
    return d


async def create_profile(db, name: str, description: str, config: dict):
    cursor = await db.execute(
        """INSERT INTO profiles (name, description, is_active, config, created_at, updated_at)
           VALUES (?, ?, 0, ?, ?, ?)""",
        (name, description, json.dumps(config), datetime.utcnow().isoformat(), datetime.utcnow().isoformat())
    )
    await db.commit()
    return cursor.lastrowid


async def update_profile(db, profile_id: int, name: str, description: str, config: dict):
    await db.execute(
        """UPDATE profiles SET name=?, description=?, config=?, updated_at=? WHERE id=?""",
        (name, description, json.dumps(config), datetime.utcnow().isoformat(), profile_id)
    )
    await db.commit()


async def set_active_profile(db, profile_id: int):
    await db.execute("UPDATE profiles SET is_active=0")
    await db.execute("UPDATE profiles SET is_active=1 WHERE id=?", (profile_id,))
    await db.commit()


async def delete_profile(db, profile_id: int):
    await db.execute("DELETE FROM profiles WHERE id=? AND is_active=0", (profile_id,))
    await db.commit()


# ─── Resumes ──────────────────────────────────────────────────────────────────

async def get_resumes(db, profile_id: int = None):
    sql = "SELECT * FROM resumes"
    params = []
    if profile_id:
        sql += " WHERE profile_id=?"
        params.append(profile_id)
    sql += " ORDER BY uploaded_at DESC"
    cursor = await db.execute(sql, params)
    rows = await cursor.fetchall()
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, r)) for r in rows]


async def insert_resume(db, profile_id: int, role_name: str, file_path: str,
                        original_filename: str, file_size: int):
    # Delete existing resume for same role
    await db.execute("DELETE FROM resumes WHERE profile_id=? AND role_name=?",
                     (profile_id, role_name))
    cursor = await db.execute(
        """INSERT INTO resumes (profile_id, role_name, file_path, original_filename, file_size, uploaded_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (profile_id, role_name, file_path, original_filename, file_size, datetime.utcnow().isoformat())
    )
    await db.commit()
    return cursor.lastrowid


async def delete_resume(db, resume_id: int):
    if resume_id is None:
        return
    await db.execute("DELETE FROM resumes WHERE id=?", (resume_id,))
    await db.commit()


# ─── Outreach ─────────────────────────────────────────────────────────────────

async def get_outreach(db, status=None, search=None, limit=100, offset=0):
    where, params = [], []
    if status:    where.append("status=?");           params.append(status)
    if search:    where.append("(company LIKE ? OR job_title LIKE ?)"); params.extend([f"%{search}%"]*2)
    sql = "SELECT * FROM outreach"
    if where: sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    cursor = await db.execute(sql, params)
    rows = await cursor.fetchall()
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, r)) for r in rows]


async def insert_outreach(db, item: dict):
    await db.execute(
        """INSERT OR IGNORE INTO outreach
           (job_id, job_title, company, company_domain, contact_name, contact_position,
            contact_linkedin, dm_short, dm_long, status, notes, created_at, profile_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            item.get("job_id"), item.get("job_title"), item.get("company"),
            item.get("company_domain"), item.get("contact_name", "[Search LinkedIn]"),
            item.get("contact_position", ""), item.get("contact_linkedin", ""),
            item.get("dm_short", ""), item.get("dm_long", ""),
            item.get("status", "pending"), item.get("notes", "[]"),
            item.get("created_at", datetime.utcnow().isoformat()),
            item.get("profile_id", 0),
        )
    )
    await db.commit()


async def update_outreach_status(db, outreach_id: int, status: str):
    now = datetime.utcnow().isoformat()
    field_map = {"messaged": "messaged_at", "replied": "replied_at", "followed_up": "followed_up_at"}
    field = field_map.get(status, "")
    if field:
        await db.execute(f"UPDATE outreach SET status=?, {field}=? WHERE id=?",
                         (status, now, outreach_id))
    else:
        await db.execute("UPDATE outreach SET status=? WHERE id=?", (status, outreach_id))
    await db.commit()


async def outreach_exists_for_job(db, job_id: str) -> bool:
    cursor = await db.execute("SELECT COUNT(*) FROM outreach WHERE job_id=?", (job_id,))
    count = (await cursor.fetchone())[0]
    return count > 0


async def get_unemailed_outreach(db, limit=15):
    cursor = await db.execute(
        """SELECT o.*, j.title as job_title, j.url as job_url, j.relevance_score,
                  j.company_domain, j.location, j.salary, j.tech_stack
           FROM outreach o
           JOIN jobs j ON o.job_id = j.id
           WHERE o.emailed_at = '' OR o.emailed_at IS NULL
           ORDER BY j.relevance_score DESC
           LIMIT ?""", (limit,)
    )
    rows = await cursor.fetchall()
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, r)) for r in rows]


async def mark_outreach_emailed(db, outreach_ids: list):
    now = datetime.utcnow().isoformat()
    for oid in outreach_ids:
        await db.execute("UPDATE outreach SET emailed_at=? WHERE id=?", (now, oid))
    await db.commit()


# ─── Companies ────────────────────────────────────────────────────────────────

async def get_companies(db, ats_platform=None, crawl_status=None, search=None,
                        limit=200, offset=0):
    where, params = [], []
    if ats_platform:   where.append("ats_platform=?");      params.append(ats_platform)
    if crawl_status:   where.append("crawl_status=?");      params.append(crawl_status)
    if search:         where.append("name LIKE ?");         params.append(f"%{search}%")
    sql = "SELECT * FROM companies"
    if where: sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY name ASC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    cursor = await db.execute(sql, params)
    rows = await cursor.fetchall()
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, r)) for r in rows]


async def upsert_company(db, company: dict):
    await db.execute(
        """INSERT OR REPLACE INTO companies
           (name, domain, careers_url, ats_platform, ats_slug, founded_year,
            employee_count, tags, india_friendly, last_crawled, crawl_status, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            company["name"], company.get("domain", ""), company.get("careers_url", ""),
            company.get("ats_platform", "unknown"), company.get("ats_slug", ""),
            company.get("founded_year", 0), company.get("employee_count", ""),
            company.get("tags", ""), company.get("india_friendly", "unknown"),
            company.get("last_crawled", ""), company.get("crawl_status", "active"),
            company.get("notes", ""),
        )
    )
    await db.commit()


# ─── API Usage ────────────────────────────────────────────────────────────────

async def get_api_usage(db, source: str = "jsearch"):
    today = date.today().isoformat()
    month_start = date.today().replace(day=1).isoformat()
    cursor = await db.execute(
        "SELECT daily_count, monthly_count FROM api_usage WHERE source=? AND date=?",
        (source, today)
    )
    row = await cursor.fetchone()
    if row:
        return {"daily": row[0], "monthly": row[1], "date": today}
    # Check monthly from month start
    cursor2 = await db.execute(
        "SELECT SUM(daily_count) FROM api_usage WHERE source=? AND date>=?",
        (source, month_start)
    )
    monthly_total = (await cursor2.fetchone())[0] or 0
    return {"daily": 0, "monthly": monthly_total, "date": today}


async def increment_api_usage(db, source: str = "jsearch", count: int = 1):
    today = date.today().isoformat()
    month_start = date.today().replace(day=1).isoformat()
    cursor = await db.execute(
        "SELECT daily_count, monthly_count FROM api_usage WHERE source=? AND date=?",
        (source, today)
    )
    row = await cursor.fetchone()
    if row:
        new_daily = row[0] + count
        new_monthly = row[1] + count
        await db.execute(
            "UPDATE api_usage SET daily_count=?, monthly_count=? WHERE source=? AND date=?",
            (new_daily, new_monthly, source, today)
        )
    else:
        # Calculate monthly
        cursor2 = await db.execute(
            "SELECT SUM(daily_count) FROM api_usage WHERE source=? AND date>=?",
            (source, month_start)
        )
        monthly_so_far = (await cursor2.fetchone())[0] or 0
        await db.execute(
            "INSERT INTO api_usage (source, date, daily_count, monthly_count) VALUES (?, ?, ?, ?)",
            (source, today, count, monthly_so_far + count)
        )
    await db.commit()


# ─── Firecrawl Queue ─────────────────────────────────────────────────────────

async def add_firecrawl_url(db, company_name: str, url: str):
    await db.execute(
        "INSERT INTO firecrawl_queue (company_name, url, status, created_at) VALUES (?, ?, 'pending', ?)",
        (company_name, url, datetime.utcnow().isoformat())
    )
    await db.commit()


async def get_pending_firecrawl(db, limit=20):
    cursor = await db.execute(
        "SELECT * FROM firecrawl_queue WHERE status='pending' ORDER BY created_at ASC LIMIT ?",
        (limit,)
    )
    rows = await cursor.fetchall()
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, r)) for r in rows]


async def complete_firecrawl(db, queue_id: int, jobs_found: int, error: str = ""):
    await db.execute(
        "UPDATE firecrawl_queue SET status=?, completed_at=?, jobs_found=?, error=? WHERE id=?",
        ("completed" if not error else "failed", datetime.utcnow().isoformat(),
         jobs_found, error, queue_id)
    )
    await db.commit()


# ─── Email Logs ───────────────────────────────────────────────────────────────

async def log_email(db, recipient: str, subject: str, jobs_count: int,
                    status: str = "sent", error: str = ""):
    await db.execute(
        """INSERT INTO email_logs (recipient, subject, jobs_count, status, error, sent_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (recipient, subject, jobs_count, status, error, datetime.utcnow().isoformat())
    )
    await db.commit()


async def get_email_logs(db, limit=10):
    cursor = await db.execute(
        "SELECT * FROM email_logs ORDER BY sent_at DESC LIMIT ?", (limit,)
    )
    rows = await cursor.fetchall()
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, r)) for r in rows]


# ─── Daily Runs ───────────────────────────────────────────────────────────────

async def log_daily_run(db, source: str, fetched: int, new: int,
                         updated: int, filtered_out: int,
                         jsearch_used: int = 0, error: str = ""):
    await db.execute(
        """INSERT INTO daily_runs (run_at, source, fetched, new, updated,
                                   filtered_out, jsearch_used, error)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (datetime.utcnow().isoformat(), source, fetched, new, updated,
         filtered_out, jsearch_used, error)
    )
    await db.commit()


async def get_last_runs(db, limit=5):
    cursor = await db.execute(
        "SELECT * FROM daily_runs ORDER BY run_at DESC LIMIT ?", (limit,)
    )
    rows = await cursor.fetchall()
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, r)) for r in rows]


async def get_cron_toggles(db):
    """Returns dict of job_id -> enabled (bool)."""
    cursor = await db.execute("SELECT job_id, enabled FROM cron_toggles")
    rows = await cursor.fetchall()
    return {row[0]: bool(row[1]) for row in rows}


async def set_cron_toggle(db, job_id: str, enabled: bool):
    """Enable or disable a cron job by ID."""
    await db.execute(
        "INSERT OR REPLACE INTO cron_toggles (job_id, enabled, updated_at) VALUES (?, ?, datetime('now'))",
        (job_id, 1 if enabled else 0),
    )
    await db.commit()

