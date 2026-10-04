"""Arbeitnow job board API (free, no key). Mostly Germany, many English-speaking roles.
Docs: https://www.arbeitnow.com/blog/job-board-api
The API has no search parameters, so we page through recent jobs and filter locally.
"""
from __future__ import annotations

from ..keywords import clean_html, normalize
from ..models import Job
from . import get

URL = "https://www.arbeitnow.com/api/job-board-api"
_cache: list[dict] | None = None


def parse(payload: dict) -> list[Job]:
    jobs = []
    for d in payload.get("data", []):
        types = d.get("job_types") or []
        jobs.append(Job(
            source="arbeitnow",
            title=d.get("title", ""),
            company=d.get("company_name", ""),
            location=d.get("location", "") + (" (remote)" if d.get("remote") else ""),
            country="de",
            url=d.get("url", ""),
            description=clean_html(d.get("description", "")) + "\nTags: " + ", ".join(d.get("tags") or []),
            posted=str(d.get("created_at", "")),
            job_type="internship" if any("intern" in t.lower() for t in types) else "",
            external_id=d.get("slug", ""),
        ))
    return jobs


def _all(pages: int = 5) -> list[dict]:
    global _cache
    if _cache is None:
        _cache = []
        for page in range(1, pages + 1):
            data = get(URL, params={"page": page}).json()
            _cache += data.get("data", [])
            if not data.get("links", {}).get("next"):
                break
    return _cache


def search(keyword: str, location: dict, cfg: dict) -> list[Job]:
    if location.get("country", "de") != "de":
        return []
    words = normalize(keyword).split()
    loc = normalize(location["name"])
    out = []
    for job in parse({"data": _all()}):
        hay = normalize(job.title + " " + job.description[:1500])
        loc_ok = loc in normalize(job.location) or "remote" in job.location.lower()
        if loc_ok and all(w in hay for w in words):
            out.append(job)
    return out
