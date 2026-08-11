"""Remotive — fully free, no API key needed."""
import httpx
from sources.base import BaseSource
from core.models import Job


class RemotiveSource(BaseSource):
    name = "remotive"
    BASE_URL = "https://remotive.com/api/remote-jobs"

    async def fetch(self) -> list[Job]:
        jobs = []
        params = {"category": "software-dev", "limit": 100}
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.get(self.BASE_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                self.log(f"HTTP error: {e}")
                return []

        for item in data.get("jobs", []):
            job = Job(
                title=item.get("title", ""),
                company=item.get("company_name", ""),
                location=item.get("candidate_required_location", "Anywhere"),
                description=item.get("description", ""),
                url=item.get("url", ""),
                source=self.name,
                posted_date=item.get("publication_date", ""),
                salary=item.get("salary", "") or "",
                job_type=item.get("job_type", ""),
            )
            job.id = job.make_fingerprint()
            jobs.append(job)

        self.log(f"Fetched {len(jobs)} jobs")
        return jobs
