"""Shared data structures."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field


@dataclass
class Job:
    source: str
    title: str
    company: str = ""
    location: str = ""
    country: str = ""
    url: str = ""
    description: str = ""
    posted: str = ""          # ISO date if known
    job_type: str = ""        # internship / working_student / full_time / unknown
    external_id: str = ""
    # filled in by the matcher
    score: float = 0.0
    matched: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    @property
    def uid(self) -> str:
        """Stable id used to dedupe the same posting across sources."""
        if self.url:
            key = self.url.split("?")[0].rstrip("/").lower()
        else:
            key = f"{self.title}|{self.company}|{self.location}".lower()
        return hashlib.sha1(key.encode()).hexdigest()[:10]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["uid"] = self.uid
        return d
