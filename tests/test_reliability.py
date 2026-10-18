"""Numerical references and negative controls for the evidence contract.

Run: python tests/test_reliability.py
Reference calculations use explicit GLS / least-squares equations, not the
pipeline's statistical dispatch or statsmodels' fitting functions.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from scipy import optimize, stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import final_audit as fa
import pipeline_state as ps
import run_pipeline as rp
import stats_descriptive as sd
import stats_inferential as si
import assemble_report as ar


def repeated_data():
    rng = np.random.default_rng(923)
    rows = []
    for unit in range(32):
        intercept = rng.normal(0, 1.3)
        for group in rng.choice(["a", "b", "c"], size=2, replace=False):
            for _ in range(2):
                rows.append((unit, group, intercept + {"a": 0, "b": .4, "c": .9}[group]
                             + rng.normal(0, .7)))
    return pd.DataFrame(rows, columns=["id", "arm", "response"])


def reference_random_intercept(frame, include_group):
    """Profile ML using V_i = sigma² (I + r 11'), Sherman-Morrison inverse.

    Each unit contributes its own covariance block. Profile beta by GLS and
    sigma² by RSS/n, then optimize the one remaining variance ratio r.
    """
    y = frame.response.to_numpy()
    columns = [np.ones(len(frame))]
    if include_group:
        columns += [(frame.arm == g).to_numpy(dtype=float) for g in ("b", "c")]
    x = np.column_stack(columns)
    indices = list(frame.groupby("id").indices.values())

    def evaluate(log_ratio):
        ratio = np.exp(log_ratio)
        xx = np.zeros((x.shape[1], x.shape[1]))
        xy = np.zeros(x.shape[1])
        yy = logdet = 0.
        for ix in indices:
            xi, yi = x[ix], y[ix]
            weight = ratio / (1 + len(ix) * ratio)
            sx, sy = xi.sum(axis=0), yi.sum()
            xx += xi.T @ xi - weight * np.outer(sx, sx)
            xy += xi.T @ yi - weight * sx * sy
            yy += yi @ yi - weight * sy * sy
            logdet += np.log1p(len(ix) * ratio)
        beta = np.linalg.solve(xx, xy)
        rss = yy - beta @ xy
        ll = -.5 * (len(y) * (np.log(2 * np.pi) + 1 + np.log(rss / len(y))) + logdet)
        return ll, beta

    fitted = optimize.minimize_scalar(lambda z: -evaluate(z)[0], bounds=(-14, 10),
                                     method="bounded", options={"xatol": 1e-10})
    return evaluate(fitted.x)


class StatisticalReferences(unittest.TestCase):
    def test_mixed_lr_matches_independent_profile_ml(self):
        frame = repeated_data()
        null_ll, _ = reference_random_intercept(frame, False)
        full_ll, beta = reference_random_intercept(frame, True)
        expected_lr = 2 * (full_ll - null_ll)
        actual = si.mixed_unit_model(frame, "arm", "response", "id")
        self.assertTrue(actual.get("estimable"), actual)
        self.assertEqual(actual["estimation"], "ML")
        self.assertAlmostEqual(actual["statistic"], expected_lr, delta=2e-4)
        self.assertAlmostEqual(actual["p_raw"], stats.chi2.sf(expected_lr, 2), delta=1e-6)
        for i, group in enumerate(("b", "c"), 1):
            estimate = actual["effect_sizes"]["fixed_effect_differences_ci95"][group]
            self.assertAlmostEqual(estimate["difference_vs_reference"], beta[i], delta=2e-4)
            self.assertTrue(fa.valid_interval(estimate["ci95"]))

    def test_nonconverged_model_is_not_reported_as_estimable(self):
        class Fit:
            converged = False
            llf = 0.
        class Model:
            def fit(self, **kwargs):
                return Fit()
        with patch("statsmodels.formula.api.mixedlm", return_value=Model()):
            actual = si.mixed_unit_model(repeated_data(), "arm", "response", "id")
        self.assertFalse(actual["estimable"])
        self.assertIn("AUTHOR_INPUT_NEEDED", actual["reason"])

    def test_failed_mixed_model_has_no_independent_cells_fallback(self):
        frame = repeated_data()
        with patch.object(si, "mixed_unit_model", return_value={
                "estimable": False, "reason": "failed fit"}):
            result = si._incomplete_repeated_tests(
                frame, frame, "arm", ["a", "b", "c"], ["response"], "id", .05)
        self.assertFalse(result[0]["estimable"])
        self.assertIsNone(result[0]["p_raw"])

    def test_paired_test_matches_difference_equations(self):
        rng = np.random.default_rng(192)
        a = rng.normal(0, 1, 40)
        b = a + rng.normal(.3, .8, 40)
        frame = pd.DataFrame({"id": np.tile(np.arange(40), 2),
                              "arm": np.repeat(["a", "b"], 40),
                              "y": np.r_[a, b]})
        result = si.paired_two_group(frame, "arm", "y", "a", "b", "id")
        diff = a - b
        se = diff.std(ddof=1) / np.sqrt(len(diff))
        expected_t = diff.mean() / se
        self.assertAlmostEqual(result["statistic"], expected_t, places=4)
        self.assertAlmostEqual(result["p_raw"], 2 * stats.t.sf(abs(expected_t), 39), places=7)

    def test_ancova_matches_matrix_partial_f_and_t_interval(self):
        rng = np.random.default_rng(292)
        group = np.repeat(["a", "b", "c"], 40)
        baseline = rng.normal(size=120)
        y = (group == "b") * .4 + (group == "c") * .9 + baseline * .7 + rng.normal(size=120)
        frame = pd.DataFrame({"arm": group, "y": y, "baseline": baseline})
        x = np.column_stack([np.ones(120), group == "b", group == "c", baseline])
        reduced = x[:, [0, 3]]
        beta = np.linalg.lstsq(x, y, rcond=None)[0]
        rss = np.sum((y - x @ beta) ** 2)
        rss0 = np.sum((y - reduced @ np.linalg.lstsq(reduced, y, rcond=None)[0]) ** 2)
        expected_f = ((rss0 - rss) / 2) / (rss / 116)
        result = si.ancova_numeric(frame, "arm", "y", ["baseline"], ["a", "b", "c"])
        self.assertTrue(result["estimable"], result)
        self.assertAlmostEqual(result["statistic"], expected_f, delta=1e-4)
        self.assertAlmostEqual(result["p_raw"], stats.f.sf(expected_f, 2, 116), places=7)
        se = np.sqrt(np.linalg.inv(x.T @ x)[1, 1] * rss / 116)
        expected_ci = beta[1] + np.array([-1, 1]) * stats.t.ppf(.975, 116) * se
        np.testing.assert_allclose(result["effect_sizes"]["adjusted_differences_ci95"]["b"]["ci95"],
                                   expected_ci, atol=1e-6)

    def test_violated_slopes_do_not_silently_fall_back(self):
        rng = np.random.default_rng(80)
        g = np.repeat(["a", "b"], 50)
        x = rng.normal(size=100)
        frame = pd.DataFrame({"g": g, "x": x,
                              "y": x * np.where(g == "a", 1, 8) + rng.normal(0, .1, 100)})
        rec = si._outcome_tests(frame, "g", ["a", "b"], ["y"], .05, "row", covariates=["x"])[0]
        self.assertFalse(rec["estimable"])
        self.assertIsNone(rec["p_raw"])

    def test_low_missingness_does_not_imply_mcar(self):
        frame = pd.DataFrame({"x": np.r_[np.nan, np.arange(99.)],
                              "category": [None] + ["a"] * 99})
        screen = sd._missing_mechanism_screen(frame)
        self.assertEqual(len(screen), 2)
        self.assertTrue(all(s["mechanism"] == "undetermined" for s in screen))
        verdict = fa.gate_2_missing({"descriptive": {"missing_mechanism_screen": screen},
                                   "cleaning_run": {"n_clean": 100}})
        self.assertEqual(verdict["status"], "WARN")

    def test_ci_keys_and_coefficient_intervals_cannot_certify_r2(self):
        invalid = [None, [], [0, float("nan")], [2, 1], [0, float("inf")], [True, 1]]
        for interval in invalid:
            with self.subTest(interval=interval):
                ctx = {"inferential": {"tests": [{"estimable": True, "outcome": "y",
                      "effect_sizes": {"omega_squared": .2, "omega_squared_ci95": interval}}]}}
                self.assertNotEqual(fa.gate_3_effect_size(ctx)["status"], "PASS")
        ctx["inferential"]["tests"][0]["effect_sizes"] = {
            "marginal_r2": .2, "fixed_effect_differences_ci95": {"b": {"ci95": [0, 1]}}}
        self.assertEqual(fa.gate_3_effect_size(ctx)["status"], "WARN")

    def test_valid_nested_effect_interval_passes(self):
        ctx = {"inferential": {"tests": [{"estimable": True, "outcome": "y",
               "effect_sizes": {"cohens_d": {"cohens_d": .2, "ci95": [-.1, .5]}}}]}}
        self.assertEqual(fa.gate_3_effect_size(ctx)["status"], "PASS")

    def test_two_group_report_preserves_nested_effect_interval_and_n(self):
        rng = np.random.default_rng(192)
        result = si.two_group_numeric(rng.normal(size=35), rng.normal(.5, 1, 35), "a", "b")
        self.assertEqual(result["n_total"], 70)
        name, value, interval = ar.summarize_effect(result["effect_sizes"])
        self.assertEqual(name, "Cohen's d")
        self.assertIsInstance(value, float)
        self.assertTrue(interval)


class EvidenceIntegrity(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)
        raw = self.out / "raw.csv"
        raw.write_text("id,y\na,1\nb,2\n")
        self.state = ps.new_state(ps.input_fingerprint(raw), self.out, {})
        self.state["execution_context"] = ps.execution_context(ROOT, {})
        ps.record_stage(self.state, "input", "completed", evidence=[str(raw)])
        for stage in ("route", "profile", "cleaning_execute", "inferential", "report"):
            path = self.out / (stage + ".json")
            path.write_text("{}")
            ps.record_stage(self.state, stage, "completed", evidence=[str(path)])
        ps.mark_run(self.state, "completed")

    def test_tampered_producer_invalidates_dependents_even_after_completion(self):
        (self.out / "cleaning_execute.json").write_text('{"tampered":true}')
        self.assertTrue(ps.validate_run(self.state))
        rp.prepare_resume(self.state, {})
        self.assertIn("profile", self.state["stages"])
        self.assertNotIn("cleaning_execute", self.state["stages"])
        self.assertNotIn("report", self.state["stages"])
        self.assertEqual(self.state["status"], "running")

    def test_missing_report_pdf_is_detected(self):
        pdf = self.out / "report.pdf"
        pdf.write_bytes(b"%PDF-test")
        ps.record_stage(self.state, "report", "completed", evidence=[str(self.out / "report.json")])
        pdf.unlink()
        self.assertTrue(ps.stage_evidence_issues(self.state, "report"))

    def test_cleaning_does_not_own_validation_from_an_earlier_run(self):
        cleaned = self.out / "cleaned"
        cleaned.mkdir()
        validation = cleaned / "validation.json"
        validation.write_text('{}')
        replay = cleaned / "clean_example.py"
        replay.write_text('# replay')
        ps.record_stage(self.state, "cleaning_execute", "completed",
                        evidence=[str(self.out / "cleaning_execute.json")])
        validation.write_text('{"new_validation":true}')
        self.assertFalse(ps.stage_evidence_issues(self.state, "cleaning_execute"))
        replay.write_text('# changed replay')
        self.assertTrue(ps.stage_evidence_issues(self.state, "cleaning_execute"))

    def test_changed_options_invalidate_previous_results(self):
        rp.prepare_resume(self.state, {"group": "other"})
        self.assertNotIn("route", self.state["stages"])
        self.assertEqual(self.state["status"], "running")

    def test_changed_code_or_environment_invalidates_results(self):
        for key in ("source_sha256", "environment"):
            self.state["execution_context"][key] = "outdated"
            rp.prepare_resume(self.state, {})
            self.assertNotIn("report", self.state["stages"])

    def test_legacy_evidence_is_not_silently_trusted(self):
        del self.state["stages"]["profile"]["artifacts"]
        rp.prepare_resume(self.state, {})
        self.assertNotIn("profile", self.state["stages"])

    def test_changed_answers_replace_only_answers_derived_choices(self):
        answers = self.out / "answers.json"
        answers.write_text('{"run":{"journal":"science"},"decisions":[]}')
        options = {"answers": str(answers), "journal": "nejm", "group": "arm"}
        self.state["options_from_answers"] = {"journal": "nejm"}
        rp.refresh_answers(self.state, options)
        self.assertEqual(options["journal"], "auto")
        self.assertEqual(options["group"], "arm")
        self.assertNotIn("inferential", self.state["stages"])

    def test_changed_upstream_records_cannot_reuse_downstream(self):
        self.state["stages"]["profile"]["artifacts"] = []
        self.assertTrue(ps.stage_evidence_issues(self.state, "report"))

    def test_verification_is_read_only_and_detects_changes(self):
        state_path = self.out / "state.json"
        ps.atomic_write_json(state_path, self.state)
        before = state_path.read_bytes()
        command = [sys.executable, str(ROOT / "scripts" / "verify_artifacts.py"),
                   "--outdir", str(self.out), "--json"]
        run = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertTrue(json.loads(run.stdout)["valid"])
        (self.out / "inferential.json").write_text('{"p":0}')
        run = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(run.returncode, 1, run.stdout)
        self.assertEqual(state_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
