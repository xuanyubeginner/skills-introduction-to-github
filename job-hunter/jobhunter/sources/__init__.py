"""Job sources. Each source exposes `search(keyword, location, cfg) -> list[Job]`.

Only official / public APIs are queried automatically. Sites without an API
(LinkedIn, StepStone, Moovijob, jobs.lu) are covered by
  * `jobspy` (optional, unofficial scraper for LinkedIn / Indeed / Google Jobs), and
  * `import_url` — paste any posting URL; most job sites embed schema.org
    JobPosting JSON-LD (it is what Google Jobs indexes), which we parse.
"""
from __future__ import annotations

import logging

import requests

log = logging.getLogger("jobhunter")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36 jobhunter/1.0 (personal job search)",
    "Accept-Language": "en,de;q=0.8,fr;q=0.6",
}


def get(url: str, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", 25)
    headers = {**HEADERS, **kwargs.pop("headers", {})}
    resp = requests.get(url, headers=headers, **kwargs)
    resp.raise_for_status()
    return resp
