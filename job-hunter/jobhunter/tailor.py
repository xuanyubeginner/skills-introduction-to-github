"""Tailor the CV to a JD: select / reorder true content so the most relevant comes first.

Nothing is invented. The tailoring report lists JD keywords you don't show yet;
add them to profile.yaml only if they are genuinely true for you.
"""
from __future__ import annotations

import copy

from . import keywords as kw
from .matcher import Profile
from .models import Job


def jd_weights(job: Job, profile: Profile) -> dict[str, int]:
    found = kw.find_skills(f"{job.title}\n{job.title}\n{job.description}", profile.lexicon)
    return {s: min(n, 4) for s, n in found.items()}


def _relevance(text: str, weights: dict[str, int], lexicon) -> int:
    return sum(weights.get(s, 0) for s in kw.find_skills(text, lexicon))


def tailor(profile: Profile, job: Job, max_bullets: int = 5, max_projects: int = 3) -> tuple[dict, dict]:
    """Return (tailored CV data for the template, report dict)."""
    w = jd_weights(job, profile)
    lex = profile.lexicon
    cv = copy.deepcopy(profile.data)

    # 1. skills: inside each group JD skills first; groups with more hits first
    groups = []
    for name, items in (cv.get("skills") or {}).items():
        ranked = sorted(items, key=lambda s: -_relevance(s, w, lex))  # sorted() is stable
        groups.append((name, ranked, sum(_relevance(s, w, lex) for s in items)))
    groups.sort(key=lambda g: -g[2])
    cv["skills"] = {name: items for name, items, _ in groups}

    # 2. experience: keep chronology, reorder bullets inside each role by relevance
    for exp in cv.get("experience", []):
        bullets = exp.get("bullets", [])
        exp["bullets"] = sorted(bullets, key=lambda b: -_relevance(b, w, lex))[:max_bullets]

    # 3. projects: most relevant first, keep the top N
    projects = cv.get("projects", [])
    projects.sort(key=lambda p: -_relevance(" ".join([p.get("name", "")] + p.get("tech", []) + p.get("bullets", [])), w, lex))
    cv["projects"] = projects[:max_projects]

    matched = sorted((s for s in w if s in profile.skills), key=lambda s: -w[s])
    missing = sorted((s for s in w if s not in profile.skills), key=lambda s: -w[s])
    report = {
        "job": job.to_dict(),
        "jd_keywords": sorted(w, key=lambda s: -w[s]),
        "matched": matched,
        "missing": missing,
        "coverage": round(100 * sum(w[s] for s in matched) / sum(w.values()), 1) if w else 0.0,
    }
    return cv, report
