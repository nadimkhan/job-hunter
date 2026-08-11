# Job Hunter — Build Phases

## Architecture

```
main.py                      FastAPI app (web + background tasks)
├── core/
│   ├── database.py          SQLite via aiosqlite (async)
│   ├── models.py           Pydantic models
│   ├── collector.py        Job collection orchestrator
│   ├── scorer.py           Rule-based relevance scoring
│   ├── hunter.py           LinkedIn URL builder + DM templates
│   ├── profile.py          Profile CRUD (DB-backed)
│   └── firecrawl_scraper.py Firecrawl direct-site scraper
├── sources/
│   ├── jsearch.py          JSearch (rate-limited: 3 reqs/run, max 6/day)
│   ├── remotive.py         Remotive (free)
│   ├── remoteok.py         RemoteOK (free)
│   ├── arbeitnow.py         Arbeitnow (free)
│   ├── greenhouse.py       Greenhouse ATS (free API)
│   ├── lever.py            Lever ATS (free API)
│   ├── ashby.py            Ashby ATS (free API)
│   └── base.py             BaseSource ABC
├── bot/
│   ├── __init__.py
│   ├── app.py              python-telegram-bot Application
│   ├── handlers.py         Command + message handlers
│   └── states.py           Conversation states
└── web/
    ├── index.html          Single-page app (all sections)
    ├── style.css           Notion-style dark/light responsive CSS
    └── app.js              Vanilla JS SPA
```

## Job Source Priority (daily run = 8h interval, 3 JSearch reqs)

| Source | Cost | Reqs/run | Notes |
|--------|------|----------|-------|
| Remotive | Free | 1 | Remote dev jobs |
| RemoteOK | Free | 1 | Remote jobs |
| Arbeitnow | Free | 1 | Remote jobs |
| JSearch | 200/mo | 3 | LinkedIn/Indeed aggregated (6 runs/day × 3 = 18/day → 540/mo, cap at 6/day = 180/mo) |

## JSearch Rate Limiting
- Track `api_usage` table with `daily_count` and `monthly_count`
- Each JSearch run uses AT MOST 3 queries (configurable)
- Hard cap: if daily_count >= 18 or monthly_count >= 180, skip JSearch that run
- Firecrawl direct-company scraping does NOT count against JSearch limit

## Resume Storage
- File: `resumes/{profile_id}/{role_slug}.pdf`
- Metadata in `resumes` table: profile_id, role_name, file_path, uploaded_at
- Max file size: 5MB
- Allowed types: .pdf, .docx, .doc

## Telegram Bot Commands
| Command | Description |
|---------|-------------|
| `/start` | Welcome + help |
| `/jobs [n]` | Show top N jobs from latest run |
| `/collect` | Trigger full collection now |
| `/firecrawl <url>` | Scrape a company's career page directly |
| `/firecrawl_list` | List companies ready for Firecrawl scrape |
| `/profile` | Show active profile |
| `/profile list` | List all profiles |
| `/profile set <id>` | Switch active profile |
| `/profile edit <id> ...` | Edit profile fields inline |
| `/profile yaml` | Import/export YAML |
| `/resume list` | List uploaded resumes |
| `/resume upload` | Upload resume for a role |
| `/outreach <job_id>` | Generate outreach for a job |
| `/status` | API usage stats, last run info |
| `/help` | Full command reference |

## Web UI Sections (single-page, hash-based routing)
1. **Dashboard** — stats, last run, top jobs
2. **Jobs** — filterable job list with score, source, india_friendly
3. **Profiles** — create, edit, import YAML, set active
4. **Resumes** — upload, list, delete per-role resumes
5. **Outreach** — generated DMs per job, LinkedIn URLs
6. **Companies** — add/manage companies for Firecrawl scraping
7. **Settings** — Telegram bot config, JSearch daily limit, Firecrawl key

## Cron Jobs (Hermes)
1. **Job Collection** — every 8h, 3 JSearch reqs, all free sources
2. **Daily Digest** — once/day (separate from collection), top jobs to Telegram Resume Builder topic
3. Firecrawl company scrape — on-demand via Telegram only

## Database Schema
- `jobs` — discovered jobs with scores
- `profiles` — YAML config blobs (JSON column)
- `resumes` — resume metadata + file path
- `outreach` — generated LinkedIn DMs
- `companies` — company list for Firecrawl scraping
- `api_usage` — daily/monthly JSearch call counts
- `firecrawl_queue` — pending URLs for on-demand scraping
- `email_logs` — sent digest history

## Tech Stack
- FastAPI + Uvicorn (HTTP + WS for live updates)
- aiosqlite (async SQLite)
- python-telegram-bot v20
- httpx + BeautifulSoup
- PyYAML (profile YAML import/export)
- python-multipart (file uploads)
- APScheduler (internal scheduler as backup; primary is Hermes cron)
- Vanilla JS/CSS (web UI — no framework, mobile responsive)
