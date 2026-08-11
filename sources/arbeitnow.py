"""Arbeitnow — fully free, no API key needed."""
import httpx
from datetime import datetime
from sources.base import BaseSource
from core.models import Job


class ArbeitnowSource(BaseSource):
    name = "arbeitnow"
    BASE_URL = "https://www.arbeitnow.com/api/job-board-api"

    async def fetch(self) -> list[Job]:
        jobs = []
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.get(self.BASE_URL)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                self.log(f"HTTP error: {e}")
                return []

        for item in data.get("data", []):
            created = item.get("created_at", "")
            if isinstance(created, int):
                created = datetime.utcfromtimestamp(created).isoformat()

            tags = item.get("tags", [])
            tags_str = ", ".join(tags) if isinstance(tags, list) else str(tags)

            job = Job(
                title=item.get("title", ""),
                company=item.get("company_name", ""),
                location=item.get("location", "Remote"),
                description=item.get("description", ""),
                url=item.get("url", ""),
                source=self.name,
                posted_date=str(created),
                job_type="full-time" if item.get("remote") else "on-site",
                tech_stack=tags_str,
            )
            job.id = job.make_fingerprint()
            jobs.append(job)

        self.log(f"Fetched {len(jobs)} jobs")
        return jobs
