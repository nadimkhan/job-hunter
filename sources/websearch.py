"""Firecrawl-based web search for blockchain/web3 jobs.
Searches the internet for job listings using Firecrawl Search API.
Uses profile keywords to build queries. Does NOT count against JSearch limits.
"""
import httpx, asyncio
from sources.base import BaseSource
from core.models import Job
from config.settings import FIRECRAWL_API_KEY

# Hardcoded blockchain/web3 search queries as fallback
DEFAULT_QUERIES = [
    "blockchain developer jobs remote 2026",
    "web3 solidity developer job openings",
    "smart contract developer remote blockchain jobs",
    "ethereum developer jobs hiring remote",
    "DeFi NFT developer job postings",
    "crypto web3 engineer full time remote",
    "blockchain content creator jobs remote",
    "web3 community manager jobs remote",
]


class WebSearchSource(BaseSource):
    """Search the web via Firecrawl for blockchain/web3 jobs.
    Falls back to hardcoded queries if profile config is unavailable.
    """
    name = "websearch"
    BASE_URL = "https://api.firecrawl.dev/v1/search"

    def __init__(self, queries: list[str] | None = None):
        self.queries = queries or DEFAULT_QUERIES
        self.api_key = FIRECRAWL_API_KEY

    async def fetch(self) -> list[Job]:
        if not self.api_key:
            self.log("No FIRECRAWL_API_KEY, skipping web search")
            return []

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        jobs = []
        seen = set()

        async with httpx.AsyncClient(timeout=60) as client:
            for query in self.queries:
                try:
                    payload = {
                        "query": query,
                        "limit": 10,
                    }
                    resp = await client.post(
                        self.BASE_URL,
                        headers=headers,
                        json=payload,
                        timeout=60,
                    )
                    if resp.status_code != 200:
                        self.log(f"Search failed for '{query}': HTTP {resp.status_code}")
                        continue

                    data = resp.json()
                    if not data.get("success"):
                        continue

                    for item in data.get("data", []):
                        url = item.get("url", "")
                        title = item.get("title", "")

                        # Skip if no useful data
                        if not title and not url:
                            continue

                        # Build fingerprint from URL or title
                        fp_input = url or title
                        fid = hash(fp_input.lower().strip()) % (10**12)
                        fingerprint = f"{fid:012x}"
                        if fingerprint in seen:
                            continue
                        seen.add(fingerprint)

                        # Try to extract job title and company from title
                        raw_title = title.strip()
                        company = ""
                        # Many listings format as "Job Title - Company Name" or "Company Name | Job Title"
                        if " - " in raw_title:
                            parts = raw_title.split(" - ", 1)
                            raw_title = parts[0].strip()
                            company = parts[1].strip().rstrip("|").strip()
                        elif " | " in raw_title:
                            parts = raw_title.split(" | ", 1)
                            company = parts[0].strip()
                            raw_title = parts[1].strip() if len(parts) > 1 else parts[0].strip()

                        # Clean title
                        title_clean = raw_title.replace("Jobs", "").replace("hiring", "").strip(" -|")

                        job = Job(
                            title=title_clean or raw_title,
                            company=company or self._infer_company(url),
                            location="Remote",
                            description=item.get("description", "")[:1000],
                            url=url,
                            source=self.name,
                            posted_date="",
                            job_type="full-time",
                        )
                        job.id = fingerprint
                        jobs.append(job)

                    self.log(f"WebSearch '{query}': {len(data.get('data', []))} results")

                except Exception as e:
                    self.log(f"WebSearch error for '{query}': {e}")
                    continue

        self.log(f"WebSearch total: {len(jobs)} jobs from {len(self.queries)} queries")
        return jobs

    def _infer_company(self, url: str) -> str:
        """Try to extract company name from URL."""
        if not url:
            return ""
        import re
        host = re.sub(r"^https?://(www\.)?", "", url.split("/")[2] if "/" in url else url)
        host = re.sub(r"\.(com|org|io|co|net|dev).*$", "", host, flags=re.IGNORECASE)
        return host.replace("-", " ").replace("_", " ").title().strip()
