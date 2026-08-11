from abc import ABC, abstractmethod
from core.models import Job


class BaseSource(ABC):
    name: str = "unknown"

    @abstractmethod
    async def fetch(self) -> list[Job]:
        pass

    def log(self, msg: str):
        print(f"  [{self.name.upper()}] {msg}", flush=True)
