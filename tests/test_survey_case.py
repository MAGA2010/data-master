"""Survey-data case: labelled values, explicit missing codes, text identifiers.

The synthetic fixture is the archetype of a survey export, and every trap in
it must surface as a held decision rather than a silent transformation:

  respondent_id      zero-padded ids stay text (leading-zero hold)
  age_years          the -999 "not answered" code parses as a number, so the
                     column converts and the impossible value is flagged, not
                     dropped
  satisfaction /
  visit_frequency    labelled categories keep their labels; blanks stay
                     missing; nothing is encoded or imputed
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples" / "survey" / "survey_responses.csv"

SATISFACTION = {"Very dissatisfied", "Dissatisfied", "Neutral",
                "Satisfied", "Very satisfied"}
FREQUENCY = {"Never", "Rarely", "Sometimes", "Often"}


class SurveyCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.out = Path(cls.temp.name) / "run"

        def run(script, *args, expected=0):
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / script), *map(str, args)],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                env={**__import__("os").environ, "PYTHONUTF8": "1"}, timeout=120)
            if proc.returncode != expected:
                raise AssertionError("exit %d (wanted %d)\n%s%s"
                                     % (proc.returncode, expected,
                                        proc.stdout, proc.stderr))
            return proc.stdout

        profile = cls.out / "analysis" / "profile.json"
        run("profile_tabular.py", "--in", FIXTURE, "--out", profile)
        run("cleaning_plan.py", "--profile", profile,
            "--out", cls.out / "cleaning_plan.json")
        run("execute_cleaning.py", "--in", FIXTURE,
            "--plan", cls.out / "cleaning_plan.json",
            "--out", cls.out / "cleaned")
        cls.plan = json.loads(
            (cls.out / "cleaning_plan.json").read_text(encoding="utf-8"))
        cls.profile = json.loads(profile.read_text(encoding="utf-8"))

    def flags(self, op):
        return [f for f in self.plan["never_automatic_flags"]
                if f["op"] == op]

    # ---- the fixture itself --------------------------------------------------
    def test_raw_values_regression(self):
        raw = pd.read_csv(FIXTURE, dtype=str, keep_default_na=False)
        self.assertEqual(list(raw.columns),
                         ["respondent_id", "age_years", "satisfaction",
                          "visit_frequency", "recommend", "minutes_spent"])
        self.assertEqual(len(raw), 120)
        ids = list(raw["respondent_id"])
        self.assertEqual(ids[0], "0001")
        self.assertTrue(all(v.startswith("0") and v.isdigit() for v in ids),
                        "ids must stay zero-padded digits")
        self.assertEqual((raw["age_years"] == "-999").sum(), 12,
                         "the explicit missing-code count changed")
        self.assertEqual(set(raw["satisfaction"]) - {""}, SATISFACTION)
        self.assertEqual((raw["satisfaction"] == "").sum(), 7)
        self.assertEqual(set(raw["visit_frequency"]) - {""}, FREQUENCY)
        self.assertEqual((raw["visit_frequency"] == "").sum(), 5)
        self.assertEqual(set(raw["recommend"]), {"Yes", "No"})
        self.assertEqual((raw["minutes_spent"] == "").sum(), 9)

    # ---- the identifier stays text -------------------------------------------
    def test_zero_padded_identifier_held_and_preserved(self):
        flags = self.flags("coerce_numeric")
        self.assertEqual([f["columns"] for f in flags], [["respondent_id"]])
        self.assertEqual(flags[0]["default_if_silent"], "keep_as_text")
        self.assertIn("leading zero", flags[0]["reason"])
        cleaned = pd.read_csv(self.out / "cleaned" / "cleaned.csv",
                              dtype=str, keep_default_na=False)
        self.assertEqual(list(cleaned["respondent_id"]),
                         list(pd.read_csv(FIXTURE, dtype=str,
                                          keep_default_na=False)["respondent_id"]),
                         "the identifier was retyped despite the hold")

    # ---- the -999 code converts but is then held ------------------------------
    def test_missing_code_flagged_not_dropped(self):
        prof = self.profile["columns"]["age_years"]
        stats = prof.get("coercion_numeric_stats") or {}
        self.assertEqual(stats.get("negatives"), 12,
                         "the -999 codes were not visible to the profiler")
        self.assertEqual(stats.get("min"), -999.0)
        anomalies = self.profile.get("anomalies", {}).get("flags", [])
        imp = [f for f in anomalies if f["type"] == "impossible_negative"]
        self.assertEqual([f["column"] for f in imp], ["age_years"])
        self.assertEqual(imp[0]["n_negatives"], 12)
        flags = self.flags("drop_impossible")
        self.assertEqual(flags[0]["columns"], ["age_years"])
        self.assertEqual(flags[0]["default_if_silent"], "flag_only")
        cleaned = pd.read_csv(self.out / "cleaned" / "cleaned.csv")
        self.assertEqual(int((cleaned["age_years"] == -999).sum()), 12,
                         "the held code must survive cleaning untouched")
        self.assertTrue(pd.api.types.is_numeric_dtype(cleaned["age_years"]))

    # ---- labelled values survive; blanks stay missing -------------------------
    def test_labels_survive_and_blanks_stay_missing(self):
        cleaned = pd.read_csv(self.out / "cleaned" / "cleaned.csv",
                              dtype=str, keep_default_na=False)
        self.assertEqual(set(cleaned["satisfaction"]) - {""}, SATISFACTION)
        self.assertEqual(set(cleaned["visit_frequency"]) - {""}, FREQUENCY)
        self.assertEqual(set(cleaned["recommend"]), {"Yes", "No"})
        self.assertEqual((cleaned["satisfaction"] == "").sum(), 7)
        self.assertEqual((cleaned["visit_frequency"] == "").sum(), 5)
        impute = self.flags("impute_categorical")
        self.assertTrue(any(set(f["columns"]) == {"minutes_spent", "satisfaction",
                                                  "visit_frequency"}
                            for f in impute),
                        "the missing-data hold did not name the labelled columns")
        self.assertTrue(all(f["default_if_silent"] == "leave_as_nan" for f in impute))
        ops = {a["op"] for a in self.plan["auto_actions"]}
        self.assertNotIn("onehot_encode", ops)
        self.assertNotIn("label_encode", ops)
        self.assertNotIn("impute_mode", ops)

    # ---- the committed case study keeps its shape -----------------------------
    def test_committed_case_study_artifacts(self):
        committed = ROOT / "examples" / "survey" / "outputs"
        audit = json.loads(
            (committed / "audit" / "final_audit.json").read_text(encoding="utf-8"))
        self.assertEqual(audit["verdict"], "SUBMISSION-READY")
        gates = {g["gate"]: g["status"] for g in audit["gates"]}
        self.assertEqual(gates[1], "PASS", "the run declares respondent_id as unit")
        self.assertEqual(gates[2], "WARN",
                         "the missingness mechanism must remain an open question")
        plan = json.loads(
            (committed / "cleaning_plan.json").read_text(encoding="utf-8"))
        held = {f["op"] for f in plan["never_automatic_flags"]}
        self.assertEqual(held, {"coerce_numeric", "drop_impossible",
                                "impute_categorical"})
        template = json.loads(
            (committed / "answers.template.json").read_text(encoding="utf-8"))
        self.assertEqual([d["id"] for d in template["decisions"]],
                         ["coerce_numeric@respondent_id",
                          "drop_impossible@age_years",
                          "impute_categorical@minutes_spent,satisfaction,visit_frequency"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
