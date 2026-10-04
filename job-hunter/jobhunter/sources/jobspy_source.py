"""Optional: LinkedIn / Indeed / Google Jobs via JobSpy (https://github.com/speedyapply/JobSpy).

Unofficial scraping — sites may block it and LinkedIn's terms forbid automated access.
Keep volumes low and use it for your own search only. Install: pip install python-jobspy
"""
from __future__ import annotations

from ..models import Job
from . import log

INDEED_COUNTRY = {"de": "germany", "lu": "luxembourg", "fr": "france", "be": "belgium",
                  "nl": "netherlands", "at": "austria", "ch": "switzerland"}
COUNTRY_NAME = {"de": "Germany", "lu": "Luxembourg", "fr": "France", "be": "Belgium",
                "nl": "Netherlands", "at": "Austria", "ch": "Switzerland"}


def search(keyword: str, location: dict, cfg: dict) -> list[Job]:
    try:
        from jobspy import scrape_jobs
    except ImportError:
        log.warning("jobspy enabled but not installed: pip install python-jobspy")
        return []
    src = cfg.get("_source", {})
    country = location.get("country", "de")
    where = f"{location['name']}, {COUNTRY_NAME.get(country, '')}".strip(", ")
    df = scrape_jobs(
        site_name=src.get("sites", ["linkedin", "indeed", "google"]),
        search_term=keyword,
        google_search_term=f"{keyword} jobs near {where} since last week",
        location=where,
        distance=location.get("radius_km", 25),
        results_wanted=min(cfg.get("results_per_query", 50), 50),
        hours_old=24 * cfg.get("max_age_days", 21),
        country_indeed=INDEED_COUNTRY.get(country, "germany"),
        linkedin_fetch_description=src.get("linkedin_fetch_description", True),
    )
    jobs = []
    for r in df.fillna("").to_dict("records"):
        jobs.append(Job(
            source=f"jobspy:{r.get('site', '')}",
            title=str(r.get("title", "")),
            company=str(r.get("company", "")),
            location=str(r.get("location", "")),
            country=country,
            url=str(r.get("job_url", "")),
            description=str(r.get("description", "")),
            posted=str(r.get("date_posted", "")),
            external_id=str(r.get("id", "")),
        ))
    return jobs
