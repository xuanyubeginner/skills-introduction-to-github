"""Explainable CV <-> JD match scoring (0-100)."""
from __future__ import annotations

from . import keywords as kw
from .models import Job

LEVELS = {"a1": 1, "a2": 2, "b1": 3, "b2": 4, "c1": 5, "c2": 6, "native": 7, "muttersprache": 7, "fluent": 5}


class Profile:
    """Thin wrapper around profile.yaml with helpers used across the tool."""

    def __init__(self, data: dict):
        self.data = data
        # very short items like "R" would match noise ("R&D"); those rely on lexicon aliases instead
        extra = {s: [s] for group in (data.get("skills") or {}).values() for s in group
                 if len(kw.normalize(str(s)).strip()) > 2}
        self.lexicon = kw.load_lexicon(extra)
        self.skills = set(kw.find_skills(self.full_text(), self.lexicon))

    def full_text(self) -> str:
        d = self.data
        parts = [d.get("headline", ""), d.get("summary", "")]
        for group in (d.get("skills") or {}).values():
            parts += group
        parts += [lang["name"] for lang in d.get("languages", [])]
        for e in d.get("experience", []):
            parts += [e.get("title", "")] + e.get("bullets", [])
        for p in d.get("projects", []):
            parts += [p.get("name", "")] + p.get("tech", []) + p.get("bullets", [])
        for ed in d.get("education", []):
            parts += [ed.get("degree", ""), ed.get("details", "")] + ed.get("bullets", [])
        parts += d.get("certifications", [])
        return "\n".join(str(p) for p in parts if p)

    def language_level(self, name: str) -> int:
        for lang in self.data.get("languages", []):
            if lang["name"].lower() == name.lower():
                return LEVELS.get(str(lang.get("level", "")).lower(), 0)
        return 0

    @property
    def target_roles(self) -> list[str]:
        return (self.data.get("target") or {}).get("roles", [])

    @property
    def target_types(self) -> list[str]:
        return (self.data.get("target") or {}).get("job_types", [])


def _title_similarity(title: str, roles: list[str]) -> float:
    t = set(kw.normalize(title).split())
    best = 0.0
    for role in roles:
        r = set(kw.normalize(role).split())
        if r:
            best = max(best, len(t & r) / len(r))
    return best


def score_job(job: Job, profile: Profile) -> Job:
    text = f"{job.title}\n{job.description}"
    jd_skills = kw.find_skills(text, profile.lexicon)
    # skills named in the title are clearly central -> weight them up
    title_skills = kw.find_skills(job.title, profile.lexicon)
    weights = {s: min(n, 3) + (3 if s in title_skills else 0) for s, n in jd_skills.items()}
    total = sum(weights.values())
    matched = sorted((s for s in weights if s in profile.skills), key=lambda s: -weights[s])
    missing = sorted((s for s in weights if s not in profile.skills), key=lambda s: -weights[s])
    skill_cov = sum(weights[s] for s in matched) / total if total else 0.0

    title_sim = _title_similarity(job.title, profile.target_roles)
    if not job.job_type:
        job.job_type = kw.classify_job_type(job.title, job.description)
    if job.job_type in profile.target_types:
        type_fit = 1.0
    elif job.job_type == "unknown":
        type_fit = 0.5
    else:
        type_fit = 0.0

    score = 55 * skill_cov + 30 * title_sim + 15 * type_fit
    flags: list[str] = []
    norm = kw.normalize(text)
    if kw.GERMAN_REQUIRED.search(norm) and profile.language_level("German") < 5:
        score -= 25  # usually a hard requirement in DE postings
        flags.append("German C1+ required")
    if kw.FRENCH_REQUIRED.search(norm) and profile.language_level("French") < 5:
        score -= 25
        flags.append("French C1+ required")
    if kw.SENIOR.search(kw.normalize(job.title)):  # tool targets students / early-career
        score -= 20
        flags.append("senior role")
    years = kw.required_years(job.description)
    if years and years >= 3:
        score -= 5 * min(years - 2, 3)
        flags.append(f"{years}+ yrs experience")
    if total == 0:
        flags.append("no skills detected (short description?)")
    if job.job_type not in profile.target_types and job.job_type != "unknown":
        flags.append(f"type: {job.job_type}")

    job.score = round(max(0.0, min(100.0, score)), 1)
    job.matched, job.missing, job.flags = matched, missing, flags
    return job
