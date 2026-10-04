"""Command line interface:  python -m jobhunter <command> --help"""
from __future__ import annotations

import argparse
import logging
import re
import shutil
import sys
import webbrowser
from datetime import date
from pathlib import Path

import yaml

from . import ats, dashboard, latex, tailor
from .db import DB, STATUSES
from .matcher import Profile, score_job
from .models import Job
from .sources import adzuna, arbeitnow, arbeitsagentur, jobspy_source, url_import

ROOT = Path.cwd()
SOURCES = {"arbeitsagentur": arbeitsagentur, "arbeitnow": arbeitnow, "adzuna": adzuna, "jobspy": jobspy_source}
log = logging.getLogger("jobhunter")


def load_yaml(name: str) -> dict:
    p = ROOT / name
    if not p.exists():
        sys.exit(f"{name} not found. Run `python -m jobhunter init` first, then edit it.")
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def ctx():
    cfg, prof = load_yaml("config.yaml"), Profile(load_yaml("profile.yaml"))
    return cfg, prof, DB(ROOT / "data" / "jobhunter.db")


def short(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "…"


def print_jobs(jobs: list[Job]):
    print(f"{'ID':<10} {'Score':>5}  {'Type':<15} {'Title':<45} {'Company':<25} {'Location':<20} Flags")
    for j in jobs:
        print(f"{j.uid:<10} {j.score:>5.0f}  {j.job_type:<15} {short(j.title, 45):<45} {short(j.company, 25):<25} "
              f"{short(j.location, 20):<20} {'; '.join(j.flags)}")


# --- commands ---------------------------------------------------------------

def cmd_init(_):
    for src, dst in [("config.example.yaml", "config.yaml"), ("profile.example.yaml", "profile.yaml")]:
        if (ROOT / dst).exists():
            print(f"{dst} exists, kept.")
        else:
            shutil.copy(ROOT / src, ROOT / dst)
            print(f"Created {dst} — edit it with your data.")


def cmd_search(a):
    cfg, prof, db = ctx()
    s = cfg["search"]
    keywords = a.keyword or s["keywords"]
    locations = [{"name": l, "country": a.country} for l in a.location] if a.location else s["locations"]
    enabled = a.sources or [n for n, c in cfg.get("sources", {}).items() if c and c.get("enabled")]
    found: dict[str, Job] = {}
    for name in enabled:
        mod = SOURCES[name]
        scfg = {**s, "_source": cfg["sources"].get(name, {})}
        for loc in locations:
            for kwd in keywords:
                try:
                    jobs = mod.search(kwd, loc, scfg)
                except Exception as exc:
                    log.warning("%s failed for '%s' @ %s: %s", name, kwd, loc["name"], exc)
                    continue
                for j in jobs:
                    found.setdefault(j.uid, j)
                if jobs:
                    print(f"  {name:<15} {kwd!r} @ {loc['name']}: {len(jobs)}")
    new = 0
    scored = [score_job(j, prof) for j in found.values()]
    for j in scored:
        new += db.upsert_job(j)
    min_score = a.min_score if a.min_score is not None else s.get("min_score", 0)
    shown = sorted((j for j in scored if j.score >= min_score), key=lambda j: -j.score)[: a.limit]
    print(f"\n{len(scored)} jobs found ({new} new); {len(shown)} with score >= {min_score}:\n")
    print_jobs(shown)
    print("\nNext: python -m jobhunter show <ID>   |   python -m jobhunter tailor <ID> --pdf")


def cmd_add(a):
    cfg, prof, db = ctx()
    if a.url and not a.text_file:
        job = url_import.import_url(a.url)
    else:
        use_file = a.text_file and a.text_file != "-"
        text = Path(a.text_file).read_text(encoding="utf-8") if use_file else sys.stdin.read()
        job = Job(source="manual", title=a.title or text.strip().splitlines()[0][:120], description=text, url=a.url or "")
    job.title = a.title or job.title
    job.company = a.company or job.company
    job.location = a.location or job.location
    score_job(job, prof)
    db.upsert_job(job)
    print_jobs([job])
    print(f"\nMatched: {', '.join(job.matched) or '-'}\nMissing: {', '.join(job.missing) or '-'}")


def cmd_jobs(a):
    _, _, db = ctx()
    jobs = sorted((j for _, j in db.jobs() if j.score >= a.min_score), key=lambda j: -j.score)[: a.limit]
    print_jobs(jobs)


def cmd_show(a):
    _, prof, db = ctx()
    j = score_job(db.get_job(a.id), prof)
    print(f"{j.title} — {j.company} — {j.location}\n{j.url}\nScore {j.score} | type {j.job_type} | flags: {'; '.join(j.flags) or '-'}")
    print(f"Matched: {', '.join(j.matched) or '-'}\nMissing: {', '.join(j.missing) or '-'}\n")
    print(j.description)


def slugify(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")[:40]


def cmd_tailor(a):
    cfg, prof, db = ctx()
    job = score_job(db.get_job(a.id), prof)
    cv, rep = tailor.tailor(prof, job, max_bullets=a.max_bullets, max_projects=a.max_projects)
    note = ""
    if a.llm:
        from . import llm
        llm_cfg = cfg.get("llm", {})
        try:
            cv, note = llm.rewrite(cv, prof, job, model=llm_cfg.get("model", "claude-opus-5-5"),
                                   effort=llm_cfg.get("effort", "medium"))
        except Exception as exc:
            note = f"AI rewrite failed ({exc}); deterministic version kept."
            print(note)
    outdir = ROOT / "output" / f"{date.today():%Y%m%d}_{slugify(job.company or 'company')}_{slugify(job.title)}"
    outdir.mkdir(parents=True, exist_ok=True)
    name = slugify(prof.data.get("name", "CV")) + "_CV"
    tex = outdir / f"{name}.tex"
    template = Path(a.template) if a.template else ROOT / "templates" / "cv.tex.j2"
    tex.write_text(latex.render(template, cv, rep["matched"]), encoding="utf-8")
    (outdir / "job_description.txt").write_text(f"{job.title}\n{job.company}\n{job.url}\n\n{job.description}", encoding="utf-8")
    (outdir / "tailored_profile.yaml").write_text(yaml.safe_dump(cv, allow_unicode=True, sort_keys=False), encoding="utf-8")
    ats_res = None
    if a.pdf:
        pdf = latex.compile_pdf(tex)
        ats_res = ats.check(pdf, cv, rep["jd_keywords"], prof.lexicon)
        print(f"PDF: {pdf}")
    (outdir / "ats_report.md").write_text(ats.report_markdown(job.to_dict(), rep, ats_res, note), encoding="utf-8")
    print(f"LaTeX: {tex}\nReport: {outdir / 'ats_report.md'}")
    print(f"JD keyword coverage: {rep['coverage']}%  | missing: {', '.join(rep['missing'][:10]) or '-'}")
    if ats_res:
        bad = [k for k, ok in ats_res["checks"].items() if not ok]
        print("ATS checks: " + ("all passed" if not bad else "FAILED: " + ", ".join(bad)))


def cmd_build(a):
    pdf = latex.compile_pdf(Path(a.tex))
    print(f"PDF: {pdf}")


def cmd_check(a):
    """ATS-check a PDF compiled elsewhere (e.g. Overleaf) against a job's JD."""
    _, prof, db = ctx()
    job = score_job(db.get_job(a.id), prof)
    pdf = Path(a.pdf).expanduser()
    if not pdf.exists():
        sys.exit(f"PDF not found: {pdf}")
    cv, rep = tailor.tailor(prof, job)
    res = ats.check(pdf, cv, rep["jd_keywords"], prof.lexicon)
    report = pdf.parent / "ats_report.md"
    report.write_text(ats.report_markdown(job.to_dict(), rep, res), encoding="utf-8")
    for name, ok in res["checks"].items():
        print(f"  [{'x' if ok else ' '}] {name}")
    print(f"Keyword coverage in PDF text: {res['coverage']}%  | not found: {', '.join(res['absent']) or '-'}")
    print(f"Report: {report}")


def cmd_track(a):
    cfg, _, db = ctx()
    if a.action == "add":
        app_id = db.add_application(a.id, status=a.status, when=a.date, cv_path=a.cv or "", notes=a.notes or "")
        print(f"Application #{app_id} recorded ({a.status}).")
    elif a.action == "update":
        db.update_application(int(a.id), a.status, notes=a.notes, when=a.date)
        print(f"Application #{a.id} -> {a.status}")
    else:
        days = cfg.get("tracker", {}).get("no_response_after_days", 21)
        print(f"{'#':>3} {'Date':<11} {'Status':<12} {'Title':<40} Company")
        for r in db.applications(days):
            print(f"{r['id']:>3} {r['date_applied'] or '-':<11} {r['status']:<12} {short(r['title'], 40):<40} {r['company']}")


def cmd_dashboard(a):
    cfg, prof, db = ctx()
    days = cfg.get("tracker", {}).get("no_response_after_days", 21)
    apps = db.applications(days)
    applied_uids = {r["job_uid"] for r in apps}
    min_score = cfg["search"].get("min_score", 0)
    # re-score so edits to profile.yaml are reflected without a new search
    rescored = [score_job(j, prof) for _, j in db.jobs() if j.uid not in applied_uids]
    top = sorted((j.to_dict() for j in rescored if j.score >= min_score), key=lambda j: -j["score"])[:30]
    out = dashboard.build(apps, top, cfg, ROOT / "output" / "dashboard.html")
    print(f"Dashboard: {out}")
    if a.open:
        webbrowser.open(out.as_uri())


def main(argv=None):
    p = argparse.ArgumentParser(prog="jobhunter", description="Job search, CV tailoring and application tracking")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create config.yaml and profile.yaml from the examples").set_defaults(fn=cmd_init)

    s = sub.add_parser("search", help="search all enabled sources and score jobs against your profile")
    s.add_argument("-k", "--keyword", action="append", help="override keywords (repeatable)")
    s.add_argument("-l", "--location", action="append", help="override locations (repeatable)")
    s.add_argument("--country", default="de", help="country code for --location (de, lu, fr, ...)")
    s.add_argument("-s", "--sources", nargs="+", choices=list(SOURCES))
    s.add_argument("--min-score", type=float)
    s.add_argument("--limit", type=int, default=40)
    s.set_defaults(fn=cmd_search)

    s = sub.add_parser("add", help="add a job from a URL (LinkedIn, StepStone, Moovijob, jobs.lu...) or pasted text")
    s.add_argument("--url")
    s.add_argument("--text-file", help="file with the JD text (use '-' or omit with no --url to read stdin)")
    s.add_argument("--title"), s.add_argument("--company"), s.add_argument("--location")
    s.set_defaults(fn=cmd_add)

    s = sub.add_parser("jobs", help="list stored jobs by score")
    s.add_argument("--min-score", type=float, default=0)
    s.add_argument("--limit", type=int, default=50)
    s.set_defaults(fn=cmd_jobs)

    s = sub.add_parser("show", help="show a job, its JD and match details")
    s.add_argument("id")
    s.set_defaults(fn=cmd_show)

    s = sub.add_parser("tailor", help="generate a JD-tailored CV (.tex, optional PDF) + ATS report")
    s.add_argument("id")
    s.add_argument("--pdf", action="store_true", help="compile to PDF and run ATS checks on the PDF text")
    s.add_argument("--llm", action="store_true", help="let Claude rephrase summary/bullets (needs ANTHROPIC_API_KEY)")
    s.add_argument("--template", help="path to your own Jinja-LaTeX template")
    s.add_argument("--max-bullets", type=int, default=5)
    s.add_argument("--max-projects", type=int, default=3)
    s.set_defaults(fn=cmd_tailor)

    s = sub.add_parser("build", help="compile a (hand-edited) .tex to PDF")
    s.add_argument("tex")
    s.set_defaults(fn=cmd_build)

    s = sub.add_parser("check", help="ATS-check a PDF compiled elsewhere (e.g. Overleaf) against a job")
    s.add_argument("id", help="job ID")
    s.add_argument("pdf", help="path to the PDF")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("track", help="application tracker")
    s.add_argument("action", choices=["add", "update", "list"])
    s.add_argument("id", nargs="?", help="job ID for add, application # for update")
    s.add_argument("--status", choices=STATUSES, default="applied")
    s.add_argument("--date", help="YYYY-MM-DD (default today)")
    s.add_argument("--cv", help="path of the CV you sent")
    s.add_argument("--notes")
    s.set_defaults(fn=cmd_track)

    s = sub.add_parser("dashboard", help="build output/dashboard.html")
    s.add_argument("--open", action="store_true")
    s.set_defaults(fn=cmd_dashboard)

    a = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO, format="%(levelname)s %(message)s")
    if a.cmd == "track" and a.action != "list" and not a.id:
        p.error("track add/update needs an id")
    a.fn(a)
