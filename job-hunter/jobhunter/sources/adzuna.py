"""Adzuna API (free key: https://developer.adzuna.com). Aggregates StepStone, company sites, etc.
Supported EU countries include de, at, be, fr, nl, it, es, pl (not Luxembourg).
"""
from __future__ import annotations

import os

from ..keywords import clean_html
from ..models import Job
from . import get

COUNTRIES = {"de", "at", "be", "fr", "nl", "it", "es", "pl", "ch", "gb"}


def parse(payload: dict, country: str) -> list[Job]:
    jobs = []
    for r in payload.get("results", []):
        jobs.append(Job(
            source="adzuna",
            title=clean_html(r.get("title", "")),
            company=(r.get("company") or {}).get("display_name", ""),
            location=(r.get("location") or {}).get("display_name", ""),
            country=country,
            url=r.get("redirect_url", ""),
            description=clean_html(r.get("description", "")),  # Adzuna only returns a snippet
            posted=r.get("created", "")[:10],
            job_type="full_time" if r.get("contract_time") == "full_time" else "",
            external_id=str(r.get("id", "")),
        ))
    return jobs


def search(keyword: str, location: dict, cfg: dict) -> list[Job]:
    country = location.get("country", "de")
    src = cfg.get("_source", {})
    app_id = src.get("app_id") or os.getenv("ADZUNA_APP_ID")
    app_key = src.get("app_key") or os.getenv("ADZUNA_APP_KEY")
    if country not in COUNTRIES or not (app_id and app_key):
        return []
    params = {
        "app_id": app_id, "app_key": app_key, "what": keyword, "where": location["name"],
        "distance": location.get("radius_km", 25), "max_days_old": cfg.get("max_age_days", 21),
        "results_per_page": min(cfg.get("results_per_query", 50), 50), "content-type": "application/json",
    }
    data = get(f"https://api.adzuna.com/v1/api/jobs/{country}/search/1", params=params).json()
    return parse(data, country)
