"""ATS check of the generated PDF: what a parser actually extracts, not what you see."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from . import keywords as kw

SECTIONS = ["summary", "skills", "experience", "education"]


def extract_text(pdf: Path) -> tuple[str, int]:
    if shutil.which("pdftotext"):
        text = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True).stdout
        pages = text.count("\f") or 1
        return text, pages
    from pypdf import PdfReader
    reader = PdfReader(str(pdf))
    return "\n".join(p.extract_text() or "" for p in reader.pages), len(reader.pages)


def check(pdf: Path, cv: dict, jd_keywords: list[str], lexicon) -> dict:
    text, pages = extract_text(pdf)
    norm = kw.normalize(text)
    found = kw.find_skills(text, lexicon)
    present = [k for k in jd_keywords if k in found]
    absent = [k for k in jd_keywords if k not in found]
    contact = cv.get("contact", {})
    checks = {
        "Text is extractable": len(text.strip()) > 200,
        "Name found": kw.normalize(cv.get("name", "")) in norm,
        "Email found": bool(contact.get("email")) and contact["email"].lower() in text.lower(),
        "Phone found": bool(contact.get("phone")) and re.sub(r"\D", "", contact["phone"])[-6:] in re.sub(r"\D", "", text),
        "Standard section headings": all(s in norm for s in SECTIONS),
        "Length <= 2 pages": pages <= 2,
        "No broken ligatures": not re.search("[ﬀ-ﬆ]", text),
    }
    coverage = round(100 * len(present) / len(jd_keywords), 1) if jd_keywords else 100.0
    return {"checks": checks, "pages": pages, "coverage": coverage,
            "present": present, "absent": absent, "chars": len(text)}


def report_markdown(job: dict, tailor_report: dict, ats: dict | None, llm_note: str = "") -> str:
    lines = [f"# ATS report — {job['title']} @ {job['company'] or '?'}", "",
             f"- URL: {job['url'] or '-'}",
             f"- Match score (search): {job.get('score', 0)} / 100",
             f"- JD keyword coverage by your profile: {tailor_report['coverage']}%", ""]
    if job.get("flags"):
        lines += ["**Flags:** " + "; ".join(job["flags"]), ""]
    lines += ["## JD keywords you already show (now prioritised in the CV)",
              ", ".join(tailor_report["matched"]) or "-", "",
              "## JD keywords missing from your profile",
              ", ".join(tailor_report["missing"]) or "-", "",
              "> Only add a missing keyword to `profile.yaml` if it is genuinely true "
              "(course, project, work task). If true, use the JD's exact wording — ATS match literally.", ""]
    if ats:
        lines += ["## Parsed-PDF checks (what an ATS sees)", ""]
        lines += [f"- [{'x' if ok else ' '}] {name}" for name, ok in ats["checks"].items()]
        lines += ["", f"Keyword coverage in extracted PDF text: **{ats['coverage']}%** ({ats['pages']} page(s))"]
        if ats["absent"]:
            lines += [f"Not found in PDF text: {', '.join(ats['absent'])}"]
        lines.append("")
    if llm_note:
        lines += ["## AI rewrite", llm_note, ""]
    lines += ["## Manual checklist", "- [ ] Job title of the posting appears in summary/headline (if honest)",
              "- [ ] Cover letter / Anschreiben tailored (German postings often expect one)",
              "- [ ] File name: `Firstname_Lastname_CV_<Company>.pdf`",
              "- [ ] Work permit / availability date stated if you are non-EU or a student"]
    return "\n".join(lines) + "\n"
