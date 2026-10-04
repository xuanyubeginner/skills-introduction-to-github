"""Generate a self-contained HTML dashboard (open in any browser, works offline)."""
from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, quote_plus

STATUS_LABEL = {"saved": "Saved", "applied": "Applied (waiting)", "no_response": "No response",
                "interview": "Interview", "offer": "Offer", "rejected": "Rejected", "withdrawn": "Withdrawn"}


def _slug(s: str) -> str:
    return quote("-".join(s.lower().split()))


def search_links(cfg: dict) -> list[dict]:
    out = []
    templates = cfg.get("search_links", {})
    for loc in cfg["search"]["locations"]:
        for q in cfg["search"]["keywords"]:
            links = {name: t.format(q=quote_plus(q), loc=quote_plus(loc["name"]), q_slug=_slug(q), loc_slug=_slug(loc["name"]))
                     for name, t in templates.items()}
            out.append({"q": q, "loc": loc["name"], "links": links})
    return out


def weekly_counts(apps: list[dict], weeks: int = 12) -> list[dict]:
    today = date.today()
    start = today - timedelta(days=today.weekday()) - timedelta(weeks=weeks - 1)
    c = Counter()
    for a in apps:
        if a["date_applied"]:
            d = datetime.fromisoformat(a["date_applied"]).date()
            if d >= start:
                c[(d - start).days // 7] += 1
    return [{"week": (start + timedelta(weeks=i)).isoformat(), "n": c[i]} for i in range(weeks)]


def build(apps: list[dict], top_jobs: list[dict], cfg: dict, out: Path) -> Path:
    applied = [a for a in apps if a["date_applied"]]
    st = Counter(a["status"] for a in apps)
    responded = st["interview"] + st["offer"] + st["rejected"]
    kpis = {
        "Applications": len(applied),
        "Interviews": st["interview"] + st["offer"],
        "Rejected": st["rejected"],
        "No response": st["no_response"],
        "Waiting": st["applied"],
        "Response rate": f"{round(100 * responded / len(applied))}%" if applied else "–",
    }
    data = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "apps": apps, "kpis": kpis, "weeks": weekly_counts(apps),
        "status_label": STATUS_LABEL, "top": top_jobs, "links": search_links(cfg),
    }
    html = TEMPLATE.replace("/*DATA*/null", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Job Search Dashboard</title>
<style>
:root{color-scheme:light;--bg:#f7f7f5;--surface:#fcfcfb;--border:#e4e3df;--text:#0b0b0b;--text2:#52514e;--muted:#7a7974;
--series:#2a78d6;--grid:#ecebe7;--good:#1a7f37;--warn:#9a6700;--bad:#c62828;--chip:#f0efec}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#121211;--surface:#1a1a19;--border:#2e2e2b;
--text:#fff;--text2:#c3c2b7;--muted:#99988f;--series:#3987e5;--grid:#2a2a27;--good:#4ac26b;--warn:#d4a72c;--bad:#ef6b6b;--chip:#26261f}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#121211;--surface:#1a1a19;--border:#2e2e2b;--text:#fff;--text2:#c3c2b7;--muted:#99988f;
--series:#3987e5;--grid:#2a2a27;--good:#4ac26b;--warn:#d4a72c;--bad:#ef6b6b;--chip:#26261f}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1200px;margin:0 auto;padding:20px 16px 48px}h1{font-size:22px;margin:0 0 2px}h2{font-size:16px;margin:28px 0 10px}
.sub{color:var(--text2);margin:0 0 18px}.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px}.kpi .v{font-size:26px;font-weight:650}.kpi .l{color:var(--text2);font-size:12px}
.chart{position:relative;height:170px;display:flex;align-items:flex-end;gap:6px;padding:8px 0 22px;border-bottom:1px solid var(--grid)}
.bar{flex:1;position:relative;height:100%;display:flex;align-items:flex-end;justify-content:center;cursor:default}.bar>i{display:block;width:100%;max-width:44px;background:var(--series);border-radius:4px 4px 0 0;min-height:0}
.bar>span{position:absolute;bottom:-20px;left:0;right:0;text-align:center;font-size:10px;color:var(--muted)}
.bar:hover>i{outline:2px solid var(--text2);outline-offset:1px}#tip{position:fixed;pointer-events:none;background:var(--text);color:var(--surface);padding:4px 8px;border-radius:6px;font-size:12px;display:none}
.filters{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px}input,select{background:var(--surface);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:7px 9px;font:inherit}
input{flex:1;min-width:180px}.tablewrap{overflow-x:auto}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:8px;border-bottom:1px solid var(--border);vertical-align:top}
th{font-size:12px;color:var(--text2);font-weight:600;cursor:pointer;white-space:nowrap}td.num{text-align:right;font-variant-numeric:tabular-nums}
.st{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;background:var(--chip);color:var(--text);white-space:nowrap}
.st::before{content:"";display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:5px;background:var(--muted)}
.st.interview::before,.st.offer::before{background:var(--good)}.st.rejected::before{background:var(--bad)}.st.no_response::before{background:var(--warn)}.st.applied::before{background:var(--series)}
details summary{cursor:pointer;color:var(--text2)}details .jd{white-space:pre-wrap;max-height:320px;overflow:auto;font-size:12px;color:var(--text2);margin-top:6px}
a{color:var(--series)}.muted{color:var(--muted)}.links a{margin-right:10px;white-space:nowrap}.cmd{font-family:ui-monospace,monospace;font-size:12px;color:var(--muted)}
</style></head><body><main>
<h1>Job Search Dashboard</h1><p class="sub" id="gen"></p>
<section class="kpis" id="kpis"></section>
<h2>Applications per week</h2><div class="card"><div class="chart" id="chart" role="img" aria-label="Applications submitted per week"></div></div>
<h2>Applications</h2>
<div class="card"><div class="filters"><input id="q" placeholder="Search title, company, JD…" aria-label="Search">
<select id="fs" aria-label="Status"><option value="">All statuses</option></select></div>
<div class="tablewrap"><table><thead><tr><th data-k="id">#</th><th data-k="date_applied">Date</th><th data-k="title">Job title</th><th data-k="company">Company</th>
<th data-k="status">Status</th><th data-k="score">Match</th><th>Job description</th></tr></thead><tbody id="rows"></tbody></table></div>
<p class="cmd">Update: python -m jobhunter track update &lt;#&gt; --status interview|rejected|offer</p></div>
<h2>Top new matches (not applied yet)</h2><div class="card tablewrap"><table><thead><tr><th>ID</th><th>Score</th><th>Job title</th><th>Company</th><th>Location</th><th>Type</th><th>Missing keywords / flags</th></tr></thead><tbody id="top"></tbody></table>
<p class="cmd">Tailor: python -m jobhunter tailor &lt;ID&gt; --pdf · Track: python -m jobhunter track add &lt;ID&gt;</p></div>
<h2>Search on sites without an API</h2><div class="card" id="links"></div>
<div id="tip"></div>
<script>
const D=/*DATA*/null;
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
document.getElementById("gen").textContent="Generated "+D.generated;
document.getElementById("kpis").innerHTML=Object.entries(D.kpis).map(([l,v])=>`<div class="card kpi"><div class="v">${esc(v)}</div><div class="l">${esc(l)}</div></div>`).join("");
const max=Math.max(1,...D.weeks.map(w=>w.n)),tip=document.getElementById("tip");
document.getElementById("chart").innerHTML=D.weeks.map(w=>`<div class="bar" data-t="Week of ${w.week}: ${w.n} application${w.n==1?"":"s"}"><i style="height:${100*w.n/max}%"></i><span>${w.week.slice(5)}</span></div>`).join("");
document.querySelectorAll(".bar").forEach(b=>{b.onmousemove=e=>{tip.textContent=b.dataset.t;tip.style.display="block";tip.style.left=e.clientX+12+"px";tip.style.top=e.clientY-28+"px"};b.onmouseleave=()=>tip.style.display="none"});
const fs=document.getElementById("fs");Object.entries(D.status_label).forEach(([k,v])=>fs.insertAdjacentHTML("beforeend",`<option value="${k}">${v}</option>`));
let sortK="date_applied",sortDir=-1;
function render(){const q=document.getElementById("q").value.toLowerCase(),s=fs.value;
 const rows=D.apps.filter(a=>(!s||a.status===s)&&(!q||(a.title+" "+a.company+" "+a.description+" "+a.notes).toLowerCase().includes(q)))
  .sort((a,b)=>(a[sortK]>b[sortK]?1:a[sortK]<b[sortK]?-1:0)*sortDir);
 document.getElementById("rows").innerHTML=rows.map(a=>`<tr><td class="num">${a.id}</td><td>${esc(a.date_applied||"–")}</td>
 <td>${a.url?`<a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.title)}</a>`:esc(a.title)}${a.notes?`<div class="muted">${esc(a.notes)}</div>`:""}</td>
 <td>${esc(a.company)}<div class="muted">${esc(a.location)}</div></td><td><span class="st ${a.status}">${esc(D.status_label[a.status]||a.status)}</span><div class="muted">${esc(a.status_date)}</div></td>
 <td class="num">${Math.round(a.score)}</td><td><details><summary>Show JD</summary><div class="jd">${esc(a.description)}</div></details></td></tr>`).join("")||`<tr><td colspan="7" class="muted">No applications yet.</td></tr>`;}
document.querySelectorAll("th[data-k]").forEach(th=>th.onclick=()=>{const k=th.dataset.k;sortDir=k===sortK?-sortDir:1;sortK=k;render()});
document.getElementById("q").oninput=render;fs.onchange=render;render();
document.getElementById("top").innerHTML=D.top.map(j=>`<tr><td class="cmd">${j.uid}</td><td class="num">${Math.round(j.score)}</td>
 <td>${j.url?`<a href="${esc(j.url)}" target="_blank" rel="noopener">${esc(j.title)}</a>`:esc(j.title)}</td><td>${esc(j.company)}</td><td>${esc(j.location)}</td><td>${esc(j.job_type)}</td>
 <td class="muted">${esc(j.missing.slice(0,6).join(", "))}${j.flags.length?" · ⚠ "+esc(j.flags.join("; ")):""}</td></tr>`).join("")||`<tr><td colspan="7" class="muted">Run: python -m jobhunter search</td></tr>`;
document.getElementById("links").innerHTML=D.links.map(l=>`<div class="links"><b>${esc(l.q)}</b> · ${esc(l.loc)}: ${Object.entries(l.links).map(([n,u])=>`<a href="${esc(u)}" target="_blank" rel="noopener">${esc(n)}</a>`).join("")}</div>`).join("");
</script></main></body></html>
"""
