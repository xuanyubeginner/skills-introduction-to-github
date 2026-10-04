# Job Hunter: job search, ATS CV tailoring and application tracking (DE / LU / EU)

This is a local command-line tool. It covers four things:

1. **Job search**: it collects postings from several sources and scores each one against your CV.
2. **CV tailoring**: it reorders your real CV content to fit a job description (JD) and checks the result the way an ATS would.
3. **PDF output**: it renders your LaTeX template and compiles it to PDF.
4. **Application tracking**: it keeps a SQLite tracker and builds an HTML dashboard.

---

## 1. Analysis of the problem

| Need | Obstacle | How the tool handles it |
|---|---|---|
| Collect jobs from LinkedIn, StepStone, Moovijob, jobs.lu and Google Jobs | None of these sites has a public API. They all block bots, and LinkedIn's terms forbid scraping. A scraper built for one site breaks when that site changes. | **Several layers**: ① Official or free APIs fetch jobs automatically. **Bundesagentur für Arbeit** is Germany's largest job database and mirrors many StepStone/Indeed jobs. Arbeitnow and Adzuna are also supported. ② The optional [JobSpy](https://github.com/speedyapply/JobSpy) library covers LinkedIn, Indeed and Google Jobs. ③ **Import by URL**: almost every job site embeds schema.org `JobPosting` JSON-LD, because Google Jobs needs it. The tool parses that data, so StepStone, Moovijob, jobs.lu and company career pages all work through one parser. ④ The dashboard has one-click search links for every keyword × city × site. |
| Decide which jobs fit | JDs come in German, English and French, with different words for the same skill (e.g. "Datenanalyse" = "Data Analysis"). Hard requirements like "fließend Deutsch", "5+ years" or "Senior" make a job unsuitable even when the skills match. | A skill dictionary in three languages (`skills_lexicon.txt`) plus an explainable 0–100 score: skill coverage 55, title similarity 30, job type 15. It then deducts points for missing language level, seniority and years of experience. Each job lists **matched / missing keywords and warning flags**. |
| Fit the CV to the JD and pass the ATS | An ATS matches keywords literally. Two-column layouts, tables, icons and ligatures garble the text it extracts. Stuffing in skills you don't have will fail at the interview. | **Your profile is the only source of truth** (`profile.yaml`). The tool only **reorders and selects** your real content: matching skills first, relevant bullets first, the most relevant projects. The optional Claude rewrite only rephrases. Any rewritten line that brings in a skill your profile doesn't show is **automatically reverted**. After compiling, the tool **extracts the PDF text again** (what an ATS sees) and checks contact details, section headings, keyword coverage, page count and ligatures. |
| Output a PDF from your LaTeX template | Templates differ. Chinese text, multiple columns and similar features hurt ATS parsing. | The template uses Jinja2 with LaTeX-safe delimiters (`\VAR{}` / `\BLOCK{}`). The bundled template is single-column and ATS-friendly (`glyphtounicode`, ligatures disabled, standard headings). Your own template can be adapted the same way (see §5). |
| Tracking dashboard | Sources are scattered, and "no response" is hard to see. | SQLite tracker. Each entry records date, job title, JD, status and match score. Applications with no reply after N days are automatically marked **No response**. The HTML dashboard shows KPI tiles, weekly applications, a searchable/sortable table, expandable JDs and the top matches you haven't applied to yet. |

## 2. Architecture

```
profile.yaml (your real CV data) ─┐
config.yaml (keywords/cities/sources) ─┤
                                       ▼
 sources/ ── arbeitsagentur · arbeitnow · adzuna · jobspy(optional) · url_import(JSON-LD)
                                       ▼
 matcher.py  (multilingual keywords + explainable score) ──► data/jobhunter.db (SQLite)
                                       ▼
 tailor.py (reorder/select) ─► llm.py (optional Claude rephrase + anti-fabrication check)
                                       ▼
 latex.py (Jinja → .tex → latexmk → PDF) ─► ats.py (re-extract PDF text and check)
                                       ▼
 db.py tracker ─► dashboard.py ─► output/dashboard.html
```

## 3. Installation

```bash
cd job-hunter
pip install -r requirements.txt
# LaTeX (pick one):
#   Ubuntu/Debian: sudo apt install latexmk texlive-latex-extra lmodern
#   macOS:         brew install --cask mactex-no-gui
#   Windows:       install MiKTeX (includes latexmk)
#   or the lightweight tectonic: https://tectonic-typesetting.github.io
# Optional:
pip install anthropic        # --llm: Claude rewrite (needs ANTHROPIC_API_KEY)
pip install python-jobspy    # LinkedIn / Indeed / Google Jobs

python -m jobhunter init     # creates config.yaml and profile.yaml
```

Then:

- **Fill in your full CV in `profile.yaml`.** Write down every true bullet you might use; the tool picks the ones that fit each job.
- Edit the keywords and cities in `config.yaml`.
- `config.yaml`, `profile.yaml`, `data/` and `output/` are in `.gitignore`, so your personal data won't be committed.

## 4. Daily workflow

```bash
# 1) Search and score (automatic sources)
python -m jobhunter search
python -m jobhunter search -k "Werkstudent Controlling" -l Trier       # one-off query
python -m jobhunter search -k "Data Analyst" -l Luxembourg --country lu -s jobspy

# 2) Found a job on LinkedIn / StepStone / Moovijob / jobs.lu? Import it by URL
python -m jobhunter add --url "https://www.stepstone.de/stellenangebote--...html"
# If the page blocks bots: copy the JD text into a file
python -m jobhunter add --text-file jd.txt --title "Data Analyst" --company "ACME" --location Luxembourg

# 3) See the details (JD, matched/missing keywords, flags)
python -m jobhunter show <ID>

# 4) Generate the tailored CV + PDF + ATS report
python -m jobhunter tailor <ID> --pdf            # deterministic reorder
python -m jobhunter tailor <ID> --pdf --llm      # plus Claude rephrasing (check every line)
#   → output/<date>_<company>_<title>/  Name_CV.tex / .pdf / ats_report.md / job_description.txt
#   After hand-editing the .tex: python -m jobhunter build output/.../Name_CV.tex

# 5) Track applications
python -m jobhunter track add <ID> --cv output/.../Name_CV.pdf
python -m jobhunter track update <#> --status interview      # applied|interview|offer|rejected|withdrawn
python -m jobhunter track list

# 6) Dashboard
python -m jobhunter dashboard --open
```

**No local LaTeX? Use Overleaf** (the website, or the VS Code "Overleaf Workshop" extension):

1. Run `tailor <ID>` without `--pdf`. It still writes the `.tex` file.
2. Paste that `.tex` into an Overleaf project and compile it there (the default pdfLaTeX compiler works).
3. Download the PDF, then run the ATS check on it:

   ```bash
   python -m jobhunter check <ID> ~/Downloads/main.pdf
   ```

**What to do with `ats_report.md`:**

- **Missing keywords**: if a keyword is genuinely true for you (a course, project or work task), add it to `profile.yaml` using the JD's exact wording, then run `tailor` again.
- **If it isn't true**: don't add it. Prepare to answer it in the cover letter or interview instead.

## 5. Using your own LaTeX template

1. Copy your `.tex` to `templates/my_cv.tex.j2`.
2. Replace the content with variables. Example:

   ```latex
   \section{Experience}
   \BLOCK{ for x in cv.experience }
   \textbf{\VAR{x.title|e}} -- \VAR{x.company|e} \hfill \VAR{x.start|e} -- \VAR{x.end|e}
   \begin{itemize}
   \BLOCK{ for b in x.bullets }  \item \VAR{b|e}
   \BLOCK{ endfor }\end{itemize}
   \BLOCK{ endfor }
   ```

   - `|e` escapes LaTeX special characters such as `& % $ # _`.
   - Lines starting with `%%` are template comments and won't appear in the output.
   - The available fields are exactly those in `profile.yaml`; `templates/cv.tex.j2` is a complete reference.
3. Run `python -m jobhunter tailor <ID> --pdf --template templates/my_cv.tex.j2`.

**ATS tips:**

- Avoid multi-column layouts, `tabular`-based layouts, icon fonts, text in images, and text boxes in headers/footers.
- Keep `\input{glyphtounicode}\pdfgentounicode=1`.
- If you need Chinese/CJK characters, use XeLaTeX (`latexmk -xelatex`) and `fontspec`.

## 6. Sources and compliance

| Source | Coverage | Key | Notes |
|---|---|---|---|
| Bundesagentur für Arbeit | DE (largest) | none needed (public client ID) | Official API; includes many jobs mirrored from StepStone/Indeed |
| Arbeitnow | DE / remote, many English-language jobs | none needed | Free API |
| Adzuna | DE, AT, BE, FR, NL, … (**no LU**) | free signup | Description is only a snippet; use `add --url` for the full text |
| JobSpy (optional) | LinkedIn, Indeed (incl. LU), Google Jobs | — | Unofficial scraper. Keep volume low, personal use only; it may be rate-limited |
| `add --url` | StepStone, Moovijob, jobs.lu, LinkedIn, company sites | — | Parses JSON-LD; one page per request, like manual browsing |
| Search links | All sites | — | One click in the dashboard opens filtered searches |

For Luxembourg, **job alert emails** from Moovijob and jobs.lu work best. Paste the links you find interesting into `add --url`.

## 7. Tests

```bash
python -m pytest -q tests
```
