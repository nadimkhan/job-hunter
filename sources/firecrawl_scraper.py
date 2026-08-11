"""Firecrawl-based job scraper for direct company career pages.
Does NOT count against JSearch rate limits.
API docs: https://docs.firecrawl.dev"""
import httpx, asyncio
from sources.base import BaseSource
from core.models import Job
from config.settings import FIRECRAWL_API_KEY


class FirecrawlSource(BaseSource):
    """Scrape a company career page using Firecrawl. Used for on-demand scraping
    via Telegram command or firecrawl_queue table."""
    name = "firecrawl"

    def __init__(self, url: str = None, company_name: str = ""):
        self.url = url
        self.company_name = company_name
        self.api_key = FIRECRAWL_API_KEY

    async def fetch(self) -> list[Job]:
        if not self.api_key or not self.url:
            self.log("No Firecrawl API key or URL, skipping")
            return []

        jobs = []
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=120) as client:
            try:
                # 1. Scrape the page
                scrape_payload = {
                    "url": self.url,
                    "pageOptions": {"onlyMainContent": True},
                }
                resp = await client.post(
                    "https://api.firecrawl.dev/v0/scrape",
                    headers=headers,
                    json=scrape_payload,
                    timeout=120,
                )
                if resp.status_code != 200:
                    self.log(f"Scrape failed: HTTP {resp.status_code}")
                    return []

                data = resp.json()
                if data.get("status") != "success":
                    self.log(f"Scrape status: {data.get('status')}")
                    return []

                markdown = data.get("data", {}).get("markdown", "")
                if not markdown:
                    self.log("No markdown content extracted")
                    return []

                # 2. Extract job listings from markdown
                jobs = self._parse_jobs(markdown)

            except Exception as e:
                self.log(f"Firecrawl error: {e}")
                return []

        self.log(f"Extracted {len(jobs)} jobs from {self.url}")
        return jobs

    def _parse_jobs(self, markdown: str) -> list[Job]:
        """Parse job listings from markdown content.
        Looks for patterns like: Job Title | Company | Location | URL"""
        import re, json

        jobs = []
        lines = markdown.split("\n")
        seen = set()

        for i, line in enumerate(lines):
            line = line.strip()
            if not line or len(line) < 5:
                continue

            # Skip headers
            if re.match(r"^#{1,6}\s", line):
                continue
            if re.match(r"^\*\*.*\*\*$", line):  # bold-only lines
                continue

            # Look for URL in line (common in job listings)
            urls = re.findall(r"https?://[^\s\)>\]\"\'\,]+", line)
            url: str = ""
            for u in urls:
                skip_domains = ["firecrawl", "linkedin.com/company", "twitter.com", "github.com"]
                if not any(s in u for s in skip_domains):
                    url = u
                    break

            # Try to extract title — lines with job-like keywords
            job_keywords = ["engineer", "developer", "manager", "lead", "analyst",
                            "designer", "writer", "specialist", "director", "architect",
                            "content", "creator", "blockchain", "web3", "defi", "nft"]
            line_lower = line.lower()
            has_keyword = any(kw in line_lower for kw in job_keywords)

            if has_keyword or url:
                # Clean title: remove markdown links, pipes, etc.
                title = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", line)
                title = re.sub(r"\|.*", "", title)
                title = re.sub(r"\*\*([^\*]+)\*\*", r"\1", title)
                title = title.strip(" *-:")
                if len(title) < 5 or len(title) > 200:
                    continue

                fingerprint = f"{self.company_name.lower().strip()}|{title.lower().strip()}|remote"
                fid = hash(fingerprint) % (10**12)
                fingerprint = f"{fid:012x}"

                if fingerprint in seen:
                    continue
                seen.add(fingerprint)

                job = Job(
                    title=title,
                    company=self.company_name,
                    location="Remote",
                    description=line,
                    url=url,
                    source=f"firecrawl:{self.company_name}",
                    company_domain=self.company_name.lower().replace(" ", "") + ".com",
                )
                job.id = fingerprint
                jobs.append(job)

        return jobs
