"""Date-versus-number ambiguity: the pipeline must hold, not guess.

`session_stamp` values such as 20240115 parse as an integer and as a date.
The contract under test, in order:

  1. the raw fixture keeps that double reading (regression on the values);
  2. the cleaning plan records the ambiguity with evidence, not a warning;
  3. automatic cleaning preserves the original text untouched;
  4. one explicit answer (dates) resolves the flag with provenance, converts
     the column through the ordinary auto-action path, and executes it.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples" / "date_number_ambiguity" / "session_export.csv"


class DateNumberAmbiguity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.out = Path(cls.temp.name) / "run"

    def run_script(self, script, *args, expected=0):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / script), *map(str, args)],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            env={**{k: v for k, v in __import__("os").environ.items()},
                 "PYTHONUTF8": "1"}, timeout=120)
        self.assertEqual(proc.returncode, expected,
                         proc.stdout + proc.stderr)
        return proc.stdout

    def plan(self, *extra):
        profile = self.out / "analysis" / "profile.json"
        plan_path = self.out / "cleaning_plan.json"
        self.run_script("profile_tabular.py", "--in", FIXTURE,
                        "--out", profile)
        self.run_script("cleaning_plan.py", "--profile", profile,
                        "--out", plan_path, *extra)
        return json.loads(plan_path.read_text(encoding="utf-8"))

    # ---- 1. the fixture itself stays ambiguous -------------------------------
    def test_raw_values_parse_both_ways(self):
        raw = pd.read_csv(FIXTURE, dtype=str)
        self.assertEqual(list(raw.columns),
                         ["subject_id", "session_stamp", "latency_s"])
        stamps = list(raw["session_stamp"])
        self.assertGreater(len(stamps), 40)
        self.assertTrue(all(re.fullmatch(r"\d{8}", v) for v in stamps),
                        "every stamp must be a bare 8-digit integer")
        # as numbers
        self.assertTrue(all(float(v) == int(v) for v in stamps))
        # as dates: every value is a real calendar day in YYYYMMDD form
        parsed = pd.to_datetime(pd.Series(stamps), format="%Y%m%d",
                                errors="coerce")
        self.assertFalse(parsed.isna().any(),
                         "fixture drifted: some stamp is no longer a date")
        self.assertGreater(parsed.dt.year.nunique(), 0)
        self.assertTrue(parsed.dt.year.between(2024, 2024).all())

    # ---- 2. the plan records the ambiguity with evidence --------------------
    def test_plan_records_ambiguity_with_evidence(self):
        plan = self.plan()
        flags = [f for f in plan["never_automatic_flags"]
                 if f["op"] == "coerce_numeric_or_date"]
        self.assertEqual([f["columns"] for f in flags], [["session_stamp"]],
                         "the ambiguous column was not held")
        flag = flags[0]
        self.assertEqual(flag["default_if_silent"], "keep_as_text")
        self.assertIn("parses both", flag["reason"])
        probe = flag["detail"]
        self.assertTrue(probe["numeric_probe"]["all_parse"],
                        "numeric evidence missing from the hold")
        self.assertTrue(probe["date_probe"]["all_parse"],
                        "date evidence missing from the hold")
        # the template exposes the same id with the explicit choices
        template = json.loads(
            (self.out / "answers.template.json").read_text(encoding="utf-8"))
        entry = next(d for d in template["decisions"]
                     if d["id"] == flag["id"])
        self.assertEqual(entry["allowed_actions"],
                         ["dates", "integers", "keep_as_text"])

    # ---- 3. automatic cleaning preserves the original values ----------------
    def test_automatic_cleaning_preserves_values(self):
        plan = self.plan()
        self.run_script("execute_cleaning.py", "--in", FIXTURE,
                        "--plan", self.out / "cleaning_plan.json",
                        "--out", self.out / "cleaned")
        raw = pd.read_csv(FIXTURE, dtype=str)
        cleaned = pd.read_csv(self.out / "cleaned" / "cleaned.csv", dtype=str)
        self.assertEqual(list(cleaned["session_stamp"]),
                         list(raw["session_stamp"]),
                         "the ambiguous column was converted without an answer")
        # while the unambiguous numeric column did convert
        self.assertTrue(pd.api.types.is_numeric_dtype(
            pd.read_csv(self.out / "cleaned" / "cleaned.csv")["latency_s"]))

    # ---- 4. one explicit answer resolves and converts ------------------------
    def test_answers_file_resolves_to_dates(self):
        plan = self.plan()
        flag = next(f for f in plan["never_automatic_flags"]
                    if f["op"] == "coerce_numeric_or_date")
        answers = self.out / "answers.json"
        answers.write_text(json.dumps({"decisions": [{
            "id": flag["id"], "action": "dates",
            "rationale": "lab notebook records session days, not counters",
            "decided_by": "benchmark test",
        }]}), encoding="utf-8")

        resolved = self.plan("--answers", answers)
        flag2 = next(f for f in resolved["never_automatic_flags"]
                     if f["op"] == "coerce_numeric_or_date")
        self.assertEqual(flag2["resolved"]["action"], "dates")
        self.assertEqual(flag2["resolved"]["decided_by"], "benchmark test")
        added = [a for a in resolved["auto_actions"]
                 if a["op"] == "coerce_dates"
                 and "session_stamp" in a["columns"]]
        self.assertEqual(len(added), 1,
                         "the answer must convert through the ordinary op path")
        self.assertEqual(added[0]["user_opt_in"]["decision_id"], flag["id"])

        self.run_script("execute_cleaning.py", "--in", FIXTURE,
                        "--plan", self.out / "cleaning_plan.json",
                        "--out", self.out / "cleaned-answered")
        converted = pd.read_csv(self.out / "cleaned-answered" / "cleaned.csv",
                                dtype=str)
        self.assertTrue(
            converted["session_stamp"].str.match(r"^\d{4}-\d{2}-\d{2}$").all(),
            "the answered column did not become dates: %s"
            % converted["session_stamp"].head(3).tolist())
        self.assertEqual(list(converted["subject_id"]),
                         list(pd.read_csv(FIXTURE, dtype=str)["subject_id"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
