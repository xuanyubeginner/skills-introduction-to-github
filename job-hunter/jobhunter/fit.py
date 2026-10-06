"""Fit the CV to an exact page count.

One knob t in [0, 1] scales font size, line spacing, vertical gaps and margins
together (0 = tightest, 1 = most spacious). We look for the largest t that still
fits the target page count, so the result is neither longer than N pages nor
leaves the last page half empty. If even t = 0 is too long, the least relevant
bullets (tailoring already sorted them last) are dropped one at a time.
"""
from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader

from . import latex

FILL_RE = re.compile(r"JOBHUNTER-FILL ([\d.]+)pt ([\d.]+)pt")
MIN_BULLETS_PER_ROLE = 2


def params(t: float) -> dict:
    fs = 8.8 + 1.7 * t                      # body font 8.8pt .. 10.5pt
    ms = fs * 0.89
    m = 0.75 + 0.5 * t                      # margin scale
    return {
        "fs": round(fs, 2), "bs": round(fs * 1.22, 2),
        "ms": round(ms, 2), "mbs": round(ms * 1.2, 2),
        "sp": round(0.35 + 1.65 * t, 3),    # vertical gaps x0.35 .. x2
        "ml": round(1.4 * m, 2), "mr": round(1.2 * m, 2), "mv": round(1.0 * m, 2),
    }


def supports_fit(template_path: Path) -> bool:
    return "fit" in template_path.read_text(encoding="utf-8")


def _measure(tex: Path) -> tuple[int, float | None]:
    pdf = latex.compile_pdf(tex, clean=False)
    pages = len(PdfReader(str(pdf)).pages)
    log = tex.with_suffix(".log")
    fill = None
    if log.exists():
        m = FILL_RE.findall(log.read_text(encoding="utf-8", errors="ignore"))
        if m and float(m[-1][1]) > 0:
            fill = float(m[-1][0]) / float(m[-1][1])
    return pages, fill


def _drop_one(cv: dict) -> str | None:
    """Remove the least relevant bullet from the role with the most bullets."""
    roles = [e for e in cv.get("experience", []) if len(e.get("bullets", [])) > MIN_BULLETS_PER_ROLE]
    if roles:
        role = max(roles, key=lambda e: len(e["bullets"]))
        return f"{role['title']}: {role['bullets'].pop()}"
    if cv.get("projects"):
        return f"project: {cv['projects'].pop()['name']}"
    return None


def fit_to_pages(template: Path, cv: dict, keywords: list[str], tex: Path, pages: int = 1,
                 steps: int = 6) -> tuple[Path, dict]:
    """Render + compile so the PDF has exactly `pages` pages (as full as possible)."""
    def build(t: float) -> tuple[int, float | None]:
        tex.write_text(latex.render(template, cv, keywords, fit=params(t)), encoding="utf-8")
        return _measure(tex)

    dropped: list[str] = []
    n, fill = build(1.0)
    best = 1.0
    if n > pages:
        n, fill = build(0.0)
        while n > pages:
            gone = _drop_one(cv)
            if gone is None:
                break
            dropped.append(gone)
            n, fill = build(0.0)
        best = 0.0
        if n <= pages:  # binary search the largest t that still fits
            lo, hi = 0.0, 1.0
            for _ in range(steps):
                mid = (lo + hi) / 2
                if build(mid)[0] <= pages:
                    lo = mid
                else:
                    hi = mid
            best = lo
            n, fill = build(best)
    pdf = latex.compile_pdf(tex)  # final build + cleanup
    info = {"t": round(best, 3), "pages": n, "target": pages, "fill": fill, "dropped": dropped,
            "font_pt": params(best)["fs"]}
    return pdf, info


def describe(info: dict) -> str:
    fill = f", last page {min(100, round(100 * info['fill']))}% full" if info.get("fill") else ""
    s = f"Layout: {info['pages']} page(s) (target {info['target']}), body font {info['font_pt']}pt{fill}."
    if info["pages"] > info["target"]:
        s += " Still too long even at the tightest layout — shorten profile.yaml."
    elif info["t"] >= 1.0 and info.get("fill") and info["fill"] < 0.85:
        s += " Content is short: add more true bullets to profile.yaml (or raise --max-bullets) to fill the page."
    if info["dropped"]:
        s += "\nDropped least-relevant bullets to fit:\n" + "\n".join(f"- {d}" for d in info["dropped"])
    return s
