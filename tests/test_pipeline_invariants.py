"""Regression tests for the guarantees that are easy to break silently.

Run:  python tests/test_pipeline_invariants.py

No third-party test runner is required. The skill is downloaded by people who
have pandas and nothing else, and a suite that needs a plugin before it can
check anything is a suite that will not be run.

Every test here pins a decision that was made for a reason. Several of them
exist because the opposite behaviour once shipped: the cleaning stage used to
read the raw CSV with pandas defaults, which turned the postcode "02134" into
2134 and merged it with the genuinely different postcode "2134". The plan said
"keep as text", the report showed no change, and the file no longer held the
evidence that any decision had been made at all.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import dm_types                     # noqa: E402
import execute_cleaning as ec        # noqa: E402
import stats_inferential as si       # noqa: E402
import assemble_profile_report as apr  # noqa: E402
import pipeline_state as ps          # noqa: E402
import run_pipeline as rp            # noqa: E402

TRAPS = ROOT / "examples" / "column_traps"
TRAPS_CSV = TRAPS / "traps_dirty.csv"
TRAPS_OUT = TRAPS / "outputs"

_RESULTS = []


def check(name):
    def deco(fn):
        _RESULTS.append((name, fn))
        return fn
    return deco


def eq(got, want, what=""):
    assert got == want, "%s\n    got : %r\n    want: %r" % (what or "mismatch", got, want)


def _run_pipeline():
    """profile -> plan -> execute, returning the artifacts they produce."""
    out = TRAPS_OUT
    for cmd in (
        ["profile_tabular.py", "--in", str(TRAPS_CSV),
         "--out", str(out / "analysis" / "profile.json")],
        ["cleaning_plan.py", "--profile", str(out / "analysis" / "profile.json"),
         "--out", str(out / "cleaning_plan.json")],
        ["execute_cleaning.py", "--in", str(TRAPS_CSV),
         "--plan", str(out / "cleaning_plan.json"), "--out", str(out / "cleaned")],
    ):
        subprocess.run([sys.executable, str(SCRIPTS / cmd[0])] + cmd[1:],
                       check=True, capture_output=True)
    run = json.loads((out / "cleaned" / "cleaning_run.json").read_text(encoding="utf-8"))
    plan = json.loads((out / "cleaning_plan.json").read_text(encoding="utf-8"))
    return run, plan


# --------------------------------------------------------------------------
# 1. the reader contract
# --------------------------------------------------------------------------
@check("reader keeps the leading zero that pandas would eat")
def t_read_table_preserves_leading_zero():
    df = dm_types.read_table(TRAPS_CSV, read_mode="text")
    assert "02134" in set(df["postcode"]), "leading zero lost at read time"

    # the escape hatch is still available for anyone who deliberately asks for it
    inferred = dm_types.read_table(TRAPS_CSV, read_mode="infer")
    assert str(inferred["postcode"].dtype).startswith("int"), \
        "infer mode is supposed to reproduce pandas' guess"


@check("no script opens a data file behind the shared reader's back")
def t_single_reader():
    for mod in ("profile_tabular", "execute_cleaning", "validate_clean",
                "stats_descriptive", "stats_inferential", "effect_size"):
        src = (SCRIPTS / (mod + ".py")).read_text(encoding="utf-8")
        assert "pd.read_csv(src" not in src and "pd.read_csv(path" not in src, \
            "%s still calls read_csv directly; route it through dm_types.read_table" % mod


# --------------------------------------------------------------------------
# 2. the cleaning contract, on a dataset built out of known traps
# --------------------------------------------------------------------------
@check("cleaning run is byte-for-byte reproducible")
def t_reproducible():
    run, _ = _run_pipeline()
    v = run["reproducibility_check"]
    assert v["passed"] is True, "regeneration diverged: %s" % v.get("stderr", "")[:800]


@check("conversion happens only where every value parses")
def t_all_or_nothing_coercion():
    _, plan = _run_pipeline()
    coerced = {c for a in plan["auto_actions"] if a["op"] == "coerce_numeric"
               for c in a["columns"]}
    eq(coerced, {"turnover", "weight_kg"}, "auto-coerced columns")
    dated = {c for a in plan["auto_actions"] if a["op"] == "coerce_dates"
             for c in a["columns"]}
    eq(dated, {"signup_date"}, "auto-coerced date columns")


@check("all four conversion traps are held, each with evidence")
def t_four_holds():
    _, plan = _run_pipeline()
    held = {tuple(f["columns"]) for f in plan["never_automatic_flags"]
            if f["op"].startswith("coerce")}
    eq(held, {("growth_pct",), ("mostly_text",), ("postcode",), ("revenue",)},
       "held conversion columns")
    for f in plan["never_automatic_flags"]:
        if f["op"].startswith("coerce"):
            assert f.get("reason"), "a hold without evidence is just a refusal"
            assert f["default_if_silent"] == "keep_as_text", \
                "silence must leave the data exactly as it was"


@check("a held column never reaches a coercion op")
def t_holds_are_not_executed():
    run, plan = _run_pipeline()
    held = {c for f in plan["never_automatic_flags"] if f["op"].startswith("coerce")
            for c in f["columns"]}
    touched = {c for a in run["applied_ops"]
               if a["op"] in ("coerce_numeric", "coerce_dates")
               for c in a["columns"]}
    eq(touched & held, set(), "a held column was converted anyway")


# --------------------------------------------------------------------------
# 3. the values themselves
# --------------------------------------------------------------------------
@check("identifiers, currency, percents and words survive cleaning")
def t_values_survive():
    _run_pipeline()
    raw = pd.read_csv(TRAPS_CSV, dtype=str)
    cln = pd.read_csv(TRAPS_OUT / "cleaned" / "cleaned.csv", dtype=str)
    eq(set(raw["postcode"]), set(cln["postcode"]), "postcode values")
    assert cln["revenue"].str.startswith("$").all(), "currency symbol stripped"
    assert cln["growth_pct"].str.contains("%").all(), "percent sign stripped"
    assert int((~cln["mostly_text"].str.match(r"^-?[0-9.]+$")).sum()) == 24, \
        "the words in a mostly-numeric column were turned into NaN"
    eq(sorted(cln["region"].unique()), ["East", "North", "South", "West"], "region levels")


@check("the untouched-column audit passes, and is known to fail when it should")
def t_untouched_audit():
    run, _ = _run_pipeline()
    audit = run["untouched_column_audit"]
    assert audit["passed"] is True, "audit failed on a clean run: %s" % audit["violations"]
    assert audit["columns_checked"] >= 5, \
        "the audit is vacuous; it only checked %d columns" % audit["columns_checked"]

    # Negative control: replay the old, broken reader and require the audit to
    # catch it. A check that has never failed is not known to work.
    raw = pd.read_csv(TRAPS_CSV, dtype=str)
    broken = pd.read_csv(TRAPS_CSV)          # pandas defaults: 02134 -> 2134
    res = ec.audit_untouched_columns(raw, broken, ec.converting_columns(run["applied_ops"]))
    assert res["passed"] is False, "the audit failed to notice a destroyed identifier"
    assert "postcode" in res["columns_violating"], \
        "the audit flagged %s instead of the column that actually broke" % res["columns_violating"]


@check("case-variant merging is fully reversible")
def t_case_merge_is_reversible():
    """A truncated map cannot undo the merge, so a truncated map is data loss."""
    words = ["north", "south", "east", "west", "zone_a", "zone_b", "site 7", "site 9"]
    levels = []
    for w in words:
        for v in {w, w.upper(), w.capitalize(), w.title()}:
            levels.append(v)
    s = pd.Series(levels, dtype="str")
    merged, info = dm_types.fold_case_map(s)

    groups = info["merged_groups"]
    listed = {v for g in groups for v in g["variants"]}
    raw_levels = set(s.unique())
    assert raw_levels <= listed, \
        "the merge map omits %r; a level with no entry cannot be restored" % (
            sorted(raw_levels - listed)[:5],)
    for g in groups:
        assert g["canonical"] in g["variants"], \
            "group %r lists variants without its canonical form" % g["canonical"]

    # the canonical rule must actually reproduce the merged column
    expected = {v: g["canonical"] for g in groups for v in g["variants"]}
    got = set(merged.astype(str).unique())
    assert got == {g["canonical"] for g in groups}, \
        "the merged column does not match the map it published"
    eq(len(got), info["n_after_casefold"], "levels after casefold")


@check("downstream stages reuse the recorded dtypes")
def t_manifest_round_trip():
    _run_pipeline()
    df, prov = dm_types.load_cleaned(TRAPS_OUT / "cleaned" / "cleaned.csv")
    eq(prov["dtype_source"], "cleaning_run.json", "dtype provenance")
    assert "02134" in set(df["postcode"].astype(str)), \
        "the postcode lost its zero again on the way into the analysis"
    assert dm_types.is_numeric(df["weight_kg"].dtype), \
        "a coerced measurement came back as %s" % df["weight_kg"].dtype
    assert dm_types.is_numeric(pd.array([1, 2], dtype="Float64").dtype), \
        "pandas nullable Float64 is not recognised as numeric"

    # with no manifest, the guess has to be labelled as a guess
    with tempfile.TemporaryDirectory() as td:
        lonely = Path(td) / "cleaned.csv"
        pd.read_csv(TRAPS_OUT / "cleaned" / "cleaned.csv").to_csv(lonely, index=False)
        _df, prov2 = dm_types.load_cleaned(lonely)
        assert prov2["dtype_source"].startswith("pandas inference"), prov2
        assert prov2.get("warning"), "an unmanifested read has to say so"

# --------------------------------------------------------------------------
# 4. statistics
# --------------------------------------------------------------------------
@check("omega^2 never exceeds eta^2, and matches its own formula")
def t_omega_squared():
    rng = np.random.default_rng(0)
    cases = [
        [rng.normal(0, 1, 60) for _ in range(4)],                  # null
        [rng.normal(m, 1, 60) for m in (0, 1, 2, 3)],              # large effect
        [rng.normal(0, 1, 80), rng.normal(0, 6, 80),
         rng.normal(0, 1, 80), rng.normal(0, 1, 80)],               # unequal variance
        [rng.normal(0, 0.001, 50) for _ in range(3)],              # tiny spread
    ]
    for groups in cases:
        groups = [np.asarray(g, dtype=float) for g in groups]
        res = si.variance_effects(groups, n_boot=200)
        k, n = len(groups), len(np.concatenate(groups))
        ss_b, ss_w, _ = si._omega2_from(groups)
        ms_w = ss_w / (n - k)
        want = (ss_b - (k - 1) * ms_w) / (ss_b + ss_w + ms_w)
        assert abs(res["omega_squared"] - want) < 5e-7, \
            "omega^2 reported as %s, the formula gives %s" % (res["omega_squared"], want)
        assert res["omega_squared"] <= res["eta_squared"] + 1e-12, \
            "omega^2 (%s) exceeded eta^2 (%s); the correction term is (k-1)*MS_w, not MS_w" % (
                res["omega_squared"], res["eta_squared"])


@check("normality never vetoes a parametric test at n >= 30")
def t_normality_is_not_a_veto():
    """Shapiro has near-100% power at large n, so gating on it there throws away
    the more powerful test in most real datasets. Below 30 it does gate."""
    from scipy import stats as sps

    rng = np.random.default_rng(11)
    big_a = np.exp(rng.normal(0, 1.4, 200))        # strongly non-normal, large n
    big_b = np.exp(rng.normal(0.5, 1.4, 200))
    small_a = np.exp(rng.normal(0, 1.4, 12))       # non-normal, small n
    small_b = np.exp(rng.normal(0.5, 1.4, 12))

    assert sps.shapiro(big_a).pvalue < 0.01, "the large sample was not actually skewed"
    assert sps.shapiro(small_a).pvalue < 0.05, "the small sample was not skewed"

    big = si.two_group_numeric(big_a, big_b, "a", "b", alpha=0.05)
    assert "mann" not in big["method"].lower(), \
        "n=200 skewed data was pushed onto a rank test: %s" % big["method"]
    for key in ("normality_a", "normality_b"):
        g = big["assumptions"][key]
        assert g["passes"] is False, "the sample was supposed to fail Shapiro"
        assert g["gating"] is False, "normality gated the choice at n >= 30"

    small = si.two_group_numeric(small_a, small_b, "a", "b", alpha=0.05)
    assert "mann" in small["method"].lower(), \
        "n=12 skewed data kept a parametric test: %s" % small["method"]


@check("unequal variance routes to Welch, not to abandonment")
def t_welch_instead_of_giving_up():
    rng = np.random.default_rng(5)
    a = rng.normal(0, 1, 80)
    b = rng.normal(0, 5, 80)                        # variance ratio 25
    res = si.two_group_numeric(a, b, "a", "b", alpha=0.05)
    assert "welch" in res["method"].lower(), \
        "wildly unequal variances should route to Welch, got %s" % res["method"]
    same = rng.normal(0, 1, 80)
    res2 = si.two_group_numeric(a, same, "a", "same", alpha=0.05)
    assert "welch" not in res2["method"].lower(), \
        "equal variances should keep the pooled test, got %s" % res2["method"]


@check("every comparison records what it rejected, and why")
def t_provenance_present():
    path = ROOT / "examples" / "iris" / "outputs" / "analysis" / "inferential.json"
    if not path.exists():
        raise AssertionError("run the iris example before this test "
                             "(examples/iris/README.md)")
    d = json.loads(path.read_text(encoding="utf-8"))
    assert d["tests"], "no tests were produced"
    for t in d["tests"]:
        # A test that could not be run owes the reader a reason, not a p-value.
        # What it must never do is look like a result.
        if not t.get("estimable", True):
            assert t.get("reason"), \
                "%s is not estimable but says nothing about why" % t.get("outcome")
            assert t.get("p_raw") is None, \
                "%s reports p_raw=%r while calling itself not estimable" % (
                    t.get("outcome"), t.get("p_raw"))
            continue
        assert t["rejected_alternatives"], "no rejected alternatives recorded"
        for r in t["rejected_alternatives"]:
            assert r.get("reason"), "an alternative rejected without a reason"
        assert "p_raw" in t and "p_adjusted" in t, "multiplicity not reported"
        es = t["effect_sizes"]
        assert any(k.endswith("ci95") for k in es), \
            "an effect size was reported without an interval: %s" % list(es)
        assert t.get("rule_source"), "no rule provenance"


@check("one NaN cannot take down the whole multiplicity family")
def t_nan_does_not_poison_correction():
    """np.argsort sorts NaN last, then the cumulative min walks it backwards.

    So a single degenerate comparison used to turn every BH-adjusted p-value in
    the family into NaN. The correction is a Nature gate; it must degrade to a
    smaller family that is still correct, never to a wall of NaN.
    """
    good = [9.2e-24, 9.3e-19, 9.2e-70, 3.9e-65]
    poisoned = si.correct_pvalues(good + [float("nan"), None], "BH", 0.05)
    clean = si.correct_pvalues(good, "BH", 0.05)

    eq(poisoned["family_size"], len(good), "family size after dropping non-finite")
    eq(poisoned["n_dropped_non_finite"], 2, "dropped count must be reported, not hidden")
    for a, b in zip(poisoned["adjusted"], clean["adjusted"]):
        assert np.isfinite(a), "an adjusted p-value came back NaN: %r" % poisoned["adjusted"]
        assert abs(a - b) < 1e-30, \
            "dropping a NaN changed the surviving corrections (%r vs %r)" % (a, b)
    # and the NaN must not have been silently promoted to 1.0 either
    assert all(a < 1.0 for a in poisoned["adjusted"])


@check("a group with no within-group variation is not estimable, not NaN")
def t_zero_variance_group_is_reported():
    """Welch's weights are n/s^2, so a constant group gives 0/0.

    That used to surface as p_raw=NaN, which then joined the family above.
    """
    a = np.array([1.0, 2.0, 3.0, 2.5, 3.5, 2.2, 2.8])
    b = np.full(7, 9.0)                                  # constant -> sd 0
    res = si.k_group_numeric({"a": a, "b": b})
    assert res.get("estimable") is False, "a constant group was tested anyway"
    assert res.get("p_raw") is None, "not-estimable must be None, got %r" % res.get("p_raw")
    assert "variance is zero" in res.get("reason", ""), \
        "the reason does not name the cause: %r" % res.get("reason")

    # a constant outcome across every row is degenerate in the same way
    flat = si.k_group_numeric({"a": np.array([2.0] * 6), "b": np.array([3.0] * 6)})
    assert flat.get("estimable") is False, "a constant outcome was tested anyway"


@check("a restatement of the grouping variable is not offered as evidence")
def t_tautological_outcome_is_skipped():
    """species_code is a relabelling of species.

    Testing it against species has the answer built into the question, and
    including it inflates the family that the correction is applied to.
    """
    d = json.loads((ROOT / "examples" / "iris" / "outputs" / "analysis"
                    / "inferential.json").read_text(encoding="utf-8"))
    by_outcome = {t.get("outcome"): t for t in d["tests"]}
    assert "species_code" in by_outcome, "the tautological outcome vanished instead of being explained"
    t = by_outcome["species_code"]
    assert t.get("estimable") is False, "a restatement of the grouping variable was tested"
    assert t.get("p_raw") is None, "the tautology reported a p-value: %r" % t.get("p_raw")
    assert "determined by the grouping variable" in t.get("reason", ""), \
        "the reason does not explain itself: %r" % t.get("reason")

    # and the family that is actually corrected must not contain it
    fam = d["multiple_comparisons"]["primary_family"]
    assert fam["family_size"] == 4, \
        "the corrected family should hold the 4 real outcomes, got %r" % fam["family_size"]
    assert fam["n_dropped_non_finite"] == 0, \
        "nothing should have needed dropping once the tautology is excluded"

# ---------------------------------------------------------------- new stages

@check("Welch ANOVA reports a real denominator df")
def test_welch_anova_dof():
    """Regression: df_denom was 0.0 on every Welch ANOVA.

    The old formula normalised weights in a way that made the denominator sum
    collapse, so the report printed "df = 0.0" beside p = 1e-70.  The correct
    Satterthwaite form must agree with statsmodels.
    """
    rng = np.random.default_rng(0)
    a = rng.normal(0.0, 1.0, 52)
    b = rng.normal(2.0, 3.0, 53)
    c = rng.normal(3.5, 2.0, 53)
    got = si._welch_anova_dof([a, b, c])
    assert got is not None, "Welch ANOVA returned no denominator df"
    assert got > 1.0, "denominator df collapsed to %r" % got

    try:
        from statsmodels.stats.oneway import anova_oneway
    except Exception:
        return                                  # statsmodels is optional here
    want = float(anova_oneway([a, b, c], use_var="unequal").df_denom)
    assert abs(float(got) - want) < 1e-2, \
        "Welch df disagrees with statsmodels: got %.4f want %.4f" % (got, want)


@check("Welch ANOVA is reported with both df and df_denom")
def test_welch_reports_both_df():
    d = json.loads((ROOT / "examples" / "iris" / "outputs" / "analysis"
                    / "inferential.json").read_text(encoding="utf-8"))
    welch = [t for t in d["tests"] if "Welch" in str(t.get("method"))]
    assert welch, "iris no longer exercises the Welch branch"
    for t in welch:
        eq(t.get("dof"), 2, "%s numerator df" % t["outcome"])
        assert t.get("dof_denom") not in (None, 0, 0.0), \
            "%s reports df_denom=%r" % (t["outcome"], t.get("dof_denom"))
        assert t["dof_denom"] > 1, \
            "%s df_denom=%r is not a plausible Satterthwaite df" % (
                t["outcome"], t["dof_denom"])


@check("the writer and the auditor share one forbidden-phrase list")
def test_forbidden_lists_match():
    import assemble_report as ar
    import final_audit as fa
    eq([p for p, _ in ar.FORBIDDEN], [p for p, _ in fa.FORBIDDEN],
       "assemble_report and final_audit disagree about what is forbidden")
    eq(list(ar.DISCLAIMER_MARKERS), list(fa.DISCLAIMER_MARKERS),
       "assemble_report and final_audit disagree about disclaimer markers")


@check("the audit fails a report that upgrades association to mechanism")
def test_audit_catches_upgrade():
    import final_audit as fa
    ctx = {"report_text": "Species drives petal length in this sample.\n",
           "inferential": {}, "descriptive": {}, "decisions": {},
           "cleaning_run": {}, "build": {}, "caveats": []}
    g = fa.gate_7_no_upgrade(ctx)
    eq(g["status"], "FAIL", "the audit did not catch a causal upgrade")


@check("disclaimer lines are not counted as upgrades")
def test_audit_skips_disclaimers():
    import final_audit as fa
    ctx = {"report_text": ("A claim that species drives petal length is not available "
                           "from this data.\n"),
           "inferential": {}, "descriptive": {}, "decisions": {},
           "cleaning_run": {}, "build": {}, "caveats": []}
    eq(fa.gate_7_no_upgrade(ctx)["status"], "PASS",
       "a disclaimer was reported as a violation")


@check("design routing does not match n = 1 inside n = 158")
def test_design_routing_boundary():
    import final_audit as fa
    routing = fa.load_routing()
    ctx = {"title": "Iris morphometrics", "profile": {"source": "iris.csv",
                                                       "columns": {"a": {}, "b": {}}},
           "report_text": "n = 158 rows, three species."}
    design, checklist, notes = fa.infer_design(ctx, routing)
    assert design != "case_report", \
        "an iris table was routed to CARE because 'n = 1' matched 'n = 158'"
    eq(design, "generic", "an undeclared design should route to generic")
    assert "AUTHOR_INPUT_NEEDED" in checklist, \
        "the generic checklist must say the design checklist is missing: %r" % checklist


@check("a dataset with a declared design routes to its EQUATOR checklist")
def test_design_routing_positive():
    import final_audit as fa
    routing = fa.load_routing()
    ctx = {"title": "A randomised, double-blind trial of X",
           "profile": {"source": "trial.csv", "columns": {"arm": {}}},
           "report_text": "Participants were randomised 1:1 to placebo or drug."}
    design, checklist, _ = fa.infer_design(ctx, routing)
    eq(design, "randomized_trial", "a trial was not routed to CONSORT")
    assert "CONSORT" in checklist, "checklist was %r" % checklist


@check("the delivered iris report carries a real PDF and a complete audit")
def test_iris_deliverables():
    out = ROOT / "examples" / "iris" / "outputs"
    pdf = out / "report.pdf"
    assert pdf.exists(), "report.pdf was not written"
    assert pdf.stat().st_size > 20_000, "report.pdf is suspiciously small"
    build = json.loads((out / "report_build.json").read_text(encoding="utf-8"))
    assert build["pdf"]["pdf_written"] is True, "report_build says the PDF was not written"
    eq(build["pdf"]["backend"], "reportlab", "the PDF backend changed unexpectedly")
    assert build["self_audit"]["n_forbidden"] == 0, \
        "the writer's own scan found forbidden phrasing: %s" % build["self_audit"]
    audit = json.loads((out / "audit" / "final_audit.json").read_text(encoding="utf-8"))
    eq(audit["n_fail"], 1, "the iris run should fail exactly gate 1 (unit undeclared)")
    eq(audit["gates"][0]["status"], "FAIL", "gate 1 should be the failing gate")
    eq(audit["structural"][0]["status"], "PASS", "structural checks should pass")


@check("every figure decision has a title, a caption and a three-part body")
def test_figure_three_part_contract():
    d = json.loads((ROOT / "examples" / "iris" / "outputs" / "analysis"
                    / "chart_decisions.json").read_text(encoding="utf-8"))
    assert d["decisions"], "no figure decisions to check"
    for dec in d["decisions"]:
        for key in ("title", "caption"):
            assert dec.get(key), "%s has no %s" % (dec.get("id"), key)
        for key in ("fact", "interpretation", "implication"):
            assert (dec.get("body") or {}).get(key), \
                "%s body.%s is empty" % (dec.get("id"), key)
        assert dec.get("rejected"), \
            "%s records no rejected chart alternative" % dec.get("id")

# --------------------------------------------------------- modality profilers

def _run(script: str, *args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)],
                          capture_output=True, text=True, timeout=180)


@check("the router separates every supported modality")
def test_router_modalities():
    import shutil
    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "in"
        d.mkdir()
        shutil.copy(ROOT / "examples" / "iris" / "iris_dirty.csv", d / "table.csv")
        shutil.copy(ROOT / "examples" / "timeseries" / "sensor_log.csv", d / "series.csv")
        shutil.copy(ROOT / "examples" / "text" / "corpus" / "run_a.txt", d / "note.txt")
        shutil.copy(ROOT / "examples" / "media" / "images" / "scene.png", d / "photo.png")
        shutil.copy(ROOT / "examples" / "geo" / "stations.geojson", d / "sites.geojson")
        out = Path(td) / "route.json"
        p = _run("route_input.py", "--in", d, "--deep", "--out", out)
        eq(p.returncode, 0, "router failed: %s" % (p.stderr or p.stdout))
        doc = json.loads(out.read_text(encoding="utf-8"))
        eq(doc["by_modality"], {"tabular": 1, "time-series": 1, "text-corpus": 1,
                                "image-set": 1, "geospatial": 1},
           "router did not separate the modalities: %s" % doc["by_modality"])
        eq(doc["is_mixed"], True, "a mixed folder was not marked mixed")
        assert all(b["profiler"] for b in doc["plan"]), \
            "a branch was emitted without a profiler"


@check("the router reads a JSON array of records as tabular")
def test_router_json_records():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "records.json"
        p.write_text(json.dumps([{"a": 1, "b": 2}, {"a": 3, "b": 4}]), encoding="utf-8")
        out = Path(td) / "route.json"
        r = _run("route_input.py", "--in", p, "--out", out)
        eq(r.returncode, 0, r.stderr)
        doc = json.loads(out.read_text(encoding="utf-8"))
        eq(doc["files"][0]["modality"], "tabular",
           "a list of records was not routed to tabular")


@check("the time-series profiler sees gaps, repeats and a regime change")
def test_timeseries_profile():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "profile.json"
        p = _run("profile_timeseries.py",
                 "--in", ROOT / "examples" / "timeseries" / "sensor_log.csv",
                 "--out", out)
        eq(p.returncode, 0, p.stderr)
        d = json.loads(out.read_text(encoding="utf-8"))
        eq(d["time_column"], "timestamp", "wrong time column")
        ts = d["timeseries_candidate"]
        eq(ts["step_seconds"], 3600.0, "modal interval should be one hour")
        assert ts["n_gaps"] >= 1, "the six-hour dropout was not detected"
        assert ts["regime_change_suspected"] is True, \
            "the switch to 15-minute sampling was not detected"
        kinds = {f["type"] for f in d["anomalies"]["flags"]}
        assert "duplicate_timestamps" in kinds, "the retransmitted timestamp was not flagged"


@check("the text profiler sees duplicates, empty files and an encoding fallback")
def test_text_profile():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "profile.json"
        p = _run("profile_text.py", "--in", ROOT / "examples" / "text" / "corpus",
                 "--out", out)
        eq(p.returncode, 0, p.stderr)
        d = json.loads(out.read_text(encoding="utf-8"))
        kinds = {f["type"] for f in d["anomalies"]["flags"]}
        assert "duplicate_documents" in kinds, "the duplicated document was not flagged"
        assert "empty_documents" in kinds, "the empty file was not flagged"
        assert "encoding_fallback" in kinds, "the GB18030 file was not flagged"
        eq(d["corpus"]["n_documents"], 6, "document count changed")


@check("the media profiler sees a corrupt image and a re-encoded duplicate")
def test_media_profile():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "profile.json"
        p = _run("profile_media.py", "--in", ROOT / "examples" / "media" / "images",
                 "--kind", "image", "--out", out)
        eq(p.returncode, 0, p.stderr)
        d = json.loads(out.read_text(encoding="utf-8"))
        eq(d["summary"]["n_unreadable"], 1, "the corrupt JPEG was not counted")
        pairs = {(x["a"], x["b"]) for x in d["summary"]["near_duplicate_pairs"]}
        assert ("scene.png", "scene_reencoded.jpg") in pairs, \
            "the re-encoded duplicate was not found: %s" % pairs
        assert "blank.png" not in {n for pair in pairs for n in pair}, \
            "a blank frame was reported as a near-duplicate of a real image"


@check("the geospatial profiler sees out-of-range, null-island and null points")
def test_geospatial_profile():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "profile.json"
        p = _run("profile_geospatial.py",
                 "--in", ROOT / "examples" / "geo" / "stations.geojson", "--out", out)
        eq(p.returncode, 0, p.stderr)
        d = json.loads(out.read_text(encoding="utf-8"))
        kinds = {f["type"] for f in d["anomalies"]["flags"]}
        assert "out_of_range_coordinates" in kinds, "the swapped lat/lon was not flagged"
        assert "null_island" in kinds, "the (0,0) point was not flagged"
        assert "non_numeric_coordinates" in kinds, "the null coordinate was not flagged"
        eq(d["summary"]["n_features_invalid"], 1, "null-coordinate feature count changed")


@check("group selection prefers a human label over an identifier or code column")
def test_group_selection_rejects_code_columns():
    profile = {
        "columns": {
            "species": {"missing_pct": 0.0,
                        "residual_case_variants_post_hygiene": {
                            "n_after_casefold": 3}},
            "species_code": {"missing_pct": 0.0},
        },
        "group_candidate": {"candidates": [
            {"column": "species_code", "n_unique": 3},
            {"column": "species", "n_unique": 9},
        ]},
    }
    eq(rp.choose_group(profile), "species", "the relabeling column won")


@check("state resume starts at the first stage without completed evidence")
def test_state_first_incomplete():
    with tempfile.TemporaryDirectory() as td:
        state = ps.new_state(
            {"kind": "file", "path": "x", "sha256": "0", "bytes": 0, "files": 1},
            Path(td),
            {},
            stages=["input", "route", "profile"],
        )
        ps.record_stage(state, "input", "completed", evidence=[])
        ps.record_stage(state, "route", "failed", evidence=[])
        eq(ps.first_incomplete(state), "route", "resume did not stop at the failed stage")


@check("profile-only prose states the inferential scope boundary")
def test_profile_report_scope():
    profile = json.loads(
        (ROOT / "examples" / "text" / "outputs" / "analysis"
         / "profile.json").read_text(encoding="utf-8")
    )
    text = apr.build_markdown(profile, {"plan": []}, "Text profile")
    assert "No statistical test is reported here" in text
    assert "does not clean" in text
    assert "AUTHOR_INPUT_NEEDED" in text


@check("the dependency checker does not demand packages the stage never imports")
def test_check_deps_truthful():
    p = _run("check_deps.py", "--modalities", "text-corpus,time-series,geospatial", "--json")
    eq(p.returncode, 0, "required deps reported missing: %s" % (p.stdout or p.stderr))
    d = json.loads(p.stdout)
    eq(d["missing_required"], [], "a required dependency is missing")
    for lib in ("wordcloud", "langdetect", "librosa", "rasterio"):
        assert lib not in d["deps"], \
            "%s is listed as a dependency but no script imports it" % lib


# --------------------------------------------- unit-of-analysis structure

def _clustered_frame(seed=7):
    """30 units x 3 arms x 4 replicate rows, one real effect."""
    rng = np.random.default_rng(seed)
    n_per, reps = 30, 4
    return pd.DataFrame({
        "pid": np.repeat(np.arange(n_per * 3), reps),
        "arm": np.repeat(np.array(["ctrl", "low", "high"]), [n_per * reps]),
        "y": np.repeat(np.repeat(np.array([0.0, 0.4, 1.0]), [n_per]), reps)
            + np.repeat(rng.normal(0, 1.0, n_per * 3), reps)
            + rng.normal(0, 0.3, n_per * 3 * reps),
    })


@check("repeated rows within units move the primary analysis to the unit level")
def test_clustered_runs_at_unit_level():
    with tempfile.TemporaryDirectory() as td:
        csv = Path(td) / "clustered.csv"
        _clustered_frame().to_csv(csv, index=False)
        out = Path(td) / "inf.json"
        p = _run("stats_inferential.py", "--clean", csv, "--out", out,
                 "--group", "arm", "--unit-key", "pid")
        eq(p.returncode, 0, p.stderr)
        d = json.loads(out.read_text(encoding="utf-8"))
        eq(d["primary_level"], "unit", "the primary analysis stayed on rows")
        t = d["tests"][0]
        eq(t["analysis_level"], "unit", "the test record does not state its level")
        eq(t["n_total"], 90, "n should be the 90 units, not the 360 rows")
        assert d.get("secondary_row_level"), \
            "the row-level results vanished instead of being kept as a secondary"
        sec = d["secondary_row_level"]["tests"][0]
        assert sec.get("pseudoreplication_warning"), \
            "the secondary row-level test carries no inflation warning"


@check("a paired design gets paired tests, not two independent samples")
def test_paired_design_runs_paired_tests():
    rng = np.random.default_rng(3)
    n = 25
    df = pd.DataFrame({
        "pid": np.tile(np.arange(n), 2),
        "time": ["pre"] * n + ["post"] * n,
        "y": np.concatenate([rng.normal(0, 1, n), rng.normal(0.9, 1, n)])
             + np.tile(rng.normal(0, 0.8, n), 2),
    })
    with tempfile.TemporaryDirectory() as td:
        csv = Path(td) / "paired.csv"
        df.to_csv(csv, index=False)
        out = Path(td) / "inf.json"
        p = _run("stats_inferential.py", "--clean", csv, "--out", out,
                 "--group", "time", "--unit-key", "pid")
        eq(p.returncode, 0, p.stderr)
        d = json.loads(out.read_text(encoding="utf-8"))
        eq(d["primary_level"], "paired", "a paired structure was not detected")
        t = d["tests"][0]
        assert "paired" in t["method"].lower() or "Wilcoxon" in t["method"], \
            "an unpaired test was run on paired data: %r" % t["method"]
        assert t["effect_sizes"].get("cohens_dz") is not None, \
            "the paired test reports no dz effect size"


@check("units in exactly 2 of 3 groups are incomplete repeated, not paired")
def test_incomplete_repeated_classification():
    # regression: g_min == g_max == 2 used to be labelled 'paired' even with a
    # 3-level group, which the paired dispatch cannot answer
    df = pd.DataFrame({
        "pid": [0, 0, 1, 1, 2, 2, 3, 3],
        "cond": ["x", "y", "x", "z", "y", "z", "x", "z"],
        "y": np.arange(8, dtype=float),
    })
    st = si.analyze_unit_structure(df, "cond", "pid")
    eq(st["structure"], "incomplete_repeated",
       "a 2-of-3 design was misclassified as paired")


@check("gate 1 fails a declared unit whose primary analysis stays on rows")
def test_gate1_blocks_row_level_under_clustering():
    import final_audit as fa
    base_inf = {
        "tests": [{"outcome": "y", "estimable": True, "n_total": 90}],
        "unit_of_analysis": {"unit_key": "pid", "n_rows": 360, "n_units": 90,
                             "rows_per_unit": 4.0},
    }
    ctx = {"inferential": {**base_inf, "primary_level": "row"},
           "report_text": "", "descriptive": {}, "decisions": {},
           "cleaning_run": {}, "build": {}, "caveats": []}
    eq(fa.gate_1_n_unit(ctx)["status"], "FAIL",
       "declaring the unit while analysing rows passed gate 1")
    ctx["inferential"] = {**base_inf, "primary_level": "unit",
                          "unit_of_analysis": {**base_inf["unit_of_analysis"],
                                               "structure": "clustered"}}
    g = fa.gate_1_n_unit(ctx)
    eq(g["status"], "PASS", "a correct unit-level analysis failed gate 1: %s" % g["evidence"])


# ------------------------------------------------------- sensitivity suite

@check("the sensitivity suite runs leave-one-group-out and reports agreement")
def test_sensitivity_logo_and_summary():
    with tempfile.TemporaryDirectory() as td:
        csv = Path(td) / "clustered.csv"
        _clustered_frame().to_csv(csv, index=False)
        inf = Path(td) / "inf.json"
        sens = Path(td) / "sens.json"
        eq(_run("stats_inferential.py", "--clean", csv, "--out", inf,
                "--group", "arm", "--unit-key", "pid").returncode, 0, "inferential failed")
        p = _run("sensitivity_analysis.py", "--clean", csv,
                 "--inferential", inf, "--out", sens)
        eq(p.returncode, 0, p.stderr)
        d = json.loads(sens.read_text(encoding="utf-8"))
        perts = d["outcomes"][0]["perturbations"]
        logo = [x for x in perts if x["name"] == "leave_one_group_out"]
        eq(len(logo), 3, "3 groups should give 3 leave-one-out refits")
        assert all(x["status"] == "ran" for x in logo), \
            "a LOGO refit did not run: %r" % [x for x in logo if x["status"] != "ran"]
        ran = [x for x in perts if x.get("status") == "ran" and x.get("agrees") is not None]
        assert len(ran) >= 10, \
            "fewer than 10 perturbations produced a verdict for one outcome"
        s = d["summary"]
        eq(s["n_conflicting"], 0,
           "a clean 3-arm signal should not conflict: %r" % s["conflicts"])


@check("gate 6 fails without the sensitivity artifact and reads it when present")
def test_gate6_requires_sensitivity_artifact():
    import final_audit as fa
    inf = {"tests": [{"outcome": "y", "estimable": True, "p_raw": 0.01,
                      "robustness_cross_check": {"test": "Mann-Whitney U",
                                                 "p_raw": 0.02,
                                                 "agrees_with_primary": True}}]}
    report_with_a1 = "## Appendix A1. Sensitivity and stability\n"
    ctx = {"inferential": inf, "sensitivity": {}, "report_text": report_with_a1,
           "descriptive": {}, "decisions": {}, "cleaning_run": {},
           "build": {}, "caveats": []}
    g = fa.gate_6_sensitivity(ctx)
    eq(g["status"], "FAIL",
       "a rank cross-check alone must not satisfy the sensitivity gate")
    ctx["sensitivity"] = {
        "alpha": 0.05,
        "outcomes": [{"outcome": "y",
                      "perturbations": [{"name": "leave_one_group_out",
                                         "status": "ran", "agrees": True}]}],
        "summary": {"n_outcomes": 1, "n_perturbations": 1,
                    "n_agreeing": 1, "n_conflicting": 0, "conflicts": []},
    }
    g = fa.gate_6_sensitivity(ctx)
    eq(g["status"], "PASS", "a real sensitivity artifact failed gate 6: %s" % g["evidence"])
    ctx["sensitivity"]["summary"]["n_conflicting"] = 1
    ctx["sensitivity"]["summary"]["conflicts"] = [
        {"outcome": "y", "perturbation": "leave_one_group_out",
         "primary_p": 0.01, "perturbed_p": 0.20}]
    eq(fa.gate_6_sensitivity(ctx)["status"], "WARN",
       "a conflict must downgrade the gate to WARN, not pass silently")


# ----------------------------------------------------------- answers file

@check("the answers file resolves holds with provenance and rejects bad ids")
def test_answers_roundtrip():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        prof = td / "profile.json"
        eq(_run("profile_tabular.py", "--in", TRAPS_CSV, "--out", prof).returncode,
           0, "profiling the traps file failed")
        plan_path = td / "cleaning_plan.json"
        eq(_run("cleaning_plan.py", "--profile", prof, "--out", plan_path).returncode,
           0, "planning failed")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        template = td / "answers.template.json"
        assert template.exists(), \
            "no answers.template.json was written for a plan with open decisions"
        pending = json.loads(template.read_text(encoding="utf-8"))["decisions"]
        assert pending, "the template lists no decisions"
        assert all(d["allowed_actions"] for d in pending), \
            "a pending decision lists no executable action"

        # an unknown id must be rejected without applying anything
        bad = td / "bad.json"
        bad.write_text(json.dumps({"decisions": [
            {"id": "coerce_numeric@nonexistent", "action": "coerce"}]}),
            encoding="utf-8")
        p = _run("cleaning_plan.py", "--profile", prof, "--out", plan_path,
                 "--answers", bad)
        eq(p.returncode, 2, "an unknown answers id was silently accepted")
        plan2 = json.loads(plan_path.read_text(encoding="utf-8"))
        eq(plan2.get("user_decisions"), None,
           "the rejected answers run still wrote decisions into the plan")

        # a real hold, answered
        hold = next(f for f in plan["never_automatic_flags"]
                    if f["op"] == "coerce_numeric")
        good = td / "answers.json"
        good.write_text(json.dumps({"decisions": [{
            "id": hold["id"], "action": "coerce",
            "rationale": "confirmed numeric in the codebook",
            "decided_by": "test-suite"}]}), encoding="utf-8")
        p = _run("cleaning_plan.py", "--profile", prof, "--out", plan_path,
                 "--answers", good)
        eq(p.returncode, 0, p.stderr)
        plan3 = json.loads(plan_path.read_text(encoding="utf-8"))
        flag = next(f for f in plan3["never_automatic_flags"] if f["id"] == hold["id"])
        eq(flag["resolved"]["action"], "coerce", "the flag was not marked resolved")
        eq(flag["resolved"]["decided_by"], "test-suite", "the decision lost its author")
        dec = plan3["user_decisions"][0]
        assert dec["rationale"], "the decision rationale was not recorded"
        forced = [a for a in plan3["auto_actions"]
                  if a["id"] == "t-coerce-numeric"
                  and a.get("user_opt_in", {}).get("flag") == "--answers"]
        assert forced, "the answered decision produced no executable op"


@check("a changed answers file invalidates the cleaning stages, not the profile")
def test_invalidate_stages_from():
    state = ps.new_state({"kind": "file", "path": "x", "sha256": "0",
                          "bytes": 0, "files": 1}, Path("."), {},
                         stages=["input", "route", "profile", "cleaning_plan",
                                 "cleaning_execute", "report"])
    for s in ("input", "route", "profile", "cleaning_plan", "cleaning_execute"):
        ps.record_stage(state, s, "completed", evidence=[])
    stale = ps.invalidate_stages_from(state, "cleaning_plan", "answers file changed")
    eq(sorted(stale), ["cleaning_execute", "cleaning_plan", "report"],
       "invalidation touched the wrong stages (everything reading cleaned data is stale)")
    eq(state["stages"]["profile"]["status"], "completed",
       "a stage before the answers boundary was dropped")
    assert "cleaning_plan" not in state["stages"], "the stale plan stage survived"


# ------------------------------------------------------- code provenance

@check("the run records the pipeline commit it was produced by")
def test_pipeline_provenance_records_commit():
    prov = ps.pipeline_provenance(ROOT)
    commit = prov.get("git_commit")
    if commit:
        eq(len(commit), 40, "the commit hash is not a full sha1: %r" % commit)
        assert prov["git_dirty"] in (True, False), "dirty flag missing"
    else:
        assert prov.get("note"), \
            "no commit and no explanation is the worst of both worlds"


@check("the lockfile pins exact versions beside the evidence")
def test_lockfile_export():
    with tempfile.TemporaryDirectory() as td:
        path = rp.export_lockfile(Path(td))
        text = path.read_text(encoding="utf-8")
        assert "pandas==" in text, "pandas is not pinned to an exact version"
        assert "# pipeline commit:" in text, "the lockfile omits the commit line"
        for line in text.splitlines():
            if line.endswith(".txt") or line.startswith("#"):
                continue
            assert "==" in line or line.startswith("#"), \
                "an unpinned requirement leaked into the lockfile: %r" % line


# ------------------------------------------------------------- scatter band

@check("scatter panels draw the bootstrap band and the r interval")
def test_scatter_band_renders():
    import matplotlib
    matplotlib.use("Agg")
    import render_chart as rc
    rng = np.random.default_rng(5)
    n = 120
    x = rng.uniform(0, 10, n)
    df = pd.DataFrame({"a": x, "b": 0.8 * x + rng.normal(0, 1.0, n)})
    d = {"title": "a and b move together (r = 0.9)",
         "spec": {"panels": [{"x": "a", "y": "b", "n": n, "title": "b vs a (units)",
                              "statistic": "r", "value": 0.9}]}}
    out = Path(tempfile.mkdtemp()) / "scatter.png"
    res = rc.render_scatter(df, d, out)
    assert res["non_blank"], "the scatter figure rendered blank"
    assert out.stat().st_size > 8000, "the banded figure is suspiciously small"


# ----------------------------------------------- mixed models and covariates

def _incomplete_frame(seed=11):
    """30 units each observed under exactly 2 of 3 conditions, 2 reps per cell."""
    rng = np.random.default_rng(seed)
    unit_eff = rng.normal(0, 1.0, 30)
    rows = []
    for u in range(30):
        for c in rng.choice(["x", "y", "z"], size=2, replace=False):
            for _ in range(2):
                rows.append((u, c, {"x": 0.0, "y": 0.5, "z": 1.2}[c]
                             + unit_eff[u] + rng.normal(0, 0.4)))
    return pd.DataFrame(rows, columns=["pid", "cond", "y"])


@check("incomplete repeated measures get a unit random-intercept mixed model")
def test_mixed_model_incomplete():
    with tempfile.TemporaryDirectory() as td:
        csv = Path(td) / "inc.csv"
        _incomplete_frame().to_csv(csv, index=False)
        out = Path(td) / "inf.json"
        p = _run("stats_inferential.py", "--clean", csv, "--out", out,
                 "--group", "cond", "--unit-key", "pid")
        eq(p.returncode, 0, p.stderr)
        d = json.loads(out.read_text(encoding="utf-8"))
        t = d["tests"][0]
        if t.get("estimable") and "mixed model" in str(t.get("method", "")):
            eq(d["primary_level"], "unit (mixed model)",
               "a fitted mixed model did not become the primary")
            assert t["effect_sizes"].get("conditional_r2") is not None, \
                "the mixed model reports no conditional R^2"
            assert t.get("robustness_cross_check", {}).get("test"), \
                "the cell-means cross-check is missing"
        else:
            assert t.get("mixed_model_fallback_reason"), \
                "the mixed model was skipped without a recorded reason"
        assert d.get("secondary_row_level"), "no row-level secondary"


@check("a group column that is also the unit key is refused, not aggregated")
def test_group_equals_unit_key_refused():
    with tempfile.TemporaryDirectory() as td:
        csv = Path(td) / "g.csv"
        pd.DataFrame({"g": ["a", "b"] * 10, "y": np.arange(20, dtype=float)}
                     ).to_csv(csv, index=False)
        p = _run("stats_inferential.py", "--clean", csv, "--out",
                 Path(td) / "o.json", "--group", "g", "--unit-key", "g")
        eq(p.returncode, 1, "group==unit_key must exit 1")
        assert "cannot also be the grouping variable" in p.stdout + p.stderr, \
            "the refusal does not explain itself"


@check("declared covariates make the adjusted comparison the primary")
def test_ancova_covariates():
    rng = np.random.default_rng(12)
    n = 90
    cov = rng.normal(50, 10, n)
    df = pd.DataFrame({
        "arm": np.repeat(["a", "b", "c"], 30),
        "y": np.repeat([0.0, 0.4, 1.0], 30) + 0.3 * (cov - 50)
             + rng.normal(0, 0.5, n),
        "baseline": cov,
    })
    with tempfile.TemporaryDirectory() as td:
        csv = Path(td) / "anc.csv"
        df.to_csv(csv, index=False)
        out = Path(td) / "inf.json"
        p = _run("stats_inferential.py", "--clean", csv, "--out", out,
                 "--group", "arm", "--covariates", "baseline")
        eq(p.returncode, 0, p.stderr)
        d = json.loads(out.read_text(encoding="utf-8"))
        eq(d.get("covariates"), ["baseline"], "the covariates were not recorded")
        t = next(t for t in d["tests"] if t["outcome"] == "y")
        eq(t["design"], "covariate-adjusted numeric", "ANCOVA did not run")
        slopes = t["assumptions"].get("homogeneity_of_slopes") or {}
        assert slopes.get("verdict") in ("HOLDS", "VIOLATED"), slopes
        assert t.get("robustness_cross_check", {}).get("p_raw") is not None, \
            "the unadjusted comparison was not kept as the cross-check"


@check("gate 3 recognises mixed-model and ANCOVA effect sizes")
def test_gate3_accepts_new_effect_sizes():
    import final_audit as fa
    ctx = {"inferential": {"tests": [
        {"outcome": "y", "estimable": True, "n_total": 30,
         "effect_sizes": {"marginal_r2": 0.14, "conditional_r2": 0.89,
                          "fixed_effect_differences_ci95": {"b": {"ci95": [0, 1]}}}}]},
        "report_text": "", "descriptive": {}, "decisions": {},
        "cleaning_run": {}, "build": {}, "caveats": []}
    eq(fa.gate_3_effect_size(ctx)["status"], "PASS",
       "a mixed model with R^2 and coefficient intervals failed gate 3")


# ------------------------------------------------------- answers run block

@check("the answers run block fills blanks, validates values, and never overrides")
def test_answers_run_block():
    import io, contextlib
    iris_profile = ROOT / "examples" / "iris" / "outputs" / "analysis" / "profile.json"

    # invalid: unknown key and a design id that does not exist
    with tempfile.TemporaryDirectory() as td:
        ans = Path(td) / "a.json"
        ans.write_text(json.dumps(
            {"run": {"journal": "nejm", "unit_key": "species",
                     "design": "randomized_trial", "bogus": 1}}), encoding="utf-8")
        options = {"journal": "auto", "design": "auto"}
        stderr = io.StringIO()
        try:
            with contextlib.redirect_stderr(stderr):
                rp.apply_answers_run_block(str(ans), options, iris_profile)
        except SystemExit as exc:
            eq(exc.code, 2, "an invalid run block must exit 2")
            out = stderr.getvalue()
            assert "bogus" in out and "design" in out, \
                "the rejection does not name the bad keys: %r" % out
        else:
            raise AssertionError("the invalid run block was accepted")

    # valid: fills blanks only
    with tempfile.TemporaryDirectory() as td:
        ans = Path(td) / "b.json"
        ans.write_text(json.dumps(
            {"run": {"journal": "nejm", "unit_key": "species"}}), encoding="utf-8")
        options2 = {"journal": "auto", "design": "auto"}
        applied = rp.apply_answers_run_block(str(ans), options2, iris_profile)
        eq(applied, {"journal": "nejm", "unit_key": "species"},
           "the run block applied the wrong keys")
        eq(options2["journal"], "nejm", "the option was not filled")
        # an explicit value is never overridden; a blank one still is
        options3 = {"journal": "nature", "unit_key": None}
        applied3 = rp.apply_answers_run_block(str(ans), options3, iris_profile)
        eq(applied3, {"unit_key": "species"},
           "the run block must still fill blanks beside explicit values")
        eq(options3["journal"], "nature", "an explicit journal was clobbered")


@check("a decision can answer one column of a multi-column flag")
def test_answers_per_column():
    import cleaning_plan as cp
    profile = json.loads(
        (TRAPS_OUT / "analysis" / "profile.json").read_text(encoding="utf-8"))
    plan = cp.build_plan(profile, {})
    multi = next((f for f in plan["never_automatic_flags"]
                  if f["op"] == "impute_numeric" and len(f["columns"]) > 1), None)
    if multi is None:
        return  # this fixture has no multi-column imputation flag; nothing to pin
    col_a = multi["columns"][0]
    applied, errors = cp.apply_answers(plan, [
        {"id": multi["id"], "action": "median", "column": col_a,
         "rationale": "median per codebook", "decided_by": "test"},
    ], Path("answers.json"), profile)
    eq(errors, [], "a per-column decision was rejected: %r" % errors)
    flag = next(f for f in plan["never_automatic_flags"] if f["id"] == multi["id"])
    assert col_a in (flag.get("resolved_columns") or {}), "no per-column record"
    assert not flag.get("resolved"), "a partially answered flag counts as resolved"
    forced = [a for a in plan["auto_actions"]
              if a["id"] == "t-impute-median" and a["columns"] == [col_a]]
    assert forced, "the per-column decision produced no scoped op"
    _, errors2 = cp.apply_answers(plan, [
        {"id": multi["id"], "action": "mean"}], Path("answers.json"), profile)
    assert errors2, "a whole-flag answer on a partially resolved flag was accepted"


# --------------------------------------------------------- time-series stage

@check("time-series statistics carry intervals, names and n")
def test_timeseries_stats():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "ts.json"
        fig = Path(td) / "ts.png"
        prof = ROOT / "examples" / "timeseries" / "outputs" / "analysis" / "profile.json"
        args = ["--in", ROOT / "examples" / "timeseries" / "sensor_log.csv",
                "--out", out, "--fig", fig]
        if prof.exists():
            args += ["--profile", prof]
        p = _run("timeseries_analysis.py", *args)
        eq(p.returncode, 0, p.stderr)
        d = json.loads(out.read_text(encoding="utf-8"))
        assert d["estimable"], d
        st = d["stats"]
        for key in ("mann_kendall", "sen_slope", "changepoint"):
            assert st[key].get("estimable"), (key, st[key])
            assert st[key].get("method"), "%s records no method name" % key
        ci = st["sen_slope"]["ci95"]
        assert ci and ci[0] <= st["sen_slope"]["slope_per_step"] <= ci[1], \
            "the Sen slope sits outside its own interval: %r" % ci
        fig_rec = d.get("figure") or {}
        assert fig_rec.get("non_blank"), "the overview figure rendered blank"


# ------------------------------------------------------------ size gate

@check("oversized inputs are blocked with a decision, not a MemoryError")
def test_input_size_gate():
    route = {"files": [{"path": str(TRAPS_CSV)}]}
    eq(rp.input_size_gate(route, {}), None,
       "a small file must pass the gate")
    verdict = rp.input_size_gate(route, {"max_input_mb": 0.00001})
    assert verdict and verdict.startswith("WARNING"), \
        "an explicit override must warn, not block: %r" % verdict
    original = rp.DEFAULT_MAX_INPUT_MB
    try:
        rp.DEFAULT_MAX_INPUT_MB = 0.00001
        blocked = rp.input_size_gate(route, {})
    finally:
        rp.DEFAULT_MAX_INPUT_MB = original
    assert blocked and blocked.startswith("BLOCKED") and "--max-input-mb" in blocked, \
        "the default-limit block does not offer the override: %r" % blocked


def main() -> int:
    width = max(len(n) for n, _ in _RESULTS)
    failed = 0
    for name, fn in _RESULTS:
        try:
            fn()
        except AssertionError as exc:
            failed += 1
            print("FAIL  %-*s" % (width, name))
            print("      %s" % str(exc).replace("\n", "\n      "))
        except Exception as exc:
            failed += 1
            print("ERROR %-*s  %s: %s" % (width, name, type(exc).__name__, exc))
        else:
            print("ok    %s" % name)
    print("\n%d passed, %d failed, %d total"
          % (len(_RESULTS) - failed, failed, len(_RESULTS)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
