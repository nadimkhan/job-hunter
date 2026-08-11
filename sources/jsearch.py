"""JSearch via RapidAPI — aggregates LinkedIn, Indeed, Glassdoor, ZipRecruiter.
Rate-limited: max 3 queries per collection run, max 6 runs/day (18 reqs/day → ~540/mo).
Free tier: 200 req/month. We cap at 180/mo to stay safe."""
import httpx
from sources.base import BaseSource
from core.models import Job
from config.settings import RAPIDAPI_KEY

# These are injected at runtime by collector
_global_usage = {"daily": 0, "monthly": 0}
MAX_JSEARCH_PER_RUN = 3   # hard cap enforced per run
_daily_limit = 18      # max JSearch calls per day
_monthly_limit = 180   # max per month (stay under 200 free tier)


def can_use_jsearch() -> bool:
    return bool(RAPIDAPI_KEY) and _global_usage["daily"] < _daily_limit and _global_usage["monthly"] < _monthly_limit


def set_usage(daily: int, monthly: int):
    _global_usage["daily"] = daily
    _global_usage["monthly"] = monthly


class JSearchSource(BaseSource):
    name = "jsearch"
    BASE_URL = "https://jsearch.p.rapidapi.com/search"

    def __init__(self, queries: list[dict] = None):
        self.queries = (queries or [])[:3]  # max 3 per run, enforced here too

    async def fetch(self) -> list[Job]:
        if not RAPIDAPI_KEY:
            self.log("No RAPIDAPI_KEY, skipping")
            return []

        if not can_use_jsearch():
            remaining_day = _daily_limit - _global_usage["daily"]
            remaining_month = _monthly_limit - _global_usage["monthly"]
            self.log(f"Rate limit reached (daily:{remaining_day} left, monthly:{remaining_month} left), skipping")
            return []

        headers = {
            "x-rapidapi-host": "jsearch.p.rapidapi.com",
            "x-rapidapi-key": RAPIDAPI_KEY,
        }

        all_jobs = []
        queries_to_run = self.queries[:3]  # hard cap at 3

        async with httpx.AsyncClient(timeout=60) as client:
            for q in queries_to_run:
                if not can_use_jsearch():
                    self.log("Rate limit hit mid-run, stopping")
                    break

                try:
                    params = {
                        **q,
                        "page": 1,
                        "num_pages": 1,
                        "employment_types": "FULLTIME",
                    }
                    resp = await client.get(self.BASE_URL, headers=headers, params=params)
                    if resp.status_code != 200:
                        self.log(f"HTTP {resp.status_code} for query: {q.get('query', '')}")
                        continue

                    data = resp.json()
                    for item in data.get("data", []):
                        job = self._map_job(item)
                        if job:
                            all_jobs.append(job)

                    # Track usage
                    _global_usage["daily"] += 1
                    _global_usage["monthly"] += 1
                    self.log(f"Query done: {q.get('query', '')} ({len(data.get('data', []))} jobs)")

                except Exception as e:
                    self.log(f"Error: {e}")
                    continue

        self.log(f"Total: {len(all_jobs)} jobs from JSearch")
        return all_jobs

    def _map_job(self, item: dict) -> Job | None:
        title = item.get("job_title", "")
        company = item.get("employer_name", "")
        if not title or not company:
            return None

        location_parts = [item.get("job_city", ""), item.get("job_state", ""), item.get("job_country", "")]
        location = ", ".join(p for p in location_parts if p) or "Remote"
        if item.get("job_is_remote"):
            location = "Remote" if not location_parts[0] else f"Remote / {location}"

        salary = ""
        if item.get("job_min_salary") and item.get("job_max_salary"):
            period = item.get("job_salary_period", "year").lower()
            salary = f"${item['job_min_salary']:,} - ${item['job_max_salary']:,} / {period}"

        url = item.get("job_apply_link", "") or item.get("job_google_link", "")

        domain = ""
        emp_website = item.get("employer_website", "")
        if emp_website:
            domain = emp_website.replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")

        job = Job(
            title=title,
            company=company,
            location=location,
            description=item.get("job_description", "")[:5000],
            url=url,
            source="jsearch",
            posted_date=item.get("job_posted_at_datetime_utc", "") or item.get("job_posted_at", ""),
            company_domain=domain,
            salary=salary,
            job_type=item.get("job_employment_type", "FULLTIME").lower(),
        )
        job.id = job.make_fingerprint()
        return job
