"""Greenhouse ATS — free public API, no auth needed."""
import httpx
from sources.base import BaseSource
from core.models import Job


class GreenhouseSource(BaseSource):
    name = "greenhouse"

    def __init__(self, company: dict):
        self.company = company
        self.slug = company.get("ats_slug", "")

    async def fetch(self) -> list[Job]:
        if not self.slug:
            self.log("No Greenhouse slug, skipping")
            return []

        url = f"https://boards-api.greenhouse.io/v1/boards/{self.slug}/jobs"
        params = {"content": "true"}

        async with httpx.AsyncClient(timeout=20) as client:
            try:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                self.log(f"HTTP error: {e}")
                return []

        jobs = []
        for item in data.get("jobs", []):
            loc_data = item.get("location", {})
            location = loc_data.get("name", "") if isinstance(loc_data, dict) else (loc_data or "Remote")

            job = Job(
                title=item.get("title", ""),
                company=self.company["name"],
                location=location or "Remote",
                description=item.get("content", ""),
                url=item.get("absolute_url", ""),
                source=f"greenhouse:{self.slug}",
                posted_date=item.get("updated_at", ""),
                company_domain=self.company.get("domain", ""),
            )
            job.id = job.make_fingerprint()
            jobs.append(job)

        self.log(f"Fetched {len(jobs)} jobs")
        return jobs
