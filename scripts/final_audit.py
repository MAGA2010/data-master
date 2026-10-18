#!/usr/bin/env python3
"""Final audit: does this report deserve the word "Nature-level"?

The report writer cannot audit itself.  assemble_report.py checks its own prose for
forbidden phrasing, but a self-check run by the same code that produced the text can
only find what that code already knew to look for.  This script is the second reader:
it re-derives every claim from the artifacts on disk, marks each of the 8 Nature
statistical gates PASS / WARN / FAIL / N/A with its evidence, and refuses the label
"submission-ready" unless the mandatory gates pass.

It also routes the run to the reporting checklist that matches its study design
(CONSORT, STROBE, PRISMA, MOOSE, STARD, ARRIVE, SQUIRE, CARE) and to the journal
family it is being prepared for (Nature, NEJM, Science, Lancet).  Routing is not
decoration: a trial judged against STROBE is being judged against the wrong
question, and a checklist that is never named is a checklist nobody can fail.

Exit codes
    0   every mandatory gate passed (WARN allowed where the gate permits it)
    1   at least one mandatory gate failed -- the report exists but is not
        submission-ready, and audit/final_audit.md lists the actionable fixes
    2   the audit could not run (missing artifacts)

Usage
    python scripts/final_audit.py --outdir outputs \
        [--journal auto|nature|nejm|science|lancet] [--design auto|<design_id>] \
        [--require-report] [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

# Kept in sync with assemble_report.FORBIDDEN by test_pipeline_invariants.
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

DISCLAIMER_MARKERS = (
    "not available from this data",
    "is not made in this report",
    "use instead",
    "forbidden",
)

REQUIRED_SECTIONS = [
    ("Executive summary", r"^##\s+Executive summary\s*$"),
    ("1. Setup", r"^##\s+1\.\s+Setup\s*$"),
    ("2. Methods", r"^##\s+2\.\s+Methods\s*$"),
    ("3. Results", r"^##\s+3\.\s+Results\s*$"),
    ("4. Discussion", r"^##\s+4\.\s+Discussion\s*$"),
    ("5. Caveats", r"^##\s+5\.\s+Caveats"),
    ("6. Reproducibility", r"^##\s+6\.\s+Reproducibility\s*$"),
    ("7. Figures", r"^##\s+7\.\s+Figures\s*$"),
    ("Appendix A1 -- sensitivity", r"^##\s+Appendix A1\."),
    ("Appendix B -- open questions", r"^##\s+Appendix B\."),
]

MANDATORY_UNLESS_RELAXED = {1, 2, 7, 8}


def load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def gate(gid: int, name: str, status: str, evidence: str,
         issues: Optional[List[str]] = None, fix: str = "") -> Dict[str, Any]:
    if status not in ("PASS", "WARN", "FAIL", "N/A"):
        raise ValueError(status)
    return {"gate": gid, "name": name, "status": status,
            "evidence": evidence, "issues": issues or [], "fix": fix}


def _pct(x: Any) -> str:
    try:
        return "%.1f%%" % float(x)
    except (TypeError, ValueError):
        return "--"


# ------------------------------------------------------------------- gates

def gate_1_n_unit(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """n is explicit, the independent unit is defined, and the analysis lives there.

    Declaring a unit key used to be the whole gate. It no longer is: a run that
    declares units, detects rows-per-unit > 1, and then reports row-level tests
    as primary has answered the question on paper and ignored it in the
    numbers, which is worse than not asking.
    """
    inf = ctx["inferential"] or {}
    unit = inf.get("unit_of_analysis") or {}
    tests = [t for t in (inf.get("tests") or []) if t.get("estimable")]

    if not tests:
        return gate(1, "n explicit and unit-defined", "N/A",
                    "no comparison was estimable, so there is no n to defend")

    missing_n = [t.get("outcome") for t in tests if not t.get("n_total")]
    unit_key = unit.get("unit_key")
    rows_per_unit = unit.get("rows_per_unit")
    primary_level = inf.get("primary_level") or "row"
    clustered = rows_per_unit is not None and float(rows_per_unit) > 1.0

    issues = []
    if missing_n:
        issues.append("no n recorded for: %s" % ", ".join(str(x) for x in missing_n))
    if not unit_key:
        issues.append("independent unit not declared: %s"
                      % (unit.get("note") or "no --unit-key given"))

    if clustered and primary_level == "row":
        return gate(1, "n explicit and unit-defined", "FAIL",
                    "rows repeat within units (rows_per_unit=%s) and the primary "
                    "tests still treat every row as independent; the declared unit "
                    "and the analysed unit are different objects."
                    % rows_per_unit,
                    ["primary_level is %r with rows_per_unit=%s"
                     % (primary_level, rows_per_unit)],
                    "re-run the inferential stage with --unit-key; it now moves the "
                    "primary analysis to the unit level (or pairs the units) "
                    "automatically once the structure is known")

    n_total = tests[0].get("n_total") if tests else None
    if issues:
        status = "FAIL" if not unit_key else "WARN"
        return gate(1, "n explicit and unit-defined", status,
                    "n is recorded per outcome (e.g. n=%s) and per group, but the "
                    "independent unit is %s."
                    % (n_total, "declared as `%s`" % unit_key if unit_key
                       else "not declared in the input"),
                    issues,
                    "pass --unit-key with what one row represents, or record it in "
                    "the run manifest; the report already marks this "
                    "AUTHOR_INPUT_NEEDED.")
    evidence = ("unit `%s` declared; primary analysis at the %s level; n=%s "
                "across %d outcome(s)."
                % (unit_key, primary_level, n_total, len(tests)))
    if clustered:
        evidence = ("unit `%s` declared (%s rows -> %s units, structure: %s); the "
                    "primary analysis runs at the `%s` level and the row-level "
                    "results are kept as a labelled secondary; n=%s."
                    % (unit_key, unit.get("n_rows"), unit.get("n_units"),
                       unit.get("structure"), primary_level, n_total))
    return gate(1, "n explicit and unit-defined", "PASS", evidence)


def gate_2_missing(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Missing data mechanism declared wherever it can change a conclusion."""
    desc = ctx["descriptive"] or {}
    screen = desc.get("missing_mechanism_screen") or []
    run = ctx["cleaning_run"] or {}
    n = run.get("n_clean") or 0

    over5, under5, undeclared = [], [], []
    for m in screen:
        missing = m.get("n_missing") or 0
        if not missing:
            continue
        pct = m.get("missing_pct")
        mech = m.get("mechanism")
        if not mech or str(mech).upper() in ("UNKNOWN", "N/A", "NONE"):
            undeclared.append(m.get("column"))
        if (pct or 0) > 5.0:
            over5.append(m)
        else:
            under5.append(m)

    if not screen:
        return gate(2, "missing data mechanism declared", "PASS",
                    "no variable carries missing values (n=%s analysed)." % n)

    if undeclared:
        return gate(2, "missing data mechanism declared", "FAIL",
                    "%d variable(s) carry missing values and %d have no declared "
                    "mechanism." % (len(screen), len(undeclared)),
                    ["no mechanism for: %s" % ", ".join(str(c) for c in undeclared)],
                    "run the missing-data screen with a mechanism classification, "
                    "or record AUTHOR_INPUT_NEEDED per column.")

    imputed = [m for m in screen if str(m.get("imputation_default", "")).lower()
               not in ("", "none", "listwise", "listwise deletion")]
    evidence = "; ".join("%s %s (%s)" % (m.get("column"), _pct(m.get("missing_pct")),
                                         m.get("mechanism")) for m in screen)
    if over5 and imputed:
        return gate(2, "missing data mechanism declared", "WARN",
                    "mechanism declared for every variable with missingness: %s."
                    % evidence,
                    ["%d variable(s) above 5%% missing were imputed; a sensitivity "
                     "analysis is required for each" % len(over5)],
                    "report the imputation method, fraction imputed, and the "
                     "compare-with-complete-case result.")
    return gate(2, "missing data mechanism declared", "PASS",
                "mechanism declared for every variable with missingness: %s. "
                "%d variable(s) exceed 5%%; nothing was imputed, so every statistic "
                "is on complete cases." % (evidence, len(over5)))


def gate_3_effect_size(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Every p value is accompanied by an effect size and its interval."""
    inf = ctx["inferential"] or {}
    tests = [t for t in (inf.get("tests") or []) if t.get("estimable")]
    if not tests:
        return gate(3, "effect size accompanies p", "N/A",
                    "no test was estimable")
    no_effect, no_ci = [], []
    for t in tests:
        es = t.get("effect_sizes") or {}
        keys = [k for k in ("omega_squared", "eta_squared", "cramers_v",
                            "cliffs_delta", "cohens_d", "cohens_dz",
                            "odds_ratio", "kendalls_w", "epsilon_squared_rank",
                            "marginal_r2", "conditional_r2")
                if k in es]
        if not keys:
            no_effect.append(t.get("outcome"))
            continue
        # any effect-size key that carries an interval counts, including the
        # nested per-level coefficient intervals mixed models and ANCOVA emit
        has_ci = any(("%s_ci95" % k) in es or "ci95" in es
                     or any("ci95" in str(k2) for k2 in es)
                     for k in keys)
        if not has_ci:
            no_ci.append(t.get("outcome"))
    if no_effect:
        return gate(3, "effect size accompanies p", "FAIL",
                    "%d of %d estimable tests carry no effect size."
                    % (len(no_effect), len(tests)),
                    ["no effect size for: %s" % ", ".join(str(x) for x in no_effect)],
                    "compute an effect size for every outcome or remove the p value.")
    if no_ci:
        return gate(3, "effect size accompanies p", "WARN",
                    "every estimable test has an effect size; %d lack a 95%% CI."
                    % len(no_ci),
                    ["no CI for: %s" % ", ".join(str(x) for x in no_ci)],
                    "bootstrap the interval, or state that the interval is not "
                    "available and why.")
    return gate(3, "effect size accompanies p", "PASS",
                "all %d estimable tests carry an effect size with a 95%% CI."
                % len(tests))


def gate_4_uncertainty(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Uncertainty is visible wherever a number is quoted as a result."""
    desc = ctx["descriptive"] or {}
    decisions = ctx["decisions"] or {}
    report = ctx["report_text"]

    no_se = [c for c, s in (desc.get("numeric") or {}).items() if s.get("se") is None]
    fig_no_unc = [d.get("id") for d in (decisions.get("decisions") or [])
                  if d.get("chart_type") in ("small_multiples_ci", "distribution_panel",
                                             "scatter_panel")
                  and not d.get("uncertainty")]

    p_no_ci: List[str] = []
    for line in report.splitlines():
        s = line.strip()
        if not s or s.startswith("|") or s.startswith("#"):
            continue
        low = s.lower()
        if any(m in low for m in DISCLAIMER_MARKERS):
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", s):
            if re.search(r"\bp\s*[=<>]", sentence) and not re.search(
                    r"\bCI\b|confidence interval|IQR|credible interval", sentence, re.I):
                p_no_ci.append(sentence.strip()[:140])

    issues = []
    if no_se:
        issues.append("no standard error for: %s" % ", ".join(no_se))
    if fig_no_unc:
        issues.append("figure(s) without a stated uncertainty: %s"
                      % ", ".join(str(x) for x in fig_no_unc))
    if p_no_ci:
        issues.append("%d sentence(s) quote a p value with no interval in the same "
                      "sentence" % len(p_no_ci))
    if issues:
        status = "FAIL" if p_no_ci else "WARN"
        return gate(4, "uncertainty visible", status,
                    "descriptive statistics carry a standard error and every figure "
                    "states its uncertainty band; %d prose sentence(s) need an "
                    "interval beside the p value." % len(p_no_ci),
                    issues,
                    "quote the effect size and its CI in the same sentence as p.")
    return gate(4, "uncertainty visible", "PASS",
                "every descriptive statistic carries an SE, every comparison figure "
                "states its interval, and every prose p value sits beside a CI.")

def gate_5_multiplicity(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """More than one test means a stated family and a stated correction."""
    inf = ctx["inferential"] or {}
    tests = [t for t in (inf.get("tests") or []) if t.get("estimable")]
    mc = inf.get("multiple_comparisons") or {}
    fam = mc.get("primary_family") or {}

    if len(tests) < 2:
        return gate(5, "multiple comparisons corrected", "N/A",
                    "only %d test was estimable, so there is no family to correct."
                    % len(tests))
    if not fam:
        return gate(5, "multiple comparisons corrected", "FAIL",
                    "%d tests were run with no multiplicity family declared."
                    % len(tests),
                    ["multiple_comparisons.primary_family is empty"],
                    "declare the family, the correction method and alpha.")
    method = fam.get("method")
    size = fam.get("family_size")
    dropped = fam.get("n_dropped_non_finite") or 0
    adjusted = [p for p in (fam.get("adjusted") or []) if p is not None]
    if not method:
        return gate(5, "multiple comparisons corrected", "FAIL",
                    "a family of %s exists but no correction method is named." % size,
                    ["method is empty"], "name the correction method.")
    if dropped:
        return gate(5, "multiple comparisons corrected", "WARN",
                    "%s correction over a family of %s; %d non-finite p value(s) were "
                    "dropped before correcting." % (method, size, dropped),
                    [fam.get("dropped_note") or "dropped members were not explained"],
                    "state which outcome could not be estimated and why.")
    if len(adjusted) != (size or 0):
        return gate(5, "multiple comparisons corrected", "FAIL",
                    "%s family claims %s members but carries %d adjusted p values."
                    % (method, size, len(adjusted)),
                    ["family size and adjusted vector disagree"],
                    "recompute the correction over exactly the estimable members.")
    return gate(5, "multiple comparisons corrected", "PASS",
                "%s correction over a family of %s; %d adjusted p value(s), all finite. "
                "Raw and adjusted values are both reported."
                % (method, size, len(adjusted)))


def gate_6_sensitivity(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """The primary analysis was perturbed, and the conflicts are named as conflicts.

    A rank-based cross-check of the primary test is assumption robustness: it
    asks whether the test survives a different distributional assumption. This
    gate asks for more -- an artifact from scripts/sensitivity_analysis.py that
    re-ran the primary question on perturbed data (leave-one-group-out, block
    jackknife, disclosed extreme-value exclusion, strict complete cases). The
    cross-check alone no longer satisfies the gate, because a report stamped
    "sensitivity tested" on the strength of it claimed more than it did.
    """
    inf = ctx["inferential"] or {}
    report = ctx["report_text"]
    sens = ctx.get("sensitivity") or {}
    tests = [t for t in (inf.get("tests") or []) if t.get("estimable")]
    if not tests or inf.get("skipped"):
        return gate(6, "sensitivity tested", "N/A", "no test was estimable")

    if not sens:
        return gate(6, "sensitivity tested", "FAIL",
                    "no sensitivity artifact exists (analysis/sensitivity.json). "
                    "The rank cross-checks below test assumptions, not the data; "
                    "they cannot stand in for a perturbation of the analysis.",
                    ["scripts/sensitivity_analysis.py did not run"],
                    "re-run the pipeline (the sensitivity stage follows the "
                    "inferential stage), or run scripts/sensitivity_analysis.py "
                    "--clean cleaned/cleaned.csv --inferential "
                    "analysis/inferential.json --out analysis/sensitivity.json")

    summary = sens.get("summary") or {}
    covered = {o.get("outcome") for o in (sens.get("outcomes") or [])}
    uncovered = [t.get("outcome") for t in tests if t.get("outcome") not in covered]
    n_conf = int(summary.get("n_conflicting") or 0)
    conflicts = summary.get("conflicts") or []
    has_appendix = bool(re.search(r"^##\s+Appendix A1\.", report, re.M))

    if uncovered:
        return gate(6, "sensitivity tested", "FAIL",
                    "the sensitivity artifact exists but %d estimable outcome(s) "
                    "carry no perturbation." % len(uncovered),
                    ["not covered: %s" % ", ".join(str(x) for x in uncovered)],
                    "re-run scripts/sensitivity_analysis.py so every estimable "
                    "outcome is perturbed, or record why it cannot be.")
    if not has_appendix:
        return gate(6, "sensitivity tested", "FAIL",
                    "%d outcome(s) were perturbed but the report has no Appendix A1."
                    % len(covered),
                    ["Appendix A1 missing"], "add the sensitivity appendix.")
    if n_conf:
        return gate(6, "sensitivity tested", "WARN",
                    "%d perturbation(s) across %d outcome(s) changed the "
                    "significance verdict; these are reported as conflicts, not "
                    "errors, and the report must carry them."
                    % (n_conf, summary.get("n_outcomes")),
                    ["%s / %s: p %s -> %s" % (c.get("outcome"),
                                              c.get("perturbation"),
                                              c.get("primary_p"),
                                              c.get("perturbed_p"))
                     for c in conflicts[:6]],
                    "state the conflicts in Appendix A1 and either justify the "
                    "primary choice or change it; a conflict that is disclosed is "
                    "a limit, one that is not is a defect.")
    return gate(6, "sensitivity tested", "PASS",
                "%s perturbation(s) ran across %d outcome(s) (leave-one-group-out, "
                "block jackknife, extreme-value fence, strict complete cases%s) "
                "and every one agreed with the primary verdict at alpha=%s. "
                "Appendix A1 reports them."
                % (summary.get("n_perturbations"), summary.get("n_outcomes"),
                   ", imputation sensitivity" if any(
                       p.get("name") == "imputation_sensitivity" and
                       p.get("status") == "ran"
                       for o in (sens.get("outcomes") or [])
                       for p in (o.get("perturbations") or [])) else "",
                   sens.get("alpha")))


def gate_7_no_upgrade(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """No sentence upgrades an association into a mechanism."""
    hits = []
    for i, line in enumerate(ctx["report_text"].splitlines(), 1):
        low = line.lower()
        if any(m in low for m in DISCLAIMER_MARKERS):
            continue
        for pattern, why in FORBIDDEN:
            m = re.search(pattern, line, flags=re.IGNORECASE)
            if m:
                hits.append({"line": i, "phrase": m.group(0), "why": why,
                             "text": line.strip()[:160]})
    if hits:
        return gate(7, "no association-to-mechanism upgrade", "FAIL",
                    "%d forbidden construction(s) survive in the report." % len(hits),
                    ["line %d: %r -- %s" % (h["line"], h["phrase"], h["why"])
                     for h in hits[:8]],
                    "replace each with association language, or quote it inside a "
                    "disclaimer so the scanner can tell the difference.")
    return gate(7, "no association-to-mechanism upgrade", "PASS",
                "no forbidden construction appears outside a disclaimer (%d patterns "
                "checked across %d lines)."
                % (len(FORBIDDEN), len(ctx["report_text"].splitlines())))


def gate_8_unknowns(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Every field without evidence is written AUTHOR_INPUT_NEEDED, not invented.

    A never-automatic flag answered through the answers file carries a
    `resolved` record (who decided, when, and why); answered questions are no
    longer unknowns, and only the unanswered ones count against this gate.
    """
    inf = ctx["inferential"] or {}
    run = ctx["cleaning_run"] or {}
    report = ctx["report_text"]
    unit_missing = not (inf.get("unit_of_analysis") or {}).get("unit_key")
    all_flags = run.get("never_automatic_flags") or []
    held = [f for f in all_flags if not f.get("resolved")]
    resolved = [f for f in all_flags if f.get("resolved")]
    has_appendix_b = bool(re.search(r"^##\s+Appendix B\.", report, re.M))
    has_marker = "AUTHOR_INPUT_NEEDED" in report

    issues = []
    if unit_missing and not has_marker:
        issues.append("the independent unit is unknown but the report does not say so")
    if held and not has_marker:
        issues.append("%d withheld decision(s) are not flagged in the report" % len(held))
    if (unit_missing or held) and not has_appendix_b:
        issues.append("Appendix B (open questions) is missing")
    if issues:
        return gate(8, "unknowns flagged", "FAIL",
                    "the run has %d known unknown(s) and they are not all flagged."
                    % (int(unit_missing) + len(held)),
                    issues,
                    "add AUTHOR_INPUT_NEEDED for each unknown and list it in "
                    "Appendix B.")
    if resolved and not has_marker:
        # answered questions carry their own provenance; the marker may still be
        # present for other reasons, but a resolution without any marker is fine
        pass
    return gate(8, "unknowns flagged", "PASS",
                "every unknown the pipeline detected is written AUTHOR_INPUT_NEEDED "
                "and repeated in Appendix B (%s)."
                % ("unit undeclared" if unit_missing
                   else "%d withheld decision(s)" % len(held) if held
                   else "%d decision(s) were answered via the answers file and "
                        "carry their provenance; no unknowns remain"
                        % len(resolved) if resolved
                   else "no unknowns detected"))


# --------------------------------------------------------------- structural

def structural_checks(ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Checks that are not one of the 8 gates but still block the label."""
    out: List[Dict[str, Any]] = []
    report = ctx["report_text"]

    missing = [name for name, pat in REQUIRED_SECTIONS
               if not re.search(pat, report, re.M)]
    out.append({"check": "required sections", "status": "FAIL" if missing else "PASS",
                "detail": ("missing: %s" % ", ".join(missing)) if missing
                          else "all %d required sections present" % len(REQUIRED_SECTIONS)})

    caveats = ctx["caveats"]
    out.append({"check": "at least one caveat", "status": "PASS" if caveats else "FAIL",
                "detail": "%d caveat(s)" % len(caveats) if caveats
                          else "no caveat was produced"})

    decisions = (ctx["decisions"] or {}).get("decisions") or []
    incomplete = []
    for d in decisions:
        body = d.get("body") or {}
        if not d.get("title") or not d.get("caption"):
            incomplete.append("%s: title/caption" % d.get("id"))
        for k in ("fact", "interpretation", "implication"):
            if not body.get(k):
                incomplete.append("%s: body.%s" % (d.get("id"), k))
    out.append({"check": "figure title / caption / body", "status":
                "FAIL" if incomplete else "PASS",
                "detail": ("incomplete: %s" % "; ".join(incomplete)) if incomplete
                          else "all %d figure(s) carry title, caption and a three-part "
                               "body" % len(decisions)})

    prov = (ctx["build"] or {}).get("provenance") or []
    out.append({"check": "number provenance", "status": "PASS" if prov else "FAIL",
                "detail": "%d registered claim(s) in report_build.json" % len(prov)
                          if prov else "report_build.json has no provenance records"})

    pdf = ((ctx["build"] or {}).get("pdf") or {})
    out.append({"check": "PDF delivered", "status":
                "PASS" if pdf.get("pdf_written") else "FAIL",
                "detail": ("backend %s, %s bytes" % (pdf.get("backend"),
                                                     pdf.get("bytes")))
                          if pdf.get("pdf_written")
                          else "no PDF was written: %s" % pdf.get("blocked_reason")})

    own = ((ctx["build"] or {}).get("self_audit") or {})
    n_forb = own.get("n_forbidden")
    out.append({"check": "writer self-audit", "status":
                "PASS" if n_forb == 0 else "WARN" if n_forb is not None else "N/A",
                "detail": ("0 forbidden phrases in the writer's own scan"
                           if n_forb == 0 else
                           "%s forbidden phrase(s) in the writer's scan" % n_forb
                           if n_forb is not None else
                           "report_build.json has no self_audit block")})
    return out

# ------------------------------------------------------------- journal route

def load_routing() -> Dict[str, Any]:
    path = ROOT / "references" / "journal-reporting-standards.json"
    if not path.exists():
        return {"designs": {}, "journals": {}, "item_checks": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def infer_design(ctx: Dict[str, Any], routing: Dict[str, Any],
                 forced: str = "auto") -> Tuple[str, str, List[str]]:
    """Pick the EQUATOR checklist from the study design, or say we cannot.

    The inference reads the title, the report prose and the column names.  It is
    deliberately allowed to return `undetermined`: a wrong checklist is worse
    than an admitted unknown, because it silently changes what "complete" means.
    """
    designs = routing.get("designs") or {}
    if forced and forced != "auto":
        d = designs.get(forced)
        if not d:
            return ("undetermined", "",
                    ["unknown design id %r; known: %s"
                     % (forced, ", ".join(sorted(designs)))])
        return (forced, d.get("checklist", ""), [])

    hay = " ".join([
        str(ctx.get("title") or ""),
        str((ctx["profile"] or {}).get("source") or ""),
        " ".join(str(c) for c in ((ctx["profile"] or {}).get("columns") or {})),
        ctx["report_text"][:6000],
    ]).lower()

    def hit(token: str, text: str) -> bool:
        """Boundary-aware match, because "n = 1" is a substring of "n = 158".

        The first version of this function used a plain substring test and
        classified an iris dataset as a CARE case report on the strength of
        "n = 1" inside "n = 158".
        """
        t = token.lower().strip()
        if t in ("n = 1", "n=1"):
            return re.search(r"\bn\s*=\s*1(?![0-9])", text) is not None
        return re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])",
                         text) is not None

    hits = []
    for key, d in designs.items():
        if key == "generic":
            continue
        for token in d.get("detect") or []:
            if hit(token, hay):
                hits.append((key, token))
                break
    if len(hits) == 1:
        key = hits[0][0]
        return (key, designs[key].get("checklist", ""),
                ["no design was declared; inferred from the token %r"
                 % hits[0][1]])
    if len(hits) > 1:
        return ("generic", designs.get("generic", {}).get("checklist", ""),
                ["design is ambiguous: tokens for %s all appear; the design must be "
                 "declared before the right EQUATOR checklist can be chosen"
                 % ", ".join("%s (%r)" % (k, t) for k, t in hits)])
    return ("generic", designs.get("generic", {}).get("checklist", ""),
            ["no design statement was found in the data or the report; pass --design "
             "to select the EQUATOR checklist that applies"])


def journal_requirements(ctx: Dict[str, Any], journal: str,
                         routing: Dict[str, Any], design_id: str) -> Dict[str, Any]:
    journals = routing.get("journals") or {}
    j = journals.get(journal) or journals.get("nature") or {}
    designs = routing.get("designs") or {}
    design = designs.get(design_id) or {}
    items = list(design.get("required_statistical_items") or [])
    for extra in ("data_availability", "code_availability", "funding",
                  "conflict_of_interest", "author_contributions"):
        if extra in (j.get("author_supplied_items") or []) and extra not in items:
            items.append(extra)

    checks = routing.get("item_checks") or {}
    derivable = {"n_and_unit", "n_per_arm", "effect_size_ci", "missing_data",
                 "multiplicity", "reproducibility_statement"}
    rows = []
    for item in items:
        if item in derivable:
            status = "CHECKED BY THE 8 GATES"
        else:
            status = "AUTHOR INPUT NEEDED"
        rows.append({"item": item, "status": status,
                     "how": checks.get(item, "")})
    return {"journal": journal, "label": j.get("label", journal),
            "reporting_standards": j.get("reporting_standards", ""),
            "url": j.get("url", ""),
            "checklist": design.get("checklist", ""),
            "checklist_url": design.get("url", ""),
            "design": design_id,
            "mandatory_statistical_gates": j.get("mandatory_statistical_gates",
                                                 [1, 2, 3, 4, 5, 6, 7, 8]),
            "items": rows}


# --------------------------------------------------------------- rendering

def render_markdown(result: Dict[str, Any]) -> str:
    L: List[str] = []
    L.append("# Final audit -- %s" % result["title"])
    L.append("")
    L.append("_Generated %s by scripts/final_audit.py from the artifacts on disk. "
             "This audit reads the report; it does not trust it._"
             % result["generated"])
    L.append("")
    L.append("**Verdict: %s**" % result["verdict"])
    L.append("")
    if result["blocking"]:
        L.append("Blocking issues:")
        for b in result["blocking"]:
            L.append("- %s" % b)
    else:
        L.append("No mandatory gate failed. Warnings below are disclosed limits, not "
                 "hidden failures.")
    L.append("")
    L.append("| Gate | Name | Status |")
    L.append("|---|---|---|")
    for g in result["gates"]:
        L.append("| %s | %s | **%s** |" % (g["gate"], g["name"], g["status"]))
    L.append("")
    for g in result["gates"]:
        L.append("## Gate %s -- %s   [%s]" % (g["gate"], g["name"], g["status"]))
        L.append("")
        L.append("- **Evidence**: %s" % g["evidence"])
        if g["issues"]:
            L.append("- **Issues**:")
            for it in g["issues"]:
                L.append("  - %s" % it)
        if g["fix"] and g["status"] in ("FAIL", "WARN"):
            L.append("- **Fix**: %s" % g["fix"])
        L.append("")
    L.append("## Structural checks")
    L.append("")
    L.append("| Check | Status | Detail |")
    L.append("|---|---|---|")
    for c in result["structural"]:
        L.append("| %s | **%s** | %s |" % (c["check"], c["status"], c["detail"]))
    L.append("")
    j = result["journal"]
    L.append("## Journal routing")
    L.append("")
    L.append("- **Journal family**: %s" % j["label"])
    L.append("- **Reporting standards**: %s" % j["reporting_standards"])
    L.append("- **Checklist for this design**: %s" % (j["checklist"] or "not determined"))
    L.append("- **Design inferred**: `%s`" % j["design"])
    if result["design_notes"]:
        for n in result["design_notes"]:
            L.append("  - %s" % n)
    L.append("")
    L.append("| Reporting item | Status | How it is evidenced |")
    L.append("|---|---|---|")
    for it in j["items"]:
        L.append("| %s | %s | %s |" % (it["item"], it["status"], it["how"]))
    L.append("")
    if result["mandatory_failures"]:
        L.append("## What must change before this is submitted")
        L.append("")
        for i, f in enumerate(result["mandatory_failures"], 1):
            L.append("%d. **Gate %s (%s)** -- %s" % (i, f["gate"], f["name"], f["fix"]))
        L.append("")
    return "\n".join(L).rstrip() + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="audit a finished data-master report")
    ap.add_argument("--outdir", required=True, help="outputs directory")
    ap.add_argument("--journal", default="auto",
                    choices=["auto", "nature", "nejm", "science", "lancet"])
    ap.add_argument("--design", default="auto",
                    help="design id from journal-reporting-standards.json, or auto")
    ap.add_argument("--template", default="nature",
                    choices=["nature", "standard", "executive"],
                    help="relaxation level for gates 3-6")
    ap.add_argument("--require-report", action="store_true",
                    help="exit 2 instead of 1 when report.md is missing")
    ap.add_argument("--json", action="store_true", help="print the result as JSON")
    args = ap.parse_args(argv)

    outdir = Path(args.outdir)
    report_path = outdir / "report.md"
    audit_dir = outdir / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)

    if not report_path.exists():
        msg = "report.md not found in %s" % outdir
        if args.require_report:
            print(msg, file=sys.stderr)
            return 2
        report_text = ""
    else:
        report_text = report_path.read_text(encoding="utf-8")

    build = load_json(outdir / "report_build.json") or {}
    ctx: Dict[str, Any] = {
        "title": build.get("title") or outdir.name,
        "report_text": report_text,
        "profile": load_json(outdir / "analysis" / "profile.json") or {},
        "descriptive": load_json(outdir / "analysis" / "descriptive.json") or {},
        "inferential": load_json(outdir / "analysis" / "inferential.json") or {},
        "sensitivity": load_json(outdir / "analysis" / "sensitivity.json") or {},
        "decisions": load_json(outdir / "analysis" / "chart_decisions.json") or {},
        "cleaning_run": load_json(outdir / "cleaned" / "cleaning_run.json") or {},
        "build": build,
        "caveats": build.get("caveats") or [],
    }
    if not ctx["inferential"] and not ctx["descriptive"]:
        print("audit cannot run: neither inferential.json nor descriptive.json exists "
              "in %s" % (outdir / "analysis"), file=sys.stderr)
        return 2

    gates = [gate_1_n_unit(ctx), gate_2_missing(ctx), gate_3_effect_size(ctx),
             gate_4_uncertainty(ctx), gate_5_multiplicity(ctx), gate_6_sensitivity(ctx),
             gate_7_no_upgrade(ctx), gate_8_unknowns(ctx)]
    structural = structural_checks(ctx)

    routing = load_routing()
    design_id, checklist, design_notes = infer_design(ctx, routing, args.design)
    if checklist:
        design_notes = design_notes + ["checklist selected: %s" % checklist]

    journal_name = args.journal
    if journal_name == "auto":
        hay = (ctx["title"] + " " + report_text[:3000]).lower()
        journal_name = next((j for j in ("nejm", "lancet", "science", "nature")
                             if j in hay), "nature")
        design_notes.append("journal resolved to %s" % journal_name)
    journal = journal_requirements(ctx, journal_name, routing, design_id)

    relaxed = set() if args.template == "nature" else {3, 4, 5, 6}
    mandatory = [g for g in gates
                 if g["gate"] not in relaxed
                 and g["status"] == "FAIL"]
    blocking = ["Gate %s (%s): %s" % (g["gate"], g["name"],
                                      "; ".join(g["issues"]) or g["evidence"])
                for g in mandatory]
    for c in structural:
        if c["status"] == "FAIL":
            blocking.append("%s: %s" % (c["check"], c["detail"]))

    result = {
        "title": ctx["title"],
        "generated": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z"),
        "template": args.template,
        "verdict": "NOT SUBMISSION-READY" if blocking else "SUBMISSION-READY",
        "gates": gates,
        "structural": structural,
        "journal": journal,
        "design_notes": design_notes,
        "mandatory_failures": mandatory,
        "blocking": blocking,
        "relaxed_gates": sorted(relaxed),
        "n_pass": sum(1 for g in gates if g["status"] == "PASS"),
        "n_warn": sum(1 for g in gates if g["status"] == "WARN"),
        "n_fail": sum(1 for g in gates if g["status"] == "FAIL"),
        "n_na": sum(1 for g in gates if g["status"] == "N/A"),
    }

    (audit_dir / "final_audit.md").write_text(render_markdown(result),
                                               encoding="utf-8")
    (audit_dir / "final_audit.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    else:
        print("final_audit: %s" % result["verdict"])
        for g in gates:
            print("  Gate %s %-38s %s" % (g["gate"], g["name"], g["status"]))
            for it in g["issues"][:3]:
                print("      - %s" % it)
        print("  structural: %d/%d pass" % (
            sum(1 for c in structural if c["status"] == "PASS"), len(structural)))
        print("  checklist: %s (%s)" % (journal["checklist"] or "undetermined",
                                        journal["label"]))
        print("  wrote %s" % (audit_dir / "final_audit.md"))
    return 1 if mandatory or any(c["status"] == "FAIL" for c in structural) else 0


if __name__ == "__main__":
    raise SystemExit(main())
