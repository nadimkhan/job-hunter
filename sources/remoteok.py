"""RemoteOK — fully free, no API key needed.
Tag-filtered to blockchain/web3 roles only.
"""
import httpx
from sources.base import BaseSource
from core.models import Job

# Tags that indicate blockchain/web3 roles
BLOCKCHAIN_TAGS = {
    "blockchain", "web3", "solidity", "ethereum", "defi", "nft",
    "smart-contract", "web3.js", "ethers.js", "rust", "crypto",
    "bitcoin", "cryptocurrency", "dao", "token", "layer-2",
    "ipfs", "chainlink", "polygon", "avalanche", "solana",
    "dapp", "DeFi", "NFT", "Web3", "Blockchain",
}


class RemoteOKSource(BaseSource):
    name = "remoteok"
    BASE_URL = "https://remoteok.com/api"

    async def fetch(self) -> list[Job]:
        jobs = []
        headers = {"User-Agent": "JobHunter/1.0 (contact@nadim.dev)"}
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.get(self.BASE_URL, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                self.log(f"HTTP error: {e}")
                return []

        for item in data[1:]:
            if not isinstance(item, dict):
                continue

            tags = item.get("tags", [])
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",")]
            tags_lower = [t.lower().strip() for t in tags]
            tags_str = ", ".join(tags) if tags else ""

            # Skip jobs without blockchain/web3 tags
            if not any(tag in BLOCKCHAIN_TAGS for tag in tags_lower):
                continue

            job = Job(
                title=item.get("position", ""),
                company=item.get("company", ""),
                location=item.get("location", "Remote"),
                description=item.get("description", ""),
                url=item.get("url", f"https://remoteok.com/l/{item.get('id', '')}"),
                source=self.name,
                posted_date=item.get("date", ""),
                job_type="full-time",
                tech_stack=tags_str,
            )
            job.id = job.make_fingerprint()
            jobs.append(job)

        self.log(f"Fetched {len(jobs)} blockchain-tagged jobs")
        return jobs
