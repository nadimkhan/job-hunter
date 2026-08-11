"""Lever ATS — free public API, no auth needed."""
import httpx
from datetime import datetime
from sources.base import BaseSource
from core.models import Job


class LeverSource(BaseSource):
    name = "lever"

    def __init__(self, company: dict):
        self.company = company
        self.slug = company.get("ats_slug", "")

    async def fetch(self) -> list[Job]:
        if not self.slug:
            self.log("No Lever slug, skipping")
            return []

        url = f"https://api.lever.co/v0/postings/{self.slug}"
        params = {"mode": "json"}

        async with httpx.AsyncClient(timeout=20) as client:
            try:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                self.log(f"HTTP error: {e}")
                return []

        if not isinstance(data, list):
            self.log(f"Unexpected response format, skipping")
            return []

        jobs = []
        for item in data:
            created_at = item.get("createdAt")
            posted = ""
            if created_at and isinstance(created_at, (int, float)):
                posted = datetime.utcfromtimestamp(created_at / 1000).isoformat()

            categories = item.get("categories", {}) or {}
            location = categories.get("location", "") or "Remote"

            job = Job(
                title=item.get("text", ""),
                company=self.company["name"],
                location=location,
                description=item.get("descriptionPlain", "") or item.get("description", ""),
                url=item.get("hostedUrl", ""),
                source=f"lever:{self.slug}",
                posted_date=posted,
                company_domain=self.company.get("domain", ""),
            )
            job.id = job.make_fingerprint()
            jobs.append(job)

        self.log(f"Fetched {len(jobs)} jobs")
        return jobs
