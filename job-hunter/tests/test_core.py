import json
from datetime import date, timedelta
from pathlib import Path

import yaml

from jobhunter import keywords as kw
from jobhunter import tailor
from jobhunter.dashboard import build
from jobhunter.db import DB
from jobhunter.latex import latex_escape, render
from jobhunter.matcher import Profile, score_job
from jobhunter.models import Job
from jobhunter.sources import adzuna, arbeitnow, arbeitsagentur, url_import

ROOT = Path(__file__).resolve().parents[1]
PROFILE = Profile(yaml.safe_load((ROOT / "profile.example.yaml").read_text()))
CFG = yaml.safe_load((ROOT / "config.example.yaml").read_text())


def test_multilingual_skill_matching():
    hits = kw.find_skills("Erfahrung in Datenanalyse, Power-BI und PostgreSQL; fließend Deutsch", PROFILE.lexicon)
    assert {"Data Analysis", "Power BI", "SQL", "German"} <= set(hits)
    # no false positives from short words
    assert "R (language)" not in kw.find_skills("R&D department, go to market", PROFILE.lexicon)
    assert "Go (language)" not in kw.find_skills("ready to go", PROFILE.lexicon)


def test_job_type_classification():
    assert kw.classify_job_type("Werkstudent (m/w/d) Controlling") == "working_student"
    assert kw.classify_job_type("Praktikum Marketing") == "internship"
    assert kw.classify_job_type("Stage - Analyste financier") == "internship"
    assert kw.classify_job_type("Junior Data Analyst (Vollzeit)") == "full_time"


def test_scoring_prefers_relevant_jobs_and_flags_language():
    good = score_job(Job(source="t", title="Junior Data Analyst",
                         description="Python, SQL, Power BI dashboards. Fluent English."), PROFILE)
    bad = score_job(Job(source="t", title="Senior Mechanical Engineer",
                        description="CATIA, FEM, 8 years experience, verhandlungssicheres Deutsch"), PROFILE)
    assert good.score > 60 > bad.score
    assert "German C1+ required" in bad.flags and any("yrs" in f for f in bad.flags)


def test_arbeitsagentur_parse():
    payload = {"stellenangebote": [{"refnr": "10000-1", "titel": "Data Analyst (m/w/d)", "arbeitgeber": "ACME",
                                    "arbeitsort": {"ort": "Trier", "region": "Rheinland-Pfalz", "land": "Deutschland"},
                                    "aktuelleVeroeffentlichungsdatum": "2026-10-01"}]}
    j = arbeitsagentur.parse_list(payload)[0]
    assert j.company == "ACME" and j.location.startswith("Trier") and "10000-1" in j.url


def test_arbeitnow_and_adzuna_parse():
    j = arbeitnow.parse({"data": [{"slug": "x", "company_name": "B", "title": "Intern Data", "description": "<p>SQL</p>",
                                   "remote": True, "url": "https://a/x", "tags": ["IT"], "job_types": ["Internship"],
                                   "location": "Berlin", "created_at": 1}]})[0]
    assert j.job_type == "internship" and "SQL" in j.description and "remote" in j.location
    j = adzuna.parse({"results": [{"id": 1, "title": "<strong>BI</strong> Analyst", "company": {"display_name": "C"},
                                   "location": {"display_name": "Köln"}, "redirect_url": "https://z", "description": "d",
                                   "created": "2026-10-01T00:00:00Z", "contract_time": "full_time"}]}, "de")[0]
    assert j.title == "BI Analyst" and j.job_type == "full_time"


def test_jsonld_import():
    html = """<html><script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"JobPosting",
    "title":"Business Analyst","description":"<p>SQL &amp; Excel</p>","datePosted":"2026-09-30T10:00",
    "employmentType":["FULL_TIME"],"hiringOrganization":{"@type":"Organization","name":"Bank SA"},
    "jobLocation":{"@type":"Place","address":{"addressLocality":"Luxembourg","addressCountry":"LU"}}}]}</script></html>"""
    j = url_import.parse_jobposting(html, "https://en.jobs.lu/x")
    assert (j.title, j.company, j.location, j.country, j.job_type) == ("Business Analyst", "Bank SA", "Luxembourg", "LU", "full_time")
    assert j.description == "SQL & Excel"


def test_tailor_reorders_without_inventing():
    job = Job(source="t", title="Business Analyst", description="Agile project management in Scrum teams, Jira")
    cv, rep = tailor.tailor(PROFILE, job)
    first = cv["experience"][1]["bullets"]
    assert set(first) == set(PROFILE.data["experience"][1]["bullets"])  # same facts
    assert "Scrum" in first[0]
    assert list(cv["skills"])[0] == "Tools"


def test_latex_render_escapes(tmp_path):
    assert latex_escape("R&D 100% #1 a_b") == r"R\&D 100\% \#1 a\_b"
    data = dict(PROFILE.data, summary="Cost -20% & more")
    tex = render(ROOT / "templates" / "cv.tex.j2", data, ["SQL"])
    assert r"Cost -20\% \& more" in tex and r"\VAR" not in tex and r"\BLOCK" not in tex


def test_tracker_and_dashboard(tmp_path):
    db = DB(tmp_path / "t.db")
    j1 = Job(source="t", title="A", company="X", url="https://x/1", description="jd one")
    j2 = Job(source="t", title="B", company="Y", url="https://x/2", description="jd two")
    assert db.upsert_job(j1) and db.upsert_job(j2) and not db.upsert_job(j1)
    old = (date.today() - timedelta(days=30)).isoformat()
    a1 = db.add_application(j1.uid, when=old)
    a2 = db.add_application(j2.uid[:6])
    db.update_application(a2, "interview", notes="call with HR")
    apps = {a["id"]: a for a in db.applications(no_response_after_days=21)}
    assert apps[a1]["status"] == "no_response" and apps[a2]["status"] == "interview"
    out = build(list(apps.values()), [], CFG, tmp_path / "d.html")
    html = out.read_text()
    data = json.loads(html.split("const D=", 1)[1].split(";\n", 1)[0])
    assert data["kpis"]["Applications"] == 2 and data["kpis"]["Interviews"] == 1
    assert "stepstone.de/jobs/data-analyst/in-trier" in html


def test_llm_rewrite_guardrail(monkeypatch):
    import sys
    import types

    from jobhunter import llm

    exp = PROFILE.data["experience"][0]["bullets"]
    fake_out = {"summary": "Data analyst with Python and SQL.", "notes": "No Azure experience.",
                "experience": [{"index": 0, "bullets": ["Designed Power BI dashboards for 25 sales KPIs, saving 6 hours weekly.",
                                                        "Built Kubernetes clusters on AWS.",  # fabricated -> must be reverted
                                                        *exp[2:]]}]}

    class Msgs:
        def create(self, **kw):
            assert kw["model"] == "claude-opus-5-5" and kw["output_config"]["format"]["type"] == "json_schema"
            block = types.SimpleNamespace(type="text", text=json.dumps(fake_out))
            return types.SimpleNamespace(stop_reason="end_turn", content=[block])

    fake = types.SimpleNamespace(Anthropic=lambda: types.SimpleNamespace(beta=types.SimpleNamespace(messages=Msgs())))
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    cv, note = llm.rewrite(PROFILE.data, PROFILE, Job(source="t", title="Data Analyst", description="Power BI"))
    bullets = cv["experience"][0]["bullets"]
    assert bullets[0].startswith("Designed Power BI")
    assert bullets[1] == exp[1]  # reverted to the original
    assert "reverted" in note


def test_compact_template_and_markup():
    data = dict(PROFILE.data)
    data["education"] = [dict(PROFILE.data["education"][0], bullets=["**Thesis:** Risk & Return (95%)"])]
    tex = render(ROOT / "templates" / "compact.tex.j2", data, ["SQL"])
    assert r"\textbf{Thesis:} Risk \& Return (95\%)" in tex
    assert r"\VAR" not in tex and r"\BLOCK" not in tex and "includegraphics" not in tex  # no photo by default
    tex = render(ROOT / "templates" / "compact.tex.j2", dict(data, photo="me.jpg"), [])
    assert r"\includegraphics[width=2.3cm]{me.jpg}" in tex


def test_profile_skill_names_merge_and_short_names_skip():
    p = Profile(dict(PROFILE.data, skills={"Finance": ["Cash management", "R"]},
                     education=[{"degree": "MSc", "bullets": ["Statistical Programming with R (1.3)"]}]))
    assert "Cash management" not in p.lexicon and "R" not in p.lexicon  # merged into lexicon / skipped
    assert "R (language)" in p.skills  # still detected from "with R"
    assert "R (language)" not in kw.find_skills("Head of R&D", p.lexicon)
