"""Render the Jinja-LaTeX template and compile it to PDF."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import jinja2

_LATEX_ESCAPES = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
    "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}
_ESC_RE = re.compile("|".join(re.escape(k) for k in _LATEX_ESCAPES))


def latex_escape(value) -> str:
    return _ESC_RE.sub(lambda m: _LATEX_ESCAPES[m.group()], "" if value is None else str(value))


def make_env(template_dir: Path) -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(template_dir)),
        block_start_string=r"\BLOCK{", block_end_string="}",
        variable_start_string=r"\VAR{", variable_end_string="}",
        comment_start_string=r"\#{", comment_end_string="}",
        line_comment_prefix="%%",
        trim_blocks=True, lstrip_blocks=True, autoescape=False,
        undefined=jinja2.ChainableUndefined,  # missing optional fields render as empty
    )
    env.filters["e"] = latex_escape
    return env


def render(template_path: Path, cv: dict, keywords: list[str]) -> str:
    env = make_env(template_path.parent)
    return env.get_template(template_path.name).render(cv=cv, keywords=keywords)


def compile_pdf(tex_path: Path) -> Path:
    """Compile with latexmk / tectonic / pdflatex, whichever is installed."""
    tex_path = tex_path.resolve()
    cwd = tex_path.parent
    if shutil.which("latexmk"):
        cmd = ["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error", tex_path.name]
    elif shutil.which("tectonic"):
        cmd = ["tectonic", tex_path.name]
    elif shutil.which("pdflatex"):
        cmd = ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", tex_path.name]
    else:
        raise RuntimeError("No LaTeX engine found. Install TeX Live (latexmk) or tectonic — see README.")
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    pdf = tex_path.with_suffix(".pdf")
    if proc.returncode != 0 or not pdf.exists():
        log = (proc.stdout + proc.stderr)[-3000:]
        raise RuntimeError(f"LaTeX compilation failed:\n{log}")
    if shutil.which("latexmk"):
        subprocess.run(["latexmk", "-c", tex_path.name], cwd=cwd, capture_output=True)
    return pdf
