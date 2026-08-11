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
                if not data.get("success"):
                    self.log(f"Scrape status: {data.get('status')}")
                    return []

                page_data = data.get("data", {})
                markdown = page_data.get("markdown") or page_data.get("content") or ""
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
        Handles formats from web3.career, cryptocurrencyjobs.co, and generic listings.
        """
        import re

        jobs = []
        lines = markdown.split("\n")
        seen = set()

        for line in lines:
            line = line.strip()
            if not line or len(line) < 5:
                continue

            # Skip headers, empty lines, non-job lines
            if re.match(r"^#{1,6}\s", line):
                continue
            if re.match(r"^\*\*.*\*\*$", line):
                continue
            if re.match(r"^\|?\s*\[.*\]\(https?://\*(?:web3|crypto|blockchain)", line):
                continue

            url = ""
            title = ""

            # Format 1: | [**Job Title**](https://...) or [**Job Title**](https://...)
            # web3.career uses: | [**Senior Engineer**](url)
            for pattern in [
                r'\[\*\*([^\]]+)\*\*\]\((https?://[^\)]+)\)',
                r'\[([^\]]+)\]\((https?://[^\)]+)\)',
            ]:
                m = re.search(pattern, line)
                if m:
                    title = m.group(1).strip()
                    url = m.group(2).strip()
                    break

            # Format 2: ## [Job Title](url)  — cryptocurrencyjobs.co
            if not title:
                m = re.search(r'##\s+\[([^\]]+)\]\((https?://[^\)]+)\)', line)
                if m:
                    title = m.group(1).strip()
                    url = m.group(2).strip()

            if not title and not url:
                continue

            # Skip non-job links
            skip_domains = ["firecrawl", "linkedin.com/company", "twitter.com",
                            "github.com", "facebook.com", "instagram.com"]
            if url and any(s in url for s in skip_domains):
                continue

            # Skip navigation/meta links
            skip_keywords = ["sign in", "sign up", "register", "login", "create profile",
                             "post a job", "pricing", "about", "blog", "home"]
            if any(kw in line.lower() for kw in skip_keywords):
                continue

            # Clean title
            title = re.sub(r'\*\*([^\*]+)\*\*', r'\1', title)
            title = re.sub(r'\*\*', '', title)
            title = title.strip(" *-:|")
            title = re.sub(r'\s+', ' ', title)

            if len(title) < 3 or len(title) > 200:
                continue

            fingerprint = f"{self.company_name.lower().strip()}|{title.lower().strip()}|{url}"
            fid = hash(fingerprint) % (10**12)
            fingerprint = f"{fid:012x}"

            if fingerprint in seen:
                continue
            seen.add(fingerprint)

            # Try to extract company from title or URL
            company = self.company_name
            if not company or company == "Unknown":
                company = self._extract_company_from_url(url) or self._extract_company_from_title(title)

            job = Job(
                title=title,
                company=company,
                location="Remote",
                description=line[:500],
                url=url,
                source=f"firecrawl:{url}",
                company_domain=self._extract_domain(url),
            )
            job.id = fingerprint
            jobs.append(job)

        return jobs

    def _extract_company_from_url(self, url: str) -> str:
        if not url:
            return ""
        import re
        host = re.sub(r"^https?://(www\.)?", "", url.split("/")[2] if "/" in url else url)
        host = re.sub(r"\.(com|org|io|co|net|dev).*$", "", host, flags=re.IGNORECASE)
        return host.replace("-", " ").replace("_", " ").title().strip()

    def _extract_company_from_title(self, title: str) -> str:
        # Format: "Job Title at Company" or "Company — Job Title"
        import re
        m = re.search(r'\bat\s+(\w+)', title, re.IGNORECASE)
        if m:
            return m.group(1).title()
        m = re.search(r'(\w+)\s*[—-]\s*.+', title)
        if m:
            return m.group(1).title()
        return ""

    def _extract_domain(self, url: str) -> str:
        if not url:
            return ""
        import re
        m = re.search(r'https?://(?:www\.)?([^\s/]+)', url)
        return m.group(1) if m else ""
