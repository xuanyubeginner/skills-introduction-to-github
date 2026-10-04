"""Import a single posting from any URL (StepStone, Moovijob, jobs.lu, LinkedIn, company sites...).

Most job sites embed schema.org `JobPosting` JSON-LD because Google for Jobs
requires it, so this works on far more sites than a per-site scraper would.
If the page blocks bots or has no JSON-LD, save the JD text to a file and use
`jobhunter add --text-file jd.txt` instead.
"""
from __future__ import annotations

import json
import re

from ..keywords import clean_html
from ..models import Job
from . import get

LD_RE = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)


def _walk(node):
    if isinstance(node, list):
        for n in node:
            yield from _walk(n)
    elif isinstance(node, dict):
        yield node
        for key in ("@graph", "itemListElement", "item"):
            if key in node:
                yield from _walk(node[key])


def _place(loc) -> tuple[str, str]:
    if isinstance(loc, list):
        loc = loc[0] if loc else {}
    addr = (loc or {}).get("address", {}) if isinstance(loc, dict) else {}
    if isinstance(addr, str):
        return addr, ""
    country = addr.get("addressCountry", "")
    if isinstance(country, dict):
        country = country.get("name", "")
    city = addr.get("addressLocality", "") or addr.get("addressRegion", "")
    return city, str(country)


def parse_jobposting(html: str, url: str) -> Job | None:
    for raw in LD_RE.findall(html):
        try:
            data = json.loads(raw.strip())
        except json.JSONDecodeError:
            continue
        for node in _walk(data):
            t = node.get("@type")
            if t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t):
                org = node.get("hiringOrganization") or {}
                city, country = _place(node.get("jobLocation"))
                etype = node.get("employmentType") or ""
                etype = " ".join(etype) if isinstance(etype, list) else str(etype)
                job_type = {"INTERN": "internship", "FULL_TIME": "full_time"}.get(etype.upper().split(" ")[0], "")
                return Job(
                    source="url",
                    title=clean_html(node.get("title", "")),
                    company=org.get("name", "") if isinstance(org, dict) else str(org),
                    location=city,
                    country=country,
                    url=url,
                    description=clean_html(node.get("description", "")),
                    posted=str(node.get("datePosted", ""))[:10],
                    job_type=job_type,
                )
    return None


def fallback_text(html: str, url: str) -> Job:
    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    body = re.sub(r"<(script|style|nav|header|footer)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    return Job(source="url", title=clean_html(title.group(1)) if title else url, url=url,
               description=clean_html(body)[:15000])


def import_url(url: str) -> Job:
    html = get(url).text
    return parse_jobposting(html, url) or fallback_text(html, url)
