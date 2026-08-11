from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
import hashlib


class Job(BaseModel):
    id: str = ""                      # fingerprint MD5
    title: str
    company: str
    location: str = "Remote"
    description: str = ""
    url: str = ""
    source: str = ""
    posted_date: Optional[str] = None
    discovered_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    tech_stack: str = ""
    experience_level: str = "mid"
    relevance_score: int = 0
    status: str = "new"              # new/reviewed/applied/stale
    company_domain: str = ""
    salary: str = ""
    job_type: str = "full-time"
    india_friendly: str = "unknown"
    location_note: str = ""
    resume_id: Optional[str] = None   # which resume to use for this job

    def make_fingerprint(self) -> str:
        raw = f"{self.company.lower().strip()}|{self.title.lower().strip()}|{self.location.lower().strip()}"
        return hashlib.md5(raw.encode()).hexdigest()

    def extract_domain(self) -> str:
        if not self.url:
            return ""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(self.url)
            domain = parsed.netloc.replace("www.", "")
            skip = ["remotive.com", "remoteok.com", "arbeitnow.com",
                    "linkedin.com", "indeed.com", "glassdoor.com",
                    "jsearch.io", "rapidapi.com"]
            if any(s in domain for s in skip):
                return ""
            return domain
        except Exception:
            return ""


class Profile(BaseModel):
    id: Optional[int] = None
    name: str
    description: str = ""
    is_active: bool = False
    config: dict = Field(default_factory=dict)  # full YAML blob as dict
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class Resume(BaseModel):
    id: Optional[int] = None
    profile_id: int
    role_name: str                    # e.g. "blockchain-dev", "pm-ai"
    file_path: str                    # relative path under RESUME_DIR
    original_filename: str
    file_size: int = 0
    uploaded_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class Outreach(BaseModel):
    id: Optional[int] = None
    job_id: str
    job_title: str
    company: str
    company_domain: str = ""
    contact_name: str = "[Search LinkedIn]"
    contact_position: str = ""
    contact_linkedin: str = ""
    dm_short: str = ""
    dm_long: str = ""
    status: str = "pending"          # pending/messaged/replied/followed_up
    notes: str = "[]"                 # JSON array of LinkedIn search URLs
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    messaged_at: str = ""
    replied_at: str = ""
    followed_up_at: str = ""
    emailed_at: str = ""
    profile_id: int = 0


class Company(BaseModel):
    id: Optional[int] = None
    name: str
    domain: str = ""
    careers_url: str = ""
    ats_platform: str = "unknown"    # greenhouse/lever/ashby/html/unknown
    ats_slug: str = ""
    founded_year: int = 0
    employee_count: str = ""
    tags: str = ""
    india_friendly: str = "unknown"
    last_crawled: str = ""
    crawl_status: str = "active"     # active/paused/failed/firecrawl_pending
    notes: str = ""

    def make_id(self) -> str:
        import re
        return re.sub(r'[^a-z0-9]+', '-', self.name.lower()).strip('-')


class APIUsage(BaseModel):
    id: Optional[int] = None
    source: str = "jsearch"          # jsearch/firecrawl/other
    date: str                         # YYYY-MM-DD
    daily_count: int = 0
    monthly_count: int = 0
