"""Bundesagentur für Arbeit — Jobsuche API (official, free, public key).

Docs: https://jobsuche.api.bund.dev/  (community docs of the official API)
Germany's largest job database; many StepStone/Indeed postings are mirrored here.
"""
from __future__ import annotations

import base64

from ..keywords import clean_html
from ..models import Job
from . import get, log

BASE = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service"
API_KEY = {"X-API-Key": "jobboerse-jobsuche"}  # public client id published by the BA
ANGEBOTSART = {"full_time": 1, "internship": 34}  # 1 = Arbeit, 34 = Praktikum/Trainee


def parse_list(payload: dict) -> list[Job]:
    jobs = []
    for s in payload.get("stellenangebote", []) or []:
        ort = s.get("arbeitsort") or {}
        refnr = s.get("refnr", "")
        jobs.append(Job(
            source="arbeitsagentur",
            title=s.get("titel") or s.get("beruf", ""),
            company=s.get("arbeitgeber", ""),
            location=", ".join(x for x in [ort.get("ort"), ort.get("region")] if x),
            country=(ort.get("land") or "Deutschland"),
            url=s.get("externeUrl") or f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}",
            posted=s.get("aktuelleVeroeffentlichungsdatum", ""),
            external_id=refnr,
            description=s.get("beruf", ""),
        ))
    return jobs


def fetch_description(refnr: str) -> str:
    enc = base64.b64encode(refnr.encode()).decode()
    for path in (f"/pc/v4/jobdetails/{enc}", f"/pc/v2/jobdetails/{enc}"):
        try:
            data = get(BASE + path, headers=API_KEY).json()
            return clean_html(data.get("stellenangebotsBeschreibung") or data.get("stellenbeschreibung") or "")
        except Exception as exc:  # detail endpoint changes occasionally; list data is still useful
            log.debug("BA detail %s failed: %s", path, exc)
    return ""


def search(keyword: str, location: dict, cfg: dict) -> list[Job]:
    if location.get("country", "de") != "de":
        return []
    params = {
        "was": keyword,
        "wo": location["name"],
        "umkreis": location.get("radius_km", 25),
        "size": min(cfg.get("results_per_query", 50), 100),
        "page": 1,
        "veroeffentlichtseit": cfg.get("max_age_days", 21),
    }
    data = get(BASE + "/pc/v4/jobs", params=params, headers=API_KEY).json()
    jobs = parse_list(data)
    for j in jobs[: cfg.get("detail_limit", 25)]:
        desc = fetch_description(j.external_id)
        if desc:
            j.description = desc
    return jobs
