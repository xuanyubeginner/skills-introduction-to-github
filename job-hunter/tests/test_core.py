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
    assert r"\includegraphics[height=2.6cm,width=2.8cm,keepaspectratio]{me.jpg}" in tex


def test_profile_skill_names_merge_and_short_names_skip():
    p = Profile(dict(PROFILE.data, skills={"Finance": ["Cash management", "R"]},
                     education=[{"degree": "MSc", "bullets": ["Statistical Programming with R (1.3)"]}]))
    assert "Cash management" not in p.lexicon and "R" not in p.lexicon  # merged into lexicon / skipped
    assert "R (language)" in p.skills  # still detected from "with R"
    assert "R (language)" not in kw.find_skills("Head of R&D", p.lexicon)


def test_compact_section_order_and_personal_line():
    contact = dict(PROFILE.data["contact"], birth_date="05.03.1996", nationality="Chinese")
    data = dict(PROFILE.data, contact=contact)
    tex = render(ROOT / "templates" / "compact.tex.j2", data, [])
    assert r"\mbox{Date of birth: 05.03.1996}\discretionary{}{}{\kern0.5em\textbar\kern0.5em}\mbox{Nationality: Chinese}" in tex
    assert r"\mbox{Tel: " in tex and r"\mbox{Address: " in tex
    assert tex.index("Key Skills") < tex.index("Professional Experience") < tex.index(r"\section{Education}")
    tex = render(ROOT / "templates" / "compact.tex.j2",
                 dict(data, section_order=["profile", "skills", "education", "experience"]), [])
    assert tex.index(r"\section{Education}") < tex.index("Professional Experience")
    assert tex.count(r"\begin{document}") == 1
    tex = render(ROOT / "templates" / "compact.tex.j2",
                 dict(data, section_order=["profile", "education", "experience", "skills"]), [])
    assert tex.index(r"\section{Education}") < tex.index("Professional Experience") < tex.index(r"\section{Skills}")
    assert "Key Skills" not in tex  # "Key Skills" only when it directly follows the profile


def test_fit_params_monotonic_and_drop_order():
    from jobhunter import fit
    a, b = fit.params(0.0), fit.params(1.0)
    assert a["fs"] < fit.params(0.5)["fs"] < b["fs"] and a["sp"] < b["sp"] and a["ml"] < b["ml"]
    cv = {"experience": [{"title": "A", "bullets": ["a1", "a2", "a3"]}, {"title": "B", "bullets": ["b1", "b2"]}],
          "projects": [{"name": "P"}]}
    assert fit._drop_one(cv) == "A: a3"          # least relevant bullet of the longest role
    assert fit._drop_one(cv) == "project: P"     # roles keep >= 2 bullets
    assert fit._drop_one(cv) is None


import shutil as _shutil  # noqa: E402

import pytest  # noqa: E402


@pytest.mark.skipif(not (_shutil.which("latexmk") or _shutil.which("pdflatex")), reason="needs LaTeX")
@pytest.mark.parametrize("extra_bullets", [0, 60])
def test_fit_to_exactly_one_page(tmp_path, extra_bullets):
    import copy

    from jobhunter import fit
    cv = copy.deepcopy(PROFILE.data)
    cv["experience"][0]["bullets"] += [f"Additional achievement number {i} with enough words to wrap onto a "
                                       f"second line in the compact layout of the CV template" for i in range(extra_bullets)]
    pdf, info = fit.fit_to_pages(ROOT / "templates" / "compact.tex.j2", cv, [], tmp_path / "cv.tex", pages=1)
    assert info["pages"] == 1 and len(fit.PdfReader(str(pdf)).pages) == 1
    assert bool(info["dropped"]) == (extra_bullets > 0)


def test_compact_photo_header_keeps_profile_below():
    tex = render(ROOT / "templates" / "compact.tex.j2", dict(PROFILE.data, photo="me.png"), [])
    assert tex.count(r"\section{Profile}") == 1
    assert tex.index(r"\includegraphics") < tex.index(r"\section{Profile}") < tex.index(r"\section{Key Skills}")
    tex = render(ROOT / "templates" / "compact.tex.j2", dict(PROFILE.data), [])
    assert tex.count(r"\section{Profile}") == 1 and "includegraphics" not in tex


DE_PROFILE = {
    "name": "Max Muster", "headline": "Finanzbuchhalter",
    "contact": {"email": "max@example.de", "phone": "+49 151 1234567", "location": "Musterweg 1, 54290 Trier"},
    "summary": "Finanzbuchhalter mit Erfahrung in Kontierung & Kontenabstimmung.",
    "experience": [{"title": "Finanzbuchhalter", "company": "Muster GmbH", "location": "Trier", "start": "01/2020",
                    "end": "heute", "bullets": ["Prüfung, Kontierung und Verbuchung von Rechnungen.",
                                                "Unterstützung bei Monatsabschlüssen nach HGB."]}],
    "education": [{"degree": "B.A. BWL", "school": "Universität Trier", "location": "Trier", "start": "2016",
                   "end": "2019", "bullets": ["**Schwerpunkt:** Rechnungswesen"]}],
    "languages": [{"name": "Deutsch", "level": "Muttersprache"}, {"name": "Englisch", "level": "fließend"}],
    "skills": {"EDV-Kenntnisse": ["SAP FI&CO", "MS Office"]},
    "certifications": ["CFA Level I"], "interests": ["Volleyball"],
}


def test_german_template_and_language_rules():
    tex = render(ROOT / "templates" / "de.tex.j2", DE_PROFILE, [])
    for heading in ("Profil", "Berufserfahrung", "Ausbildung", "Kenntnisse und Interessen"):
        assert r"\section*{" + heading + "}" in tex
    assert tex.index("Berufserfahrung") < tex.index("Ausbildung")      # German default order
    assert r"\item[01/2020 -- heute] \textbf{Finanzbuchhalter}" in tex
    assert r"SAP FI\&CO\\ MS Office" in tex and r"\textbf{Schwerpunkt:}" in tex
    assert r"E-Mail: " in tex and "faEnvelope" not in tex and "tabularx" not in tex
    assert r"\VAR" not in tex and r"\BLOCK" not in tex
    p = Profile(DE_PROFILE)
    assert p.language_level("German") == 7 and p.language_level("English") == 5
    assert not kw.GERMAN_REQUIRED.search(kw.normalize("gute Deutschkenntnisse"))
    assert kw.GERMAN_REQUIRED.search(kw.normalize("sehr gute Deutschkenntnisse in Wort und Schrift"))


@pytest.mark.skipif(not (_shutil.which("latexmk") or _shutil.which("pdflatex")), reason="needs LaTeX")
def test_german_cv_fits_one_page_and_passes_ats(tmp_path):
    from jobhunter import ats, fit
    p = Profile(DE_PROFILE)
    pdf, info = fit.fit_to_pages(ROOT / "templates" / "de.tex.j2", dict(DE_PROFILE), [], tmp_path / "lebenslauf.tex")
    res = ats.check(pdf, DE_PROFILE, ["Accounting", "SAP"], p.lexicon)
    assert info["pages"] == 1 and all(res["checks"].values()), res["checks"]
