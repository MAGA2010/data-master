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
