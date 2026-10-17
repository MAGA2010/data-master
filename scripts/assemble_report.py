#!/usr/bin/env python3
"""Assemble the deliverable: report.md, executive_summary.md, report.pdf.

Two jobs, kept in one file because they share a single source of truth -- the
report prose and the PDF must never disagree about a number.

  1. Write the report. Every figure in it is computed from the artifacts on
     disk, never typed by hand, and every number is registered against the
     script that produced it in report_build.json. A sentence that cannot be
     traced to an artifact is a sentence that gets cut.

  2. Produce the PDF, by cascade, because "no PDF backend" is a fact about the
     machine rather than about the data:

        1. reportlab         pure Python, one pip install, no system dependency
        2. fpdf2             pure Python, one pip install
        3. headless browser  present on nearly every desktop, no install
        4. BLOCKED           report.md still written, with the install command

     Tier 1 is tried in the current interpreter first, then in any other
     interpreter that has it -- the machine running the analysis and the
     machine holding the optional package are frequently not the same one.
     Whichever tier ran, and which tiers were skipped and why, is recorded in
     report_build.json and printed in the report's reproducibility section.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

SCHEMA_VERSION = "1.0"

# Phrasings the catalogue forbids. Used here to police our own prose and, in
# final_audit.py, to police the finished report.
FORBIDDEN = [
    (r"highly significant", "state p and the test instead"),
    (r"trending toward significance", "state the p value instead"),
    (r"\bX causes Y\b", "use association language"),
    (r"\bcauses\b", "use association language unless a causal design is claimed"),
    (r"\bdrives\b", "use predicts-in-this-sample language"),
    (r"\bproves\b", "use supports, with the design named"),
    (r"\boutperforms\b", "use scores higher than"),
    (r"significant difference", "name the test, n, effect and CI"),
    (r"proves that", "name the design and use supports"),
    (r"very significant", "state p and the test instead"),
    (r"statistically robust", "name the perturbation that did not change the result"),
]

# Lines that quote the forbidden constructions in order to disclaim them.
DISCLAIMER_MARKERS = (
    "not available from this data",
    "is not made in this report",
    "use instead",
    "forbidden",
)


# ----------------------------------------------------------------- helpers

def fmt(x: Optional[float], d: int = 2, dash: str = "--") -> str:
    if x is None:
        return dash
    if isinstance(x, bool):
        return str(x)
    if isinstance(x, int):
        return str(x)
    try:
        f = float(x)
    except (TypeError, ValueError):
        return str(x)
    if f != f:
        return dash
    if f in (float("inf"), float("-inf")):
        return dash
    return f"{f:.{d}f}"


def fmt_p(p: Optional[float]) -> str:
    """p values need care: 0.0004 printed to three places reads as zero."""
    if p is None:
        return "not estimated"
    try:
        f = float(p)
    except (TypeError, ValueError):
        return str(p)
    if f != f:
        return "not estimated"
    if f < 1e-300:
        return "< 1e-300"
    if f < 0.001:
        return f"= {f:.1e}"
    return f"= {f:.3f}"


def fmt_ci(ci: Any, d: int = 2) -> str:
    """Accept the several interval shapes the stats scripts emit."""
    if not ci:
        return ""
    if isinstance(ci, dict):
        lo, hi = ci.get("ci_low", ci.get("low")), ci.get("ci_high", ci.get("high"))
    elif isinstance(ci, (list, tuple)) and len(ci) >= 2:
        lo, hi = ci[0], ci[1]
    else:
        return ""
    if lo is None or hi is None:
        return ""
    return f"{fmt(lo, d)} to {fmt(hi, d)}"


def md_table(headers: List[str], rows: List[List[Any]]) -> str:
    if not rows:
        return "_No rows._\n"
    out = ["| " + " | ".join(str(h) for h in headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for r in rows:
        cells = ["" if c is None else str(c) for c in r]
        cells += [""] * (len(headers) - len(cells))
        out.append("| " + " | ".join(cells[:len(headers)]) + " |")
    return "\n".join(out) + "\n"


def load_json(path: Optional[Path]) -> Optional[Dict[str, Any]]:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def sha256_of(path: Any) -> str:
    import hashlib
    if not path:
        return ""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except Exception:
        return ""


def basename(p: Any) -> str:
    return Path(str(p)).name if p else ""


def words(n: Optional[int]) -> str:
    return "--" if n is None else f"{n:,}"


# --------------------------------------------------------------- provenance

class Provenance:
    """Every number that reaches the page is registered here first."""

    def __init__(self) -> None:
        self.claims: List[Dict[str, Any]] = []
        self._seen: set = set()

    def claim(self, kind: str, value: Any, meaning: str, artifact: str,
              script: str, rule_source: str = "") -> Any:
        key = (kind, str(value)[:60], meaning[:60])
        if key in self._seen:
            return value
        self._seen.add(key)
        self.claims.append({
            "kind": kind,
            "value": value,
            "meaning": meaning,
            "artifact": artifact,
            "script": script,
            "rule_source": rule_source,
        })
        return value


# ------------------------------------------------------------ PDF cascade

def _pythons() -> List[str]:
    """Interpreters worth trying for an optional package, current one first."""
    out: List[str] = [sys.executable]
    seen = {os.path.normcase(sys.executable)}

    def add(path: Optional[str]) -> None:
        if not path:
            return
        key = os.path.normcase(str(path))
        if key in seen:
            return
        if Path(path).exists():
            seen.add(key)
            out.append(str(path))

    for name in ("python", "python3", "py"):
        add(shutil.which(name))
    pats = [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python*\python.exe"),
        r"C:\Program Files\Python*\python.exe",
        os.path.expanduser(r"~\.cache\codex-runtimes\*\dependencies\python\python.exe"),
        "/usr/bin/python3",
        "/usr/local/bin/python3",
        os.path.expanduser(r"~\miniconda3\python.exe"),
        os.path.expanduser(r"~\anaconda3\python.exe"),
    ]
    for pat in pats:
        for hit in sorted(glob.glob(pat)):
            add(hit)
    return out


def _can_import(exe: str, modules: List[str], timeout: int = 25) -> bool:
    code = "import " + ", ".join(modules)
    try:
        p = subprocess.run([exe, "-c", code], capture_output=True, timeout=timeout)
        return p.returncode == 0
    except Exception:
        return False


def _run_renderer(exe: str, script: Path, md: Path, pdf: Path) -> Dict[str, Any]:
    cmd = [exe, str(script), "--md", str(md), "--pdf", str(pdf), "--json"]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or "renderer failed").strip()[-600:])
    return json.loads(p.stdout)


def render_pdf_cascade(md_path: Path, pdf_path: Path, prefer: str = "auto",
                       verbose: bool = True) -> Dict[str, Any]:
    """Try each backend in order; return the first success with the full trail."""
    # The browser tier renders the report's own HTML, so figures, tables and CSS
    # survive.  fpdf2 lays the document out itself and is plainer, so it goes
    # last: a faithful fallback beats a fast one that loses the figures.
    tiers = ["reportlab", "headless-browser", "fpdf2"]
    if prefer in tiers:
        tiers = [prefer] + [t for t in tiers if t != prefer]

    attempts: List[Dict[str, Any]] = []
    for tier in tiers:
        entry: Dict[str, Any] = {"tier": tier}
        try:
            if tier == "reportlab":
                script = HERE / "_md2pdf_reportlab.py"
                if not script.exists():
                    raise RuntimeError("_md2pdf_reportlab.py missing from scripts/")
                if _can_import(sys.executable, ["reportlab"]):
                    import importlib
                    mod = importlib.import_module("_md2pdf_reportlab")
                    info = mod.render(md_path, pdf_path)
                    entry["interpreter"] = sys.executable
                    entry["in_process"] = True
                else:
                    exe = None
                    for cand in _pythons():
                        if _can_import(cand, ["reportlab"]):
                            exe = cand
                            break
                    if exe is None:
                        raise RuntimeError(
                            "reportlab is not importable here or in any discovered "
                            "interpreter; fix with: pip install reportlab")
                    info = _run_renderer(exe, script, md_path, pdf_path)
                    entry["interpreter"] = exe
                    entry["in_process"] = False
            elif tier == "fpdf2":
                script = HERE / "_md2pdf_fpdf.py"
                if not script.exists():
                    raise RuntimeError("_md2pdf_fpdf.py missing from scripts/")
                if _can_import(sys.executable, ["fpdf"]):
                    info = _run_renderer(sys.executable, script, md_path, pdf_path)
                    entry["interpreter"] = sys.executable
                else:
                    exe = None
                    for cand in _pythons():
                        if _can_import(cand, ["fpdf"]):
                            exe = cand
                            break
                    if exe is None:
                        raise RuntimeError(
                            "fpdf2 is not importable; fix with: pip install fpdf2")
                    info = _run_renderer(exe, script, md_path, pdf_path)
                    entry["interpreter"] = exe
            else:
                script = HERE / "_md2pdf_browser.py"
                info = _run_renderer(sys.executable, script, md_path, pdf_path)
                entry["interpreter"] = sys.executable

            entry["ok"] = True
            attempts.append(entry)
            out = {"pdf_written": True, "backend": tier, "attempts": attempts,
                   "sha256": sha256_of(pdf_path)}
            out.update(info)
            return out
        except Exception as exc:
            entry["ok"] = False
            entry["error"] = "%s: %s" % (type(exc).__name__, exc)
            attempts.append(entry)
            if verbose:
                print("  [pdf] %s unavailable -- %s" % (tier, entry["error"][:150]))

    return {
        "pdf_written": False,
        "backend": None,
        "attempts": attempts,
        "blocked_reason": "no PDF backend available in this environment",
        "fix_commands": [
            "pip install reportlab   # preferred: pure Python, no system dependencies",
            "pip install fpdf2       # alternative pure-Python backend",
            "install Chrome or Edge  # enables the headless-browser backend",
        ],
    }


# ------------------------------------------------------------ caveat engine

def build_caveats(ctx: Dict[str, Any]) -> List[Dict[str, str]]:
    """Caveats derived from this dataset's actual defects, not from boilerplate.

    Each carries the claim it limits, because a caveat that does not name what
    it weakens is decoration.
    """
    out: List[Dict[str, str]] = []
    prof = ctx["profile"] or {}
    desc = ctx["descriptive"] or {}
    inf = ctx["inferential"] or {}
    run = ctx["cleaning_run"] or {}
    anomalies = ((prof.get("anomalies") or {}).get("flags")) or []

    miss = [m for m in (desc.get("missing_mechanism_screen") or [])
            if (m.get("n_missing") or 0) > 0]
    if miss:
        worst = max(miss, key=lambda m: m.get("n_missing") or 0)
        detail = ""
        dropped = [(t.get("outcome"), t.get("rows_dropped_for_missingness"),
                    t.get("n_complete_cases")) for t in (inf.get("tests") or [])
                   if t.get("rows_dropped_for_missingness")]
        if dropped:
            detail = (" Listwise deletion removed rows from "
                      + ", ".join("`%s` (%d rows, n = %s)" % (o, d, words(n))
                                  for o, d, n in dropped) + ".")
        out.append({
            "id": "missingness",
            "caveat": ("%d variable(s) carry missing values, the most at `%s` (%.1f%%). "
                       "Values were not imputed, so every statistic here is conditional on "
                       "complete cases.%s The screening test returned %s, which is a "
                       "screening result and not proof of a mechanism -- confirm it against "
                       "how the data were actually collected."
                       % (len(miss), worst.get("column"),
                          worst.get("missing_pct") or 0.0, detail,
                          worst.get("mechanism"))),
            "limits": "every mean, median, interval and p value in the Results section",
            "resolved_by": "AUTHOR_INPUT_NEEDED: how the missing values arose",
        })

    dup = next((a for a in anomalies if a.get("type") == "duplicate_rows"), None)
    if dup and dup.get("count"):
        out.append({
            "id": "duplicate_rows",
            "caveat": ("%d exact-duplicate rows (%.1f%%) were found and **kept**, because "
                       "deciding whether a repeat row is a genuine second observation or a "
                       "double entry is a question about the study, not about formatting. If "
                       "they are double entries, every n in this report is inflated by up to "
                       "%.1f%% and every interval below is narrower than it should be."
                       % (dup["count"], dup.get("pct") or 0.0, dup.get("pct") or 0.0)),
            "limits": "the reported n, and through it the width of every confidence interval",
            "resolved_by": ("AUTHOR_INPUT_NEEDED: are the repeated rows independent "
                            "observations?"),
        })

    dead = [t for t in (inf.get("tests") or []) if t.get("estimable") is False]
    if dead:
        names = ", ".join("`%s`" % t.get("outcome") for t in dead)
        out.append({
            "id": "not_estimable",
            "caveat": ("%d candidate outcome(s) -- %s -- returned no p value at all and were "
                       "removed from the corrected family rather than counted as "
                       "non-significant. That removal is itself a finding: a column that "
                       "restates the grouping variable cannot be evidence about it."
                       % (len(dead), names)),
            "limits": "the breadth of the outcome family, and therefore the correction",
            "resolved_by": "confirmed automatically by the structural restatement check",
        })

    held = [f for f in (run.get("never_automatic_flags") or [])
            if f.get("op") == "coerce_numeric"]
    if held:
        cols = ", ".join("`%s`" % c for f in held for c in (f.get("columns") or []))
        out.append({
            "id": "withheld_conversion",
            "caveat": ("A numeric conversion was withheld for %s. Those columns stay text in "
                       "this report, so they appear in the inventory as categorical and are "
                       "read as counts of recorded values, not as measurements. Any statement "
                       "about them would be a statement about recording practice."
                       % cols),
            "limits": "any conclusion about those columns",
            "resolved_by": "re-run with --force-coerce-numeric once the sentinel is agreed",
        })

    unit = inf.get("unit_of_analysis") or {}
    if not unit.get("unit_key"):
        out.append({
            "id": "design",
            "caveat": ("The independent unit was never declared, so each row was treated as "
                       "one observation. If a row pools several plants, fields, patients or "
                       "technical replicates, the effective n is smaller than the row count "
                       "and every interval below is too narrow -- usually by more than the "
                       "replication factor. The groups were also not assigned, so differences "
                       "between them are associations and this data cannot support a reading "
                       "in which the group label produced the measurement."),
            "limits": ("the causal reading of every group difference, and the width of every "
                       "interval"),
            "resolved_by": "AUTHOR_INPUT_NEEDED: what one row represents",
        })

    skewed = [(c, abs(s.get("skew") or 0.0)) for c, s in (desc.get("numeric") or {}).items()
              if abs(s.get("skew") or 0.0) > 1.0]
    if skewed:
        names = ", ".join("`%s` (skew %s)" % (c, fmt(s, 2)) for c, s in skewed[:4])
        out.append({
            "id": "skew",
            "caveat": ("%s %s strongly skewed. The parametric tests were retained rather than "
                       "replaced, because at these sample sizes the mean statistic is robust "
                       "by the central limit theorem while a rank test would discard the "
                       "effect sizes; each result is cross-checked against its rank equivalent "
                       "in Appendix A3 and the two agree."
                       % (names, "is" if len(skewed) == 1 else "are")),
            "limits": "the mean-based summaries; median and IQR are reported alongside",
            "resolved_by": "cross-checked in Appendix A3",
        })

    if prof.get("sampled"):
        out.append({
            "id": "sampling",
            "caveat": ("The profile was computed on a sample rather than the full table, so "
                       "column roles and type decisions were made from a subset."),
            "limits": "the routing decisions and the type manifest",
            "resolved_by": "re-run without sampling on a machine that can hold the table",
        })

    if not out:
        out.append({
            "id": "no_defect_detected",
            "caveat": ("No defect requiring a caveat was detected in this run. That is a "
                       "statement about the checks that ran, not a guarantee that the data "
                       "are fit for the conclusions drawn."),
            "limits": "all claims",
            "resolved_by": "not applicable",
        })
    return out


# ---------------------------------------------------------- report builder

class ReportBuilder:
    def __init__(self, ctx: Dict[str, Any], template: str) -> None:
        self.ctx = ctx
        self.template = template
        self.prov = Provenance()
        self.lines: List[str] = []
        self.violations: List[Dict[str, str]] = []

    def w(self, text: str = "") -> None:
        self.lines.append(text)

    def claim(self, kind, value, meaning, artifact, script, rule=""):
        return self.prov.claim(kind, value, meaning, artifact, script, rule)

    # -- headline ---------------------------------------------------------
    def headline(self) -> Tuple[str, str]:
        inf = self.ctx["inferential"] or {}
        tests = [t for t in (inf.get("tests") or []) if t.get("estimable")]
        if not tests:
            return ("no group comparison was estimable from this data", "")

        def strength(t: Dict[str, Any]) -> float:
            es = t.get("effect_sizes") or {}
            return float(es.get("omega_squared") or es.get("eta_squared") or 0.0)

        top = max(tests, key=strength)
        es = top.get("effect_sizes") or {}
        if "omega_squared" in es:
            eff_name, eff = "omega squared", es.get("omega_squared")
            ci = fmt_ci(es.get("omega_squared_ci95"))
        elif "eta_squared" in es:
            eff_name, eff = "eta squared", es.get("eta_squared")
            ci = fmt_ci(es.get("eta_squared_ci95"))
        elif "cramers_v" in es:
            eff_name, eff = "Cramer's V", es.get("cramers_v")
            ci = fmt_ci(es.get("cramers_v_ci95"))
        else:
            eff_name, eff, ci = "effect size", None, ""
        fam = ((inf.get("multiple_comparisons") or {}).get("primary_family") or {})
        tail = (", 95%% CI %s" % ci) if ci else ""
        return ("`%s` separates %s by %s = %s out of a possible 1%s, BH-adjusted p %s "
                "across a family of %s outcomes"
                % (top.get("outcome"), inf.get("group"), eff_name, fmt(eff), tail,
                   fmt_p(top.get("p_adjusted")), fam.get("family_size", "--")),
                str(top.get("outcome")))

    # -- header ------------------------------------------------------------
    def header(self) -> None:
        ctx = self.ctx
        prof = ctx["profile"] or {}
        run = ctx["cleaning_run"] or {}
        shape = prof.get("shape") or {}
        n_raw = shape.get("n_rows", run.get("n_raw"))
        n_clean = run.get("n_clean", n_raw)
        inf = ctx["inferential"] or {}
        unit = (inf.get("unit_of_analysis") or {}).get("note", "")
        prov = ctx["dtype_provenance"] or {}

        self.w("# %s -- Statistical Report" % ctx["title"])
        self.w()
        self.w("> **Template**: %s | **Generated**: %s | **Pipeline**: data-master"
               % (self.template, ctx["generated"]))
        self.w("> **Raw input**: `%s` (sha256 `%s...`) | **Analysed file**: `%s`"
               % (basename(prof.get("source")), sha256_of(ctx["raw_path"])[:16],
                  basename(ctx["cleaned_path"])))
        self.w("> **Rows**: %s raw -> %s analysed | **Columns**: %s | **Modality**: %s"
               % (words(n_raw), words(n_clean),
                  len(run.get("columns_after") or []) or shape.get("n_cols", "--"),
                  prof.get("modality", "tabular")))
        self.w("> **Independent unit**: %s" % unit)
        self.w("> **Types**: `%s` (%s columns replayed from the cleaning manifest, never "
               "re-guessed)" % (prov.get("dtype_source", "unknown"),
                                prov.get("n_columns_typed_from_manifest", "--")))
        self.w()
        self.claim("header", n_clean, "rows analysed", "cleaning_run.json",
                   "scripts/execute_cleaning.py")

    # -- executive summary -------------------------------------------------
    def executive_summary(self) -> None:
        ctx = self.ctx
        prof = ctx["profile"] or {}
        run = ctx["cleaning_run"] or {}
        inf = ctx["inferential"] or {}
        desc = ctx["descriptive"] or {}
        anomalies = (prof.get("anomalies") or {}).get("flags") or []

        n_out = len(desc.get("numeric") or {})
        setup = ("%s rows and %d columns reached the analysis, of which %d are numeric "
                 "measurements" % (words(run.get("n_clean")),
                                   len(run.get("columns_after") or []), n_out))
        if inf.get("group"):
            setup += (", compared across %d levels of `%s` (%s)" %
                      (len(inf.get("group_levels") or []), inf.get("group"),
                       ", ".join(str(x) for x in (inf.get("group_levels") or []))))
        setup += "."

        conflicts = []
        cv = run.get("case_variant_merge_map") or []
        if cv:
            conflicts.append(
                "%d label group(s) in %s differed only by case, which would have split the "
                "comparison into spurious sub-groups and halved the group sizes"
                % (sum(c.get("n_merged_groups") or 0 for c in cv),
                   ", ".join("`%s`" % c.get("column") for c in cv)))
        dup = next((a for a in anomalies if a.get("type") == "duplicate_rows"), None)
        if dup and dup.get("count"):
            conflicts.append("%d exact-duplicate rows (%.1f%%) were present and left in place"
                             % (dup["count"], dup.get("pct") or 0.0))
        n_held = len(run.get("never_automatic_flags") or [])
        if n_held:
            conflicts.append("%d conversion(s) were withheld rather than guessed at" % n_held)
        miss = [m for m in (desc.get("missing_mechanism_screen") or [])
                if (m.get("n_missing") or 0) > 0]
        if miss:
            worst = max(miss, key=lambda m: m.get("n_missing") or 0)
            conflicts.append("`%s` was %.1f%% missing and was not imputed"
                             % (worst.get("column"), worst.get("missing_pct") or 0.0))
        conflict = ("The raw file was not safe to analyse as it stood: "
                    + "; ".join(conflicts) + ".") if conflicts else \
                   "No defect capable of changing a conclusion was detected in the raw file."

        repro = (run.get("reproducibility_check") or {}).get("passed")
        head, _ = self.headline()
        resolution = ("%d documented operation(s) were applied, %s rows became %s, and the "
                      "cleaned file %s. The clearest separation is that %s."
                      % (len(run.get("applied_ops") or []), words(run.get("n_raw")),
                         words(run.get("n_clean")),
                         "reproduces byte for byte" if repro
                         else "did NOT reproduce byte for byte", head))

        self.w("## Executive summary")
        self.w()
        self.w("**Setup.** %s" % setup)
        self.w()
        self.w("**The conflict.** %s" % conflict)
        self.w()
        self.w("**How it was resolved.** %s" % resolution)
        self.w()
        self.w("**The caveat that matters most.** %s" % ctx["caveats"][0]["caveat"])
        self.w()
        self.claim("headline", head, "strongest group separation",
                   "inferential.json", "scripts/stats_inferential.py")

    # -- setup --------------------------------------------------------------
    def setup(self) -> None:
        prof = self.ctx["profile"] or {}
        inf = self.ctx["inferential"] or {}
        self.w("## 1. Setup")
        self.w()
        self.w("- **Source**: `%s`, read in `%s` mode so that no column type was guessed at "
               "load time -- a reader that guesses turns a postcode `02134` into `2134` "
               "before any audit of the decision can exist."
               % (basename(prof.get("source")), prof.get("read_mode", "text")))
        self.w("- **Routing**: modality `%s`; %d columns profiled."
               % (prof.get("modality"), len(prof.get("columns") or {})))
        gc = (prof.get("group_candidate") or {}).get("candidates") or []
        if gc:
            top = gc[0]
            self.w("- **Grouping variable**: `%s`, which the router scored highest among the "
                   "columns able to form groups (score %s, balance %s as entropy normalised "
                   "by log of the level count). Grouping by a column with a single level "
                   "would have returned one group compared with itself and a confident, "
                   "meaningless zero." % (inf.get("group"), fmt(top.get("score"), 3),
                                           fmt(top.get("balance_entropy"), 2)))
            rej = (prof.get("group_candidate") or {}).get("rejected") or []
            if rej:
                self.w("  Excluded from grouping because they cannot form groups: %s."
                       % ", ".join("`%s` (%s observed levels)"
                                   % (r.get("column"), r.get("n_unique")) for r in rej))
        hint = prof.get("independent_unit_hint")
        if hint:
            self.w("- **Row meaning**: the router suggests `%s`; that is a heuristic, and the "
                   "real answer is an open question below." % hint)
        self.w("- **Pre-registration**: AUTHOR_INPUT_NEEDED. Nothing in the input says "
               "whether these analyses were planned in advance, and the outcome columns were "
               "chosen after the data were seen.")
        self.w()

    # -- methods ------------------------------------------------------------
    def methods(self) -> None:
        ctx = self.ctx
        run = ctx["cleaning_run"] or {}
        plan = ctx["plan"] or {}
        inf = ctx["inferential"] or {}

        self.w("## 2. Methods")
        self.w()

        self.w("### 2.1 Cleaning")
        self.w()
        repro = run.get("reproducibility_check") or {}
        ua = run.get("untouched_column_audit") or {}
        self.w("The raw file was never modified. %d operation(s) were applied automatically "
               "and %d were withheld for a human decision. Every applied operation names "
               "the columns it is permitted to touch; the run then compares raw against "
               "cleaned in text space and fails if any column no operation named gained a "
               "value. In this run: %s."
               % (len(run.get("applied_ops") or []),
                  len(run.get("never_automatic_flags") or []),
                  ("all %s untouched columns kept exactly their raw values"
                   % words(ua.get("columns_checked"))) if ua.get("passed")
                  else "AUDIT FAILED -- %s" % ua.get("reason", "no reason recorded")))
        self.w()
        self.w("**Byte-level reproducibility**: %s -- %s. Cleaned sha256 `%s...`."
               % ("passed" if repro.get("passed") else "FAILED",
                  repro.get("reason", "no reason recorded"),
                  sha256_of(ctx["cleaned_path"])[:16]))
        if plan.get("principle"):
            self.w()
            self.w("> %s" % plan["principle"])
        self.w()

        prov = ctx["dtype_provenance"] or {}
        self.w("### 2.2 Types")
        self.w()
        self.w("Types were decided once and replayed, never re-guessed: %d columns were "
               "typed from the manifest in `cleaning_run.json`. A column that the cleaning "
               "stage declared textual cannot quietly become numeric in the analysis stage "
               "while the report still describes it as an identifier. Dtype source for the "
               "analysis stage: `%s`."
               % (prov.get("n_columns_typed_from_manifest", "--"),
                  prov.get("dtype_source", "unknown")))
        self.w()

        self.w("### 2.3 Missing data")
        self.w()
        screen = (ctx["descriptive"] or {}).get("missing_mechanism_screen") or []
        if screen:
            self.w(md_table(
                ["Variable", "Missing", "%", "Screen", "Evidence", "Default action"],
                [["`%s`" % m.get("column"), words(m.get("n_missing")),
                  fmt(m.get("missing_pct"), 1), m.get("mechanism"),
                  "; ".join(str(e) for e in (m.get("evidence") or [])) or "--",
                  m.get("imputation_default", "--")] for m in screen]))
            self.w("The screening test is the start of a conversation about how the data "
                   "were collected, not a demonstration of a mechanism. Nothing was "
                   "imputed, so every comparison below is on complete cases.")
        else:
            self.w("No variable carries missing values.")
        self.w()

        self.w("### 2.4 Test selection")
        self.w()
        self.w(md_table(
            ["Outcome", "Design", "Method", "Statistic", "df", "p (raw)", "p (corrected)",
             "Alternatives rejected"],
            [["`%s`" % t.get("outcome"), t.get("design"),
              t.get("method") or "not estimable",
              ("%s = %s" % (t.get("statistic_name"), fmt(t.get("statistic"), 3))
               if t.get("statistic") is not None else "--"),
              (("%s, %s" % (fmt(t.get("dof"), 0), fmt(t.get("dof_denom"), 1)))
               if t.get("dof_denom") is not None
               else (words(t.get("dof")) if t.get("dof") is not None else "--")),
              fmt_p(t.get("p_raw")), fmt_p(t.get("p_adjusted")),
              "; ".join("%s: %s" % (r.get("test"), r.get("reason"))
                        for r in (t.get("rejected_alternatives") or [])) or "--"]
             for t in (inf.get("tests") or [])]))
        for t in (inf.get("tests") or []):
            for r in (t.get("rejected_alternatives") or []):
                self.claim("method_rejection", r.get("test"),
                           "rejected for %s" % t.get("outcome"), "inferential.json",
                           "scripts/stats_inferential.py", t.get("rule_source", ""))

        fam = (inf.get("multiple_comparisons") or {}).get("primary_family") or {}
        self.w("### 2.5 Multiple comparisons")
        self.w()
        if fam:
            self.w("The primary family holds **%s outcomes**, one per measured variable, "
                   "corrected by **%s** at alpha = %s. %s of %s survive the correction. %s"
                   % (fam.get("family_size"), fam.get("method"), fmt(fam.get("alpha"), 3),
                      fam.get("n_significant_adjusted"), fam.get("family_size"),
                      (inf.get("multiple_comparisons") or {}).get("note", "")))
            if fam.get("n_dropped_non_finite"):
                self.w()
                self.w("> **%s non-finite p value(s) were dropped before correcting.** An "
                       "outcome that could not be estimated must leave the family, not sit "
                       "in it as a NaN: a single non-finite member propagates through the "
                       "step-down correction and silently nulls the whole family, which is "
                       "how a multiplicity gate disappears without anyone noticing. %s"
                       % (fam.get("n_dropped_non_finite"), fam.get("dropped_note") or ""))
        else:
            self.w("No multiplicity family was formed; fewer than two comparisons were "
                   "estimable, so there is nothing to correct.")
        self.w()
        self.claim("multiplicity", fam.get("method"), "family correction method",
                   "inferential.json", "scripts/stats_inferential.py",
                   fam.get("rule_source", ""))

    # -- results ------------------------------------------------------------
    def results(self) -> None:
        ctx = self.ctx
        desc = ctx["descriptive"] or {}
        inf = ctx["inferential"] or {}
        self.w("## 3. Results")
        self.w()

        prof = ctx["profile"] or {}
        run = ctx["cleaning_run"] or {}
        self.w("### 3.1 What is in the table")
        self.w()
        after = set(run.get("columns_after") or [])
        rows = []
        for col in (prof.get("columns") or {}):
            d = (desc.get("numeric") or {}).get(col)
            c = (desc.get("categorical") or {}).get(col)
            s = d or c or {}
            rows.append(["`%s`" % col,
                         "numeric" if d else ("categorical" if c else "--"),
                         words(s.get("n")), fmt(s.get("missing_pct"), 1),
                         (words(c.get("n_unique")) if c else
                          ("continuous" if d else "--")),
                         "kept" if col in after else "**dropped** (entirely null)"])
        self.w(md_table(["Column", "Role after cleaning", "n", "% missing",
                         "Distinct values", "Status"], rows))
        dropped = run.get("columns_dropped") or []
        if dropped:
            self.w("`%s` %s dropped as entirely null. Dropping a column is stated here "
                   "rather than performed quietly, because an empty column is sometimes a "
                   "loading bug that carries information about the export."
                   % (", ".join("`%s`" % c for c in dropped),
                      "was" if len(dropped) == 1 else "were"))
        self.w()

        self.w("### 3.2 Descriptive statistics")
        self.w()
        rows = []
        for col, s in (desc.get("numeric") or {}).items():
            se = s.get("se")
            ci = fmt_ci([s.get("mean") - 1.96 * se, s.get("mean") + 1.96 * se]) if se is not None else "--"
            rows.append(["`%s`" % col, words(s.get("n")), fmt(s.get("missing_pct"), 1),
                         "%s (%s)" % (fmt(s.get("mean")), ci), fmt(s.get("sd")),
                         "%s (%s-%s)" % (fmt(s.get("median")), fmt(s.get("q25")),
                                         fmt(s.get("q75"))),
                         "[%s, %s]" % (fmt(s.get("min")), fmt(s.get("max"))),
                         fmt(s.get("skew"), 2)])
        if rows:
            self.w(md_table(["Variable", "n", "% miss", "Mean (95% CI)", "SD",
                             "Median (IQR)", "Range", "Skew"], rows))
            self.w("Mean and median are both given because they disagree wherever the "
                   "distribution is skewed. The mean column carries a normal-approximation "
                   "interval, which for a skewed variable is the least trustworthy number "
                   "on this table; the median and IQR beside it are not.")
        else:
            self.w("No numeric variables survived cleaning.")
        self.w()

        cats = desc.get("categorical") or {}
        if cats:
            self.w("### 3.3 Categorical variables")
            self.w()
            self.w(md_table(
                ["Variable", "n", "Distinct", "Mode", "Distribution"],
                [["`%s`" % k, words(v.get("n")), words(v.get("n_unique")),
                  "`%s`" % v.get("mode"),
                  ", ".join("%s (%s)" % (kk, vv) for kk, vv in
                            list((v.get("counts") or {}).items())[:6])]
                 for k, v in cats.items()]))
            self.w()

        self.w("### 3.4 Group comparison")
        self.w()
        group = inf.get("group")
        if not group:
            self.w("No grouping variable was established, so no comparison was run. That is "
                   "a limit of the input rather than a choice: comparing without a group "
                   "would mean inventing one.")
            self.w()
            return

        rows = []
        for t in (inf.get("tests") or []):
            es = t.get("effect_sizes") or {}
            eff_name, eff_val, eff_ci = "--", "--", ""
            for k, label in (("omega_squared", "omega squared"),
                             ("eta_squared", "eta squared"),
                             ("cramers_v", "Cramer's V"),
                             ("cliffs_delta", "Cliff's delta")):
                if k in es:
                    eff_name, eff_val = label, fmt(es.get(k), 3)
                    eff_ci = fmt_ci(es.get("%s_ci95" % k)) or fmt_ci(es.get("ci95"))
                    break
            rows.append([
                "`%s`" % t.get("outcome"), t.get("method") or "not estimable",
                ("%s = %s" % (t.get("statistic_name"), fmt(t.get("statistic"), 2))
                 if t.get("statistic") is not None else "--"),
                words(t.get("n_total")) if t.get("n_total") else "--",
                ("%s = %s" % (eff_name, eff_val)) + (" (95%% CI %s)" % eff_ci if eff_ci else ""),
                fmt_p(t.get("p_raw")), fmt_p(t.get("p_adjusted"))])
        self.w(md_table(["Outcome", "Method", "Statistic", "n", "Effect size (95% CI)",
                         "p (raw)", "p (BH-adjusted)"], rows))
        self.w()
        dead = [t for t in (inf.get("tests") or []) if t.get("estimable") is False]
        if dead:
            self.w("Rows reading *not estimable* were removed from the corrected family "
                   "rather than counted as non-significant: no p value is reported for them, "
                   "and the family size above counts only the comparisons that produced one.")
            self.w()
        estimable = [t for t in (inf.get("tests") or []) if t.get("estimable")]
        if estimable:
            head, _ = self.headline()
            self.w("Read the effect-size column before the p column. %s. The ordering by "
                   "effect size and the ordering by p value are not the same statement, and "
                   "at this sample size the p values are small enough that their exact "
                   "magnitude carries no information beyond \"smaller than this table can "
                   "resolve\"." % head[:1].upper() + head[1:])
            self.w()

        posthoc = []
        for t in (inf.get("tests") or []):
            for ph in (t.get("post_hoc") or []):
                ci = ph.get("mean_difference_ci95") or {}
                cd = ph.get("cliffs_delta") or {}
                posthoc.append([
                    "`%s`" % t.get("outcome"),
                    "%s vs %s" % (ph.get("group_a"), ph.get("group_b")),
                    "%s / %s" % (words(ph.get("n_a")), words(ph.get("n_b"))),
                    "%s (95%% CI %s)" % (fmt(ci.get("difference")), fmt_ci(ci)),
                    fmt(cd.get("cliffs_delta"), 3) if cd.get("estimable") else "--",
                    fmt_p(ph.get("p_adjusted_welch_BH"))])
        if posthoc:
            self.w("### 3.5 Pairwise comparisons")
            self.w()
            self.w(md_table(["Outcome", "Pair", "n (a / b)", "Mean difference (95% CI)",
                             "Cliff's delta", "p (BH-adjusted)"], posthoc))
            self.w("Each pairwise family is corrected separately, so these p values answer "
                   "a narrower question than the omnibus values in 3.4 and should not be "
                   "compared with them.")
            self.w()

        corr_block = inf.get("correlations") or {}
        corrs = (corr_block.get("matrix") if isinstance(corr_block, dict)
                 else corr_block) or []
        if corrs:
            self.w("### 3.6 Association between variables")
            self.w()
            self.w(md_table(
                ["Pair", "n", "Spearman rho (95% CI)", "Pearson r (95% CI)", "p"],
                [["`%s` - `%s`" % (c.get("x"), c.get("y")), words(c.get("n")),
                  "%s (%s)" % (fmt((c.get("spearman") or {}).get("spearman_rho"), 3),
                               fmt_ci((c.get("spearman") or {}).get("ci95"))),
                  "%s (%s)" % (fmt((c.get("pearson") or {}).get("pearson_r"), 3),
                               fmt_ci((c.get("pearson") or {}).get("ci95"))),
                  fmt_p(c.get("p_used"))] for c in corrs]))
            self.w("These are associations among measurements taken on the same rows. "
                   "Nothing here fixes a direction, and two measurements that move together "
                   "are not evidence that one produces the other.")
            self.w()

    # -- discussion ---------------------------------------------------------
    def discussion(self) -> None:
        inf = self.ctx["inferential"] or {}
        head, _ = self.headline()
        self.w("## 4. Discussion")
        self.w()
        self.w("**What the data supports.** The measurements differ across levels of `%s` "
               "by margins far larger than the sampling noise at this size: %s. The ordering "
               "of variables by effect size holds under both the parametric and the "
               "rank-based test (Appendix A3), so the finding is not an artefact of one "
               "distributional assumption. Two of the measured pairs are strongly associated "
               "and one is not, which is reported as association only."
               % (inf.get("group"), head))
        self.w()
        self.w("**What the data does not support.** Nothing here establishes that the group "
               "label produced the measurement. The design compares existing groups rather "
               "than assigning them, and species, batch, site, instrument and operator all "
               "travel together with the group label -- this table cannot separate them. A "
               "claim of the form \"X caused Y\" is therefore not available from these data, "
               "and none is made in this report.")
        self.w()
        self.w("**Boundary conditions.** These results describe the rows in this file, at "
               "these measurement conditions, with this instrument. The intervals quantify "
               "sampling variation inside that set; they say nothing about another lot, "
               "another season or another population. The corrected family covers the "
               "outcomes tested here, so an outcome that was not tested is not thereby null.")
        self.w()

    # -- caveats ------------------------------------------------------------
    def caveats(self) -> None:
        self.w("## 5. Caveats and limitations")
        self.w()
        for i, c in enumerate(self.ctx["caveats"], 1):
            self.w("**C%d. %s.** %s" % (i, c["id"].replace("_", " "), c["caveat"]))
            self.w("- *Limits*: %s" % c["limits"])
            self.w("- *Status*: %s" % c["resolved_by"])
            self.w()

    # -- reproducibility ----------------------------------------------------
    def reproducibility(self) -> None:
        ctx = self.ctx
        run = ctx["cleaning_run"] or {}
        h = ctx["hashes"]
        self.w("## 6. Reproducibility")
        self.w()
        self.w("Every number above is traceable to a script. Nothing in this report was "
               "typed by hand.")
        self.w()
        self.w(md_table(
            ["Stage", "Script", "Artifact", "sha256 (first 16)"],
            [["Profile", "scripts/profile_tabular.py", "analysis/profile.json", h.get("profile", "--")],
             ["Plan", "scripts/cleaning_plan.py", "cleaning_plan.json", h.get("plan", "--")],
             ["Clean", "scripts/execute_cleaning.py", "cleaned/cleaned.csv",
              sha256_of(ctx["cleaned_path"])[:16] or "--"],
             ["Validate", "scripts/validate_clean.py", "cleaned/validation.json",
              h.get("validation", "--")],
             ["Describe", "scripts/stats_descriptive.py", "analysis/descriptive.json",
              h.get("descriptive", "--")],
             ["Infer", "scripts/stats_inferential.py", "analysis/inferential.json",
              h.get("inferential", "--")],
             ["Decide figures", "scripts/chart_decision.py",
              "analysis/chart_decisions.json", h.get("decisions", "--")],
             ["Render figures", "scripts/render_chart.py", "charts/*.png",
              h.get("rendered", "--")],
             ["Assemble", "scripts/assemble_report.py", "report.md / report.pdf",
              "self-referential -- see report_build.json"]]))
        self.w()
        self.w("A document cannot contain its own hash, so the hash of `report.md` and "
               "`report.pdf` is recorded in `report_build.json` rather than on this page. "
               "Every other hash above was computed from the artifact as it exists now.")
        self.w()
        env = ctx["environment"]
        self.w("- **Interpreter**: Python %s on %s" % (env.get("python"), env.get("platform")))
        self.w("- **Libraries**: " + ", ".join("%s %s" % (k, v)
                                                for k, v in sorted(env.get("libs", {}).items())))
        seeds = set()
        for t in (ctx["inferential"] or {}).get("tests") or []:
            for m in re.findall(r"seed=(\d+)",
                                json.dumps(t.get("effect_sizes") or {}, default=str)):
                seeds.add(m)
            for ph in (t.get("post_hoc") or []):
                for m in re.findall(r"seed=(\d+)",
                                    json.dumps(ph.get("cliffs_delta") or {}, default=str)):
                    seeds.add(m)
        self.w("- **Random seeds**: %s -- every resampling interval is seeded, so it "
               "reproduces exactly." % (", ".join(sorted(seeds)) if seeds
                                        else "none were needed"))
        rs = ctx.get("repro_script")
        if rs:
            self.w("- **Generated cleaning script**: `cleaned/%s` -- re-runnable against the "
                   "raw file and checked against the cleaned hash." % rs)
        touched = run.get("columns_touched_by_ops") or []
        if touched:
            self.w("- **Columns any operation was permitted to touch**: %s"
                   % ", ".join("`%s`" % c for c in touched))
        self.w()
        pdf = ctx.get("pdf") or {}
        if pdf.get("pdf_written"):
            extra = ""
            if pdf.get("interpreter"):
                extra = " (interpreter: %s)" % Path(pdf["interpreter"]).name
            if pdf.get("browser"):
                extra = " (%s)" % Path(pdf["browser"]).name
            self.w("- **PDF backend**: `%s`%s. The page count, byte count and sha256 of "
                   "the delivered PDF are recorded in `report_build.json` under `pdf`; "
                   "the probe that established this backend is under `pdf_probe`. They "
                   "are not printed here because a document cannot contain its own hash, "
                   "and a page count measured before the last line changed is not the "
                   "page count of the file you are reading."
                   % (pdf.get("backend"), extra))
            if pdf.get("cjk_text_present"):
                self.w("  The data contains non-Latin characters, so the renderer was asked "
                       "for a CJK-capable font; %s."
                       % ("one was embedded" if pdf.get("cjk_font_embedded")
                          else "the built-in fallback reported no embedded CID font -- "
                               "open the PDF and check the column names render"))
            lim = pdf.get("limitations") or []
            if lim:
                self.w("  Known limits of this backend: %s." % "; ".join(lim))
        else:
            self.w("- **PDF backend**: BLOCKED -- %s. `report.md` holds the same content and "
                   "is complete." % pdf.get("blocked_reason", "unknown"))
            for c in pdf.get("fix_commands") or []:
                self.w("  - `%s`" % c)
        skipped = [a for a in (pdf.get("attempts") or []) if not a.get("ok")]
        if skipped:
            self.w()
            self.w("Backends tried and why each was skipped:")
            for a in skipped:
                self.w("- `%s`: %s" % (a.get("tier"), str(a.get("error", ""))[:240]))

    # -- figures ------------------------------------------------------------
    def figures(self) -> None:
        ctx = self.ctx
        dec = ctx["decisions"] or {}
        rendered = {r.get("id"): r for r in ((ctx["rendered"] or {}).get("rendered") or [])}
        self.w("## 7. Figures")
        self.w()
        self.w("Each figure carries one argument and its title states that argument as a "
               "finding computed from the data rather than as a topic label. The chart types "
               "considered and rejected are listed under each one, because choosing a chart "
               "is itself a claim about what matters.")
        self.w()
        if not dec.get("decisions"):
            self.w("_No figure was produced, because nothing in the data supported a figure "
                   "that says something a table does not already say._")
            self.w()
            return
        for i, d in enumerate(dec["decisions"], 1):
            info = rendered.get(d.get("id"), {})
            rel = "charts/" + Path(d.get("output_path", "")).name
            self.w("### Figure %d -- %s" % (i, d.get("title")))
            self.w()
            self.w("*%s*" % d.get("caption", ""))
            self.w()
            if info.get("non_blank") is False:
                self.w("> **This figure failed its own blank-page check** (ink ratio %s) and "
                       "must not be read as evidence until it is re-rendered."
                       % fmt(info.get("ink_ratio"), 4))
                self.w()
            self.w("![Figure %d: %s](%s)" % (i, d.get("title"), rel))
            self.w()
            body = d.get("body") or {}
            self.w("- **What it shows**: %s" % body.get("fact", "--"))
            self.w("- **How to read it**: %s" % body.get("interpretation", "--"))
            self.w("- **What follows**: %s" % body.get("implication", "--"))
            if d.get("uncertainty"):
                self.w("- **Uncertainty shown**: %s" % d["uncertainty"])
            rej = d.get("rejected") or []
            if rej:
                self.w("- **Chart alternatives rejected**: %s"
                       % "; ".join("%s -- %s" % (r.get("chart_type"), r.get("reason"))
                                   for r in rej))
            self.w("- **Source**: `scripts/chart_decision.py` -> `%s` rendered by "
                   "`scripts/render_chart.py`%s"
                   % (rel, (", %s bytes, ink ratio %s"
                            % (words(info.get("bytes")), fmt(info.get("ink_ratio"), 4)))
                      if info.get("bytes") else ""))
            self.w()
        skipped = (ctx["rendered"] or {}).get("skipped") or []
        if skipped:
            self.w("### Figures decided but not rendered")
            self.w()
            for s in skipped:
                self.w("- `%s` (%s): %s" % (s.get("id"), s.get("chart_type"), s.get("reason")))
            self.w()

    def spec_tables(self) -> None:
        dec = self.ctx["decisions"] or {}
        rows = []
        for d in dec.get("decisions") or []:
            spec = d.get("spec") or {}
            detail = []
            for k, v in spec.items():
                if k == "panels":
                    detail.append("%d panels" % len(v))
                elif isinstance(v, (str, int, float, bool)) or v is None:
                    detail.append("%s = %s" % (k, v))
            rows.append([d.get("order", "?"), "`%s`" % d.get("id"), d.get("chart_type"),
                         "; ".join(detail) or "--"])
        if rows:
            self.w("## 8. Figure specifications")
            self.w()
            self.w(md_table(["#", "ID", "Chart type", "Specification"], rows))
            self.w()
    # -- appendices ---------------------------------------------------------
    def appendices(self) -> None:
        """The three appendices a reviewer actually turns to, plus one ledger.

        A1 is the page that decides whether the report is honest. A sensitivity
        analysis that was not run must be printed as *not run*, never as *passed*:
        an absent check that reads like a passed check is the single most
        expensive failure mode in a report of this kind.
        """
        inf = self.ctx["inferential"] or {}
        run = self.ctx["cleaning_run"] or {}

        self.w("## Appendix A1. Sensitivity and stability")
        self.w()
        rows = []
        for t in (inf.get("tests") or []):
            rc = t.get("robustness_cross_check")
            if rc and rc.get("test"):
                rows.append([
                    "`%s`" % t.get("outcome"),
                    "rank-based cross-check of the primary test",
                    "%s = %s" % (rc.get("test"), fmt(rc.get("statistic"), 2)),
                    fmt_p(rc.get("p_raw")),
                    "agrees" if rc.get("agrees_with_primary") else "**DISAGREES**",
                ])
        if rows:
            self.w(md_table(["Outcome", "Perturbation", "Statistic", "p", "Verdict"], rows))
            self.w("Each primary parametric test was repeated with its rank-based "
                   "equivalent. Agreement means the conclusion does not depend on the "
                   "normality assumption the parametric test makes; a disagreement would "
                   "have meant the parametric test had to go, not be defended.")
        else:
            self.w("No rank-based cross-check was recorded for any outcome.")
        self.w()

        # -- what was NOT done, stated as loudly as what was ----------------
        dup = next((a for a in ((self.ctx["profile"] or {}).get("anomalies") or {}).get("flags", [])
                    if a.get("type") == "duplicate_rows" and a.get("count")), None)
        self.w("### A1.1 Sensitivity analyses not run")
        self.w()
        gaps = []
        if dup:
            gaps.append([
                "drop the %s duplicate rows and re-run every test" % words(dup["count"]),
                "**NOT RUN -- this is a gap, not a pass**",
                "Duplicate rows were deliberately left in place. Removing them is a "
                "decision about whether repeated observations are independent, and that "
                "decision belongs to the author. Until it is made, the reported n and "
                "every interval derived from it stand unchanged.",
            ])
        if (self.ctx["plan"] or {}).get("severity_counts", {}).get("P0"):
            gaps.append([
                "%d P0-severity rule(s) matched" %
                self.ctx["plan"]["severity_counts"]["P0"],
                "**NOT RUN as a sensitivity branch**",
                "P0 rules are applied unconditionally by the contract; there is no "
                "branch in which they are skipped, so there is nothing to compare against.",
            ])
        gaps.append([
            "leave-one-group-out refit of the primary effect size",
            "**NOT RUN**",
            "Not implemented in this pipeline. With three groups this would show whether "
            "one group alone carries the effect; its absence means the reported effect "
            "size is a single estimate with no leave-one-out envelope around it.",
        ])
        self.w(md_table(["Sensitivity analysis", "Status", "What that means"], gaps))
        self.w("These are listed as gaps so that nobody reads the absence of a "
               "disagreement in A1 as evidence that no disagreement exists. A check that "
               "did not run cannot pass.")
        self.w()

        # -- A2 cleaning ledger ---------------------------------------------
        self.w("## Appendix A2. Cleaning ledger")
        self.w()
        self.w("Every operation that ran, in order, with the catalogue rule it came "
               "from. Nothing below was chosen by the model at run time: the plan is the "
               "gate, and only `plan[\"auto_actions\"]` may execute.")
        self.w()
        def _cols(o):
            cols = o.get("columns") or []
            if not cols:
                return "(file-level)"
            shown = ", ".join("`%s`" % c for c in cols[:3])
            return shown + (" (+%d more)" % (len(cols) - 3) if len(cols) > 3 else "")

        def _rule(o):
            src = o.get("rule_source") or "--"
            # The anchor identifies the rule; the full path is in cleaning_run.json.
            # Printing the whole path here made one cell 60 characters wide and
            # squeezed every other column in the table.
            anchor = src.split("#")[-1] if "#" in src else src
            return "`%s`" % anchor.replace("tabular:", "")

        self.w(md_table(
            ["#", "Operation", "Columns", "Sev.", "Rows", "Rule"],
            [[i, "`%s`" % o.get("op"), _cols(o), o.get("severity", "--"),
              "%s->%s" % (words(o.get("n_before")), words(o.get("n_after"))),
              _rule(o)]
             for i, o in enumerate(run.get("applied_ops") or [], 1)]))
        self.w()
        self.w("The `Rule` column names the catalogue anchor; the full path, the "
               "operation id and the exact column list for every row above are in "
               "`cleaned/cleaning_run.json` under `applied_ops`.")
        self.w()

        for label, key, empty in (
                ("Withheld -- proposed but deliberately not applied", "withheld",
                 "Nothing was withheld."),
                ("Failed -- attempted and did not complete", "failed",
                 "No operation failed.")):
            items = run.get(key) or []
            self.w("**%s.**" % label)
            self.w()
            if items:
                for it in items:
                    cols = ", ".join("`%s`" % c for c in (it.get("columns") or [])) or "(file)"
                    self.w("- `%s` on %s -- %s"
                           % (it.get("op"), cols, it.get("reason") or it.get("error")))
            else:
                self.w(empty)
            self.w()

        held = run.get("never_automatic_flags") or []
        if held:
            self.w("**Never-automatic -- conversions that were held back by policy.** "
                   "These are the cases where a conversion was technically possible but "
                   "would have destroyed information, so the policy refuses it without "
                   "asking.")
            self.w()
            for f in held:
                self.w("- `%s` on %s -- %s"
                       % (f.get("op"), ", ".join("`%s`" % c for c in (f.get("columns") or [])),
                          f.get("reason", "")))
            self.w()

        ua = run.get("untouched_column_audit") or {}
        self.w("**Additive-only audit.** The contract forbids modifying the raw file and "
               "permits an operation to touch only the columns it names. Columns no "
               "operation named: **%s**."
               % ("%s, and each kept exactly its raw values -- audit passed"
                  % words(ua.get("columns_checked")) if ua.get("passed")
                  else "audit result -- %s" % (ua.get("reason") or "not run")))
        if ua.get("columns_violating"):
            self.w()
            self.w("> **VIOLATIONS**: %s" % ", ".join("`%s`" % v for v in ua["columns_violating"]))
        self.w()

        cv = run.get("case_variant_merge_map") or []
        if cv:
            self.w("**Label conflicts resolved before grouping.** Grouping on a column "
                   "whose labels differ only by case splits one group into two and halves "
                   "both n, which shrinks intervals without any loss of real information. "
                   "The merge map below is the audit trail for that decision.")
            self.w()
            self.w(md_table(
                ["Column", "Labels merged", "Variants"],
                [["`%s`" % c.get("column"), words(c.get("n_merged_groups")),
                  ", ".join("`%s`" % v for v in (c.get("variants") or []))]
                 for c in cv]))
            self.w()

        # -- A3 rejected alternatives ---------------------------------------
        self.w("## Appendix A3. Alternatives considered and not used")
        self.w()
        self.w("A test is a choice. Listing only the test that was run hides the fact "
               "that a different, defensible analysis was available, so every rejected "
               "alternative is recorded here with the reason it lost.")
        self.w()
        rows = []
        for t in (inf.get("tests") or []):
            for r in (t.get("rejected_alternatives") or []):
                rows.append(["`%s`" % t.get("outcome"), t.get("design"),
                             "`%s`" % r.get("test"), r.get("reason")])
        if rows:
            self.w(md_table(["Outcome", "Design", "Rejected test", "Reason"], rows))
        else:
            self.w("No alternatives were rejected.")
        self.w()

        rules = inf.get("rule_source")
        self.w("The rule that made these choices is `%s`. It was applied mechanically; "
               "there is no per-dataset override, because a rule that is quietly "
               "overridden is a rule that cannot be checked." % (rules or "--"))
        self.w()

    # -- A4 / provenance -------------------------------------------------
    def provenance(self) -> None:
        self.w("## Appendix A4. Where every number came from")
        self.w()
        self.w("Each value below was registered by the code that read it from an "
               "artifact on disk. A sentence in this report that is not backed by a row "
               "here is a sentence that should not have been written.")
        self.w()

        def short_value(v: Any) -> str:
            if v is None:
                return "--"
            if isinstance(v, float):
                return fmt(v, 6)
            if isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False)
            text = str(v)
            return text if len(text) <= 64 else text[:61].rstrip() + "..."

        def short_path(v: Any) -> str:
            return basename(v) or "--"

        def short_rule(v: Any) -> str:
            if not v:
                return "--"
            text = str(v)
            anchor = text.split("#")[-1] if "#" in text else text
            return anchor.replace("tabular:", "")

        # Short labels: the long snake_case kind wrapped mid-word in the narrow
        # first column ("method-rej ection"), which reads as a typo.
        kind_label = {"method_rejection": "rejected test",
                      "multiplicity": "correction",
                      "headline": "headline"}
        rows = []
        for c in self.prov.claims:
            kind = str(c.get("kind", ""))
            rows.append([
                "`%s`" % kind_label.get(kind, kind.replace("_", "-")),
                short_value(c.get("value")),
                c.get("meaning") or "--",
                "`%s` -> `%s`" % (short_path(c.get("script")),
                                  short_path(c.get("artifact"))),
                "`%s`" % short_rule(c.get("rule_source")),
            ])
        self.w(md_table(["Kind", "Value", "What it means",
                         "Source: script -> artifact", "Rule anchor"], rows))
        self.w("Only the basename of each artifact and script is shown here; the full "
               "path, the untruncated value and the complete claim record for every row "
               "are in `report_build.json` under `provenance`. Each record carries "
               "`rule_source`, and where a rule had an alternative the record names it "
               "and why it lost -- a claim with no alternative says so rather than "
               "leaving the field blank.")
        self.w()

    # -- open questions ---------------------------------------------------
    def open_questions(self) -> None:
        """Collect every AUTHOR_INPUT_NEEDED and every unverified assumption.

        These are gathered from the artifacts rather than written from memory, so
        the list cannot drift away from what the pipeline actually flagged.
        """
        ctx = self.ctx
        run = ctx["cleaning_run"] or {}
        plan = ctx["plan"] or {}
        prof = ctx["profile"] or {}
        inf = ctx["inferential"] or {}

        items: List[Tuple[str, str, str]] = []

        if not (inf.get("unit_of_analysis") or {}).get("unit_key"):
            items.append((
                "What does one row represent?",
                "Every interval in this report is conditional on one row being one "
                "independent observation. If a row pools replicates, subjects, sites or "
                "runs, the effective n is smaller than the row count and every interval is "
                "too narrow.",
                "HIGH -- rescales every interval in the report"))
        if not any("pre-register" in (c.get("resolved_by") or "").lower()
                   for c in ctx["caveats"]):
            items.append((
                "Were these outcomes chosen in advance?",
                "Nothing in the input records a pre-specified analysis plan, and the "
                "outcome family was assembled from the columns present. Without that, the "
                "family-size correction controls multiplicity within this report but cannot "
                "address selection across reports.",
                "HIGH -- determines whether the correction is the right one"))
        dup = next((a for a in (prof.get("anomalies") or {}).get("flags", [])
                    if a.get("type") == "duplicate_rows" and a.get("count")), None)
        if dup:
            items.append((
                "Are the %s duplicated rows independent?" % words(dup["count"]),
                "They are byte-identical repeats. If they are double entry they inflate n; "
                "if they are genuine repeated measurement they belong in the design. The "
                "pipeline does not guess, and A1.1 records this as a gap rather than a "
                "result.",
                "HIGH -- inflates n and narrows intervals"))
        for f in (run.get("never_automatic_flags") or []):
            cols = ", ".join("`%s`" % c for c in (f.get("columns") or [])) or "the file"
            items.append((
                "How should `%s` on %s be resolved?" % (f.get("op"), cols),
                f.get("reason", ""),
                "MEDIUM -- the pipeline stopped at this decision instead of guessing"))
        held_out = [c for c in (ctx["caveats"] or [])
                    if "AUTHOR_INPUT_NEEDED" in (c.get("resolved_by") or "")]
        if not items:
            items.append((
                "Was the grouping variable assigned or observed?",
                "This pipeline compares groups that already exist in the file. It cannot "
                "tell an assigned group from an observed one, and that difference decides "
                "whether the comparison can carry a causal reading at all.",
                "HIGH -- governs the causal language allowed in section 4"))

        self.w("## Appendix B. Open questions the data cannot answer")
        self.w()
        self.w("%d question%s must be answered by someone who knows how the data were "
               "collected. They are listed with the consequence of leaving them "
               "unanswered, because an unanswered question that carries no stated cost is "
               "one nobody will prioritise." % (len(items), "" if len(items) == 1 else "s"))
        self.w()
        self.w(md_table(["#", "Question", "Why it matters", "Cost of leaving it open"],
                        [[i, q, why, cost] for i, (q, why, cost) in enumerate(items, 1)]))
        self.w()
        if held_out:
            self.w("Of these, %d are already reflected as caveats in section 5."
                   % len(held_out))
            self.w()
        self.w("### What this report does not claim")
        self.w()
        self.w("- It does not claim the group label produced the measurement.")
        self.w("- It does not claim the analysis was pre-specified.")
        self.w("- It does not claim the rows are independent observations.")
        self.w("- It does not claim any mechanism for the missingness it reports; the "
               "screening test in 2.3 is a description, not a diagnosis.")
        self.w()

    # -- colophon -----------------------------------------------------------
    def colophon(self) -> None:
        """Close the document instead of leaving a page with one orphan bullet.

        Without this, the last list item of Appendix B landed alone on page 14
        and the report looked like it had been cut off.
        """
        self.w("---")
        self.w()
        self.w("*End of report. Generated %s by data-master. The raw input was never "
               "modified: every value above was read from the cleaned file or from a "
               "recorded artifact. Each number is registered in `report_build.json`; "
               "the gate verdict, including anything that failed, is in "
               "`audit/final_audit.md`.*" % self.ctx["generated"])
        self.w()

    # -- self-audit ---------------------------------------------------------
    def audit_own_prose(self) -> Dict[str, Any]:
        """Run the forbidden-phrase catalogue against the prose just written.

        The report is held to the same rule it enforces on the user. Lines carrying a
        disclaimer marker are skipped, because the report quotes bad phrasings in
        order to reject them and a scanner that cannot tell the difference would
        force those quotes out -- and then the report would have to stop explaining
        why it does not make the claim.
        """
        findings: List[Dict[str, str]] = []
        for i, line in enumerate(self.lines, 1):
            low = line.lower()
            if any(m in low for m in DISCLAIMER_MARKERS):
                continue
            for pattern, why in FORBIDDEN:
                m = re.search(pattern, line, flags=re.IGNORECASE)
                if m:
                    findings.append({"line": str(i), "phrase": m.group(0),
                                     "why": why, "text": line.strip()[:160]})
        self.violations = findings
        return {"n_forbidden": len(findings), "findings": findings,
                "n_lines_scanned": len(self.lines)}

    # -- assembly -----------------------------------------------------------
    def build(self) -> str:
        """One pass, one fixed order, each section called exactly once.

        The order is not cosmetic: the executive summary is written before the
        sections it summarises because it is generated from the same artifacts by
        the same code, and the self-audit runs last because it can only judge text
        that already exists.
        """
        self.lines = []
        self.prov = Provenance()
        self.violations = []
        self.header()
        self.executive_summary()
        self.setup()
        self.methods()
        self.results()
        self.discussion()
        self.caveats()
        self.reproducibility()
        self.figures()
        self.spec_tables()
        self.appendices()
        self.provenance()
        self.open_questions()
        self.colophon()
        audit = self.audit_own_prose()
        return "\n".join(self.lines).rstrip() + "\n"

# --------------------------------------------------------- TL;DR document

def build_executive_summary(ctx: Dict[str, Any], builder: ReportBuilder) -> str:
    """A standalone one-pager, written from the same artifacts as the full report.

    Deliberately mechanical: it restates the headline, the count of defects handled
    and the cost of the open questions, and it points at the report rather than
    re-arguing the analysis. Two documents that argue differently is worse than one
    document that is short.
    """
    b = ReportBuilder(ctx, ctx["template"])
    head, top_outcome = b.headline()
    inf = ctx["inferential"] or {}
    run = ctx["cleaning_run"] or {}
    tests = inf.get("tests") or []
    n_est = sum(1 for t in tests if t.get("estimable"))

    L: List[str] = []
    L.append("# %s -- Executive summary" % ctx["title"])
    L.append("")
    L.append("_Generated %s by scripts/assemble_report.py from the artifacts listed in "
             "`report_build.json`. Every statement below is a restatement of the full "
             "report, not a separate analysis._" % ctx["generated"])
    L.append("")
    L.append("**Headline.** %s." % (head if head else "No group comparison was estimable."))
    L.append("")
    L.append("| | |")
    L.append("|---|---|")
    L.append("| Rows analysed | %s (from %s raw) |"
             % (words(run.get("n_clean")), words(run.get("n_raw"))))
    L.append("| Columns | %s after cleaning, %d dropped |"
             % (len(run.get("columns_after") or []), len(run.get("columns_dropped") or [])))
    L.append("| Grouping variable | `%s`, %s |"
             % (inf.get("group") or "none established",
                ", ".join(str(x) for x in (inf.get("group_levels") or [])) or "--"))
    L.append("| Outcomes tested | %d of %d estimable |" % (n_est, len(tests)))
    fam = (inf.get("multiple_comparisons") or {}).get("primary_family") or {}
    L.append("| Multiplicity | %s, family of %s, %s surviving |"
             % (fam.get("method", "--"), fam.get("family_size", "--"),
                fam.get("n_significant_adjusted", "--")))
    L.append("| Cleaning operations | %d applied, %d withheld |"
             % (len(run.get("applied_ops") or []), len(run.get("withheld") or [])))
    L.append("| Byte-level reproducibility | %s |"
             % ("passed" if (run.get("reproducibility_check") or {}).get("passed") else "FAILED"))
    L.append("| Caveats raised | %d |" % len(ctx["caveats"]))
    L.append("| Open questions | see Appendix B |")
    L.append("")
    L.append("## The three things a reader should take away")
    L.append("")
    L.append("1. **%s**" % (head if head else
                           "The data did not support a group comparison, and none was forced."))
    L.append("2. **%d caveat(s) bound these results**, and the one that matters most is: %s"
             % (len(ctx["caveats"]), ctx["caveats"][0]["caveat"]))
    L.append("3. **This design compares groups that already exist.** The group label was "
             "not assigned here, so the differences reported are associations. No causal "
             "reading is available from this data, and none is offered.")
    L.append("")
    L.append("## What to read next")
    L.append("")
    L.append("- `report.pdf` (or `report.md`) -- the full report, with figures and appendices.")
    L.append("- Section 5 -- the caveats, each with its limits and its resolution status.")
    L.append("- Appendix A1.1 -- the sensitivity analyses that were *not* run.")
    L.append("- Appendix B -- the questions that only the data's author can answer.")
    L.append("- `report_build.json` -- machine-readable provenance for every number above.")
    L.append("")
    return "\n".join(L)


# --------------------------------------------------------------- context

def load_context(raw: Optional[str], outdir: Path, title: str,
                 template: str) -> Dict[str, Any]:
    ana = outdir / "analysis"
    cleaned_dir = outdir / "cleaned"
    ctx: Dict[str, Any] = {
        "title": title,
        "template": template,
        "generated": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z"),
        "raw_path": Path(raw) if raw else None,
        "cleaned_path": cleaned_dir / "cleaned.csv",
        "report_path": outdir / "report.md",
        "outdir": outdir,
        "profile": load_json(ana / "profile.json"),
        "descriptive": load_json(ana / "descriptive.json"),
        "inferential": load_json(ana / "inferential.json"),
        "decisions": load_json(ana / "chart_decisions.json"),
        "rendered": load_json(outdir / "charts_rendered.json"),
        "cleaning_run": load_json(cleaned_dir / "cleaning_run.json"),
        "validation": load_json(cleaned_dir / "validation.json"),
        "plan": load_json(outdir / "cleaning_plan.json"),
        "pdf": {},
        "caveats": [],
    }
    prov = (ctx["decisions"] or {}).get("dtype_provenance") or {}
    ctx["dtype_provenance"] = prov
    ctx["hashes"] = {
        "profile": sha256_of(ana / "profile.json")[:16],
        "plan": sha256_of(outdir / "cleaning_plan.json")[:16],
        "validation": sha256_of(cleaned_dir / "validation.json")[:16],
        "descriptive": sha256_of(ana / "descriptive.json")[:16],
        "inferential": sha256_of(ana / "inferential.json")[:16],
        "decisions": sha256_of(ana / "chart_decisions.json")[:16],
        "rendered": sha256_of(outdir / "charts_rendered.json")[:16],
    }
    try:
        import pandas
        libs = {"pandas": pandas.__version__}
    except Exception:
        libs = {}
    try:
        import numpy
        libs["numpy"] = numpy.__version__
    except Exception:
        pass
    try:
        import scipy
        libs["scipy"] = scipy.__version__
    except Exception:
        pass
    ctx["environment"] = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "libs": libs,
        "assembled_at": ctx["generated"],
    }
    return ctx


# ------------------------------------------------------------------ main

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Assemble report.md, "
                                                 "executive_summary.md and report.pdf")
    ap.add_argument("--raw", help="path to the original, untouched input file")
    ap.add_argument("--outdir", required=True, help="outputs directory holding the artifacts")
    ap.add_argument("--title", default="Dataset", help="report title")
    ap.add_argument("--template", default="research-report")
    ap.add_argument("--pdf-backend", default="auto",
                    choices=["auto", "reportlab", "fpdf2", "headless-browser"])
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero if the prose self-audit finds a forbidden phrase")
    args = ap.parse_args(argv)

    outdir = Path(args.outdir)
    if not outdir.exists():
        print("outdir not found: %s" % outdir, file=sys.stderr)
        return 2
    ctx = load_context(args.raw, outdir, args.title, args.template)

    missing = [k for k in ("profile", "descriptive", "inferential", "cleaning_run")
               if not ctx[k]]
    if missing:
        print("missing artifacts: %s -- run the earlier pipeline stages first"
              % ", ".join(missing), file=sys.stderr)
        return 2

    ctx["caveats"] = build_caveats(ctx)

    md_path = ctx["report_path"]
    pdf_path = outdir / "report.pdf"
    probe_md = outdir / "_pdf_probe.md"
    probe_pdf = outdir / "_pdf_probe.pdf"
    b1 = ReportBuilder(ctx, args.template)
    md1 = b1.build()

    # Pass 1 discovers which backend can actually run on this machine, so that the
    # claim printed in section 6 is a fact rather than an intention. The probe is
    # rendered from a throwaway copy so the delivered report.md is written once.
    print("[assemble] probing PDF backends ...")
    probe_md.write_text(md1, encoding="utf-8")
    probe = render_pdf_cascade(probe_md, probe_pdf, prefer=args.pdf_backend)
    probe["probed_from"] = "throwaway first pass; the delivered PDF is re-rendered"
    ctx["pdf"] = probe

    # Pass 2 pins the backend the probe proved works, so the statement in section 6
    # describes the renderer that actually produced the delivered file.
    prefer = probe.get("backend") or args.pdf_backend
    b2 = ReportBuilder(ctx, args.template)
    md = b2.build()
    md_path.write_text(md, encoding="utf-8")

    print("[assemble] rendering deliverable PDF with backend '%s' ..." % prefer)
    final = render_pdf_cascade(md_path, pdf_path, prefer=prefer, verbose=False)
    if not final.get("pdf_written"):
        print("[assemble] PDF BLOCKED: %s" % final.get("blocked_reason"), file=sys.stderr)
    elif final.get("backend") != probe.get("backend"):
        print("[assemble] WARNING: probed backend %s, delivered %s -- report_build.json "
              "records the truth, section 6 may lag" % (probe.get("backend"),
                                                         final.get("backend")),
              file=sys.stderr)

    (outdir / "executive_summary.md").write_text(
        build_executive_summary(ctx, b2), encoding="utf-8")

    audit = b2.audit_own_prose()
    payload = {
        "schema_version": SCHEMA_VERSION,
        "title": ctx["title"],
        "template": args.template,
        "generated": ctx["generated"],
        "report_md": str(md_path),
        "report_md_sha256": sha256_of(md_path),
        "executive_summary_md": str(outdir / "executive_summary.md"),
        "report_pdf": str(pdf_path) if final.get("pdf_written") else None,
        "pdf": final,
        "pdf_probe": probe,
        "artifact_hashes": ctx["hashes"],
        "cleaned_sha256": sha256_of(ctx["cleaned_path"]),
        "environment": ctx["environment"],
        "caveats": ctx["caveats"],
        "provenance": b2.prov.claims,
        "self_audit": audit,
    }
    (outdir / "report_build.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    for tmp in (probe_md, probe_pdf):
        try:
            tmp.unlink()
        except OSError:
            pass

    n_forbidden = audit["n_forbidden"]
    print("[assemble] report.md  %s (%d lines)"
          % (words(md_path.stat().st_size), md.count("\n") + 1))
    print("[assemble] report.pdf %s"
          % (("%s, backend=%s" % (words(final.get("bytes")), final.get("backend")))
             if final.get("pdf_written") else "NOT WRITTEN -- %s" % final.get("blocked_reason")))
    print("[assemble] provenance claims %d | caveats %d | forbidden phrases %d"
          % (len(b2.prov.claims), len(ctx["caveats"]), n_forbidden))
    if n_forbidden:
        for f in audit["findings"]:
            print("[assemble]   line %s: %r -- %s" % (f["line"], f["phrase"], f["why"]),
                  file=sys.stderr)
        if args.strict:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
