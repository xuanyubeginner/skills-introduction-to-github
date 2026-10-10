"""Keyword extraction for JDs and CVs.

Deliberately dependency-free: a curated skill lexicon (EN + DE + FR synonyms,
since postings in DE/LU are often German or French) plus the skills listed in
the user's own profile. Each canonical skill maps to the surface forms that
count as a hit, so "Datenanalyse" in a German JD matches "Data Analysis" on
an English CV.
"""
from __future__ import annotations

import html
import re
from pathlib import Path

LEXICON_FILE = Path(__file__).with_name("skills_lexicon.txt")


def clean_html(text: str) -> str:
    text = re.sub(r"<(br|/p|/li|/div|/h\d)[^>]*>", "\n", text or "", flags=re.I)
    text = re.sub(r"<li[^>]*>", "\n- ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def normalize(text: str) -> str:
    text = text.lower()
    text = text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    text = re.sub(r"[‐-‒–—/|•·,;:()\[\]{}\"'!?]", " ", text)
    return re.sub(r"\s+", " ", text)


def load_lexicon(extra: dict[str, list[str]] | None = None) -> dict[str, list[str]]:
    """Return {canonical: [surface forms...]}. Lines: `Canonical = alias1, alias2`."""
    lex: dict[str, list[str]] = {}
    for line in LEXICON_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        canon, _, aliases = line.partition("=")
        canon = canon.strip()
        forms = [canon] + [a.strip() for a in aliases.split(",") if a.strip()]
        lex[canon] = forms
    known = {normalize(f).strip(): c for c, fs in lex.items() for f in fs}
    for canon, forms in (extra or {}).items():
        if normalize(canon).strip() in known:  # e.g. "Cash management" is already "Cash Management"
            continue
        lex.setdefault(canon, [canon])
        lex[canon] = list(dict.fromkeys(lex[canon] + list(forms)))
    return lex


def _pattern(form: str) -> re.Pattern:
    f = re.escape(normalize(form).strip())
    # word boundaries that also work for tokens like "c++", "c#", ".net"
    return re.compile(rf"(?<![a-z0-9+#]){f}(?![a-z0-9+#])")


_cache: dict[str, re.Pattern] = {}


def find_skills(text: str, lexicon: dict[str, list[str]]) -> dict[str, int]:
    """Return {canonical skill: number of mentions} found in text."""
    norm = " " + normalize(text) + " "
    hits: dict[str, int] = {}
    for canon, forms in lexicon.items():
        n = 0
        for form in forms:
            pat = _cache.get(form)
            if pat is None:
                pat = _cache[form] = _pattern(form)
            n += len(pat.findall(norm))
        if n:
            hits[canon] = n
    return hits


# --- requirements that are not "skills" but decide whether applying makes sense

GERMAN_REQUIRED = re.compile(
    r"(fliessend\w* deutsch|verhandlungssicher\w* deutsch|deutsch\w* (auf )?(c1|c2|muttersprach)|"
    r"sehr gute\w* deutschkenntnisse|fluent (in )?german|german \(?(c1|c2|fluent|native)|"
    r"business[- ]fluent german|excellent german)"
)
FRENCH_REQUIRED = re.compile(
    r"(francais courant|maitrise du francais|fluent (in )?french|french \(?(c1|c2|fluent|native)|"
    r"excellent french|franzoesisch\w* (fliessend|verhandlungssicher))"
)
SENIOR = re.compile(r"\b(senior|lead|principal|head of|teamleiter|leiter|director|manager)\b")
INTERNSHIP = re.compile(
    r"\b(intern|internship|praktikum|praktikant\w*|pflichtpraktikum|stage|stagiaire|trainee)\b"
)
WORKING_STUDENT = re.compile(r"\b(werkstudent\w*|working student|studentische\w* (hilfskraft|mitarbeit))\b")
THESIS = re.compile(r"\b(abschlussarbeit|masterarbeit|bachelorarbeit|thesis)\b")
FULL_TIME = re.compile(r"\b(full[- ]time|vollzeit|cdi|festanstellung|unbefristet|graduate|junior|berufseinsteiger)\b")
YEARS_EXP = re.compile(r"(\d+)\s*\+?\s*(?:years|jahre|ans)\b")


def classify_job_type(title: str, description: str = "") -> str:
    t = normalize(title)
    if WORKING_STUDENT.search(t):
        return "working_student"
    if INTERNSHIP.search(t):
        return "internship"
    if THESIS.search(t):
        return "thesis"
    d = normalize(description)
    if WORKING_STUDENT.search(d[:600]):
        return "working_student"
    if INTERNSHIP.search(d[:600]):
        return "internship"
    if FULL_TIME.search(t) or FULL_TIME.search(d):
        return "full_time"
    return "unknown"


def required_years(description: str) -> int | None:
    vals = [int(m.group(1)) for m in YEARS_EXP.finditer(normalize(description)) if int(m.group(1)) < 20]
    return max(vals) if vals else None
