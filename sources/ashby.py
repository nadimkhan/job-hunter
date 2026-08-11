"""Ashby ATS — free public API, no auth needed."""
import httpx
from sources.base import BaseSource
from core.models import Job


class AshbySource(BaseSource):
    name = "ashby"

    def __init__(self, company: dict):
        self.company = company
        self.slug = company.get("ats_slug", "")

    async def fetch(self) -> list[Job]:
        if not self.slug:
            self.log("No Ashby slug, skipping")
            return []

        url = f"https://api.ashbyhq.com/posting-api/job-board/{self.slug}"

        async with httpx.AsyncClient(timeout=20) as client:
            try:
                resp = await client.get(url, params={"includeCompensation": "true"})
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                self.log(f"HTTP error: {e}")
                return []

        jobs = []
        for item in data.get("jobs", []):
            location = item.get("location", "")
            if isinstance(location, dict):
                location = location.get("name", "")

            salary = ""
            comp = item.get("compensation")
            if comp and isinstance(comp, dict):
                parts = comp.get("summaryComponents", [])
                if parts:
                    salary = " ".join(str(p) for p in parts)

            job = Job(
                title=item.get("title", ""),
                company=self.company["name"],
                location=location or "Remote",
                description=item.get("descriptionHtml", "") or item.get("descriptionPlain", ""),
                url=item.get("externalLink", "") or item.get("jobUrl", ""),
                source=f"ashby:{self.slug}",
                posted_date=item.get("publishedDate", ""),
                salary=salary,
                company_domain=self.company.get("domain", ""),
            )
            job.id = job.make_fingerprint()
            jobs.append(job)

        self.log(f"Fetched {len(jobs)} jobs")
        return jobs
