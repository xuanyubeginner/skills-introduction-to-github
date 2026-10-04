"""Optional AI rewrite with Claude: rephrase summary and bullets toward the JD wording.

Guardrails: the model may only rephrase; every rewritten bullet is checked and any
bullet that introduces a skill not evidenced in your profile is rejected and the
original is kept.
"""
from __future__ import annotations

import json

from . import keywords as kw
from .matcher import Profile
from .models import Job

SYSTEM = """You are an expert CV writer for the German, Luxembourgish and EU job market and an ATS specialist.
You rewrite CV content so it matches a job description, under strict honesty rules:
- Never invent experience, employers, tools, numbers, degrees or responsibilities.
- Only rephrase what is given. You may use the job description's terminology for things the candidate demonstrably did
  (e.g. "dashboards" -> "data visualization"), and you may reorder clauses to lead with impact.
- Keep every number/metric exactly as given. Start bullets with a strong past-tense action verb. Max ~25 words per bullet.
- Write in the CV's language (English) unless asked otherwise.
- The summary: 2-3 sentences, mention the target role title from the posting if it fits the candidate, and the most relevant true strengths."""

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "experience": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "bullets": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["index", "bullets"],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["summary", "experience", "notes"],
    "additionalProperties": False,
}


def rewrite(cv: dict, profile: Profile, job: Job, model: str = "claude-opus-5-5", effort: str = "medium") -> tuple[dict, str]:
    import anthropic  # imported lazily so the tool works without the SDK

    payload = {
        "summary": cv.get("summary", ""),
        "skills": cv.get("skills", {}),
        "experience": [{"index": i, "title": e["title"], "company": e["company"], "bullets": e["bullets"]}
                       for i, e in enumerate(cv.get("experience", []))],
    }
    prompt = (f"<job_posting>\nTitle: {job.title}\nCompany: {job.company}\n\n{job.description[:12000]}\n</job_posting>\n\n"
              f"<cv>\n{json.dumps(payload, ensure_ascii=False, indent=1)}\n</cv>\n\n"
              "Rewrite the summary and each experience's bullets (same number of bullets, same order, same index). "
              "In `notes`, list in one or two sentences which JD requirements the candidate cannot honestly claim.")

    client = anthropic.Anthropic()
    resp = client.beta.messages.create(
        model=model,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=SYSTEM,
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    )
    if resp.stop_reason in ("refusal", "max_tokens"):
        return cv, f"AI rewrite skipped (stop_reason={resp.stop_reason}); deterministic version kept."
    data = json.loads(next(b.text for b in resp.content if b.type == "text"))

    allowed = profile.skills
    rejected = 0

    def safe(new: str, original: str) -> str:
        nonlocal rejected
        orig_skills = set(kw.find_skills(original, profile.lexicon))
        introduced = set(kw.find_skills(new, profile.lexicon)) - orig_skills - allowed
        if introduced:
            rejected += 1
            return original
        return new

    out = dict(cv)
    out["summary"] = safe(data["summary"], cv.get("summary", "") + " " + profile.full_text())
    exps = [dict(e) for e in cv.get("experience", [])]
    for item in data["experience"]:
        i = item["index"]
        if 0 <= i < len(exps) and len(item["bullets"]) == len(exps[i]["bullets"]):
            exps[i]["bullets"] = [safe(n, o) for n, o in zip(item["bullets"], exps[i]["bullets"])]
    out["experience"] = exps
    note = data.get("notes", "")
    if rejected:
        note += f"\n\n{rejected} rewritten line(s) introduced skills not in your profile and were reverted to the original."
    return out, note + "\n\n**Review every rewritten line before sending.**"
