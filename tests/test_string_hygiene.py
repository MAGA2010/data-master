"""String cleanup must retain missing values under both pandas backends."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from dm_types import hygiene_project  # noqa: E402
import execute_cleaning as ec  # noqa: E402
from profile_tabular import profile_columns  # noqa: E402


class StringHygiene(unittest.TestCase):
    def storage_modes(self):
        yield "python"
        if importlib.util.find_spec("pyarrow") is not None:
            yield "pyarrow"

    def test_missing_and_empty_columns_remain_string_typed(self):
        for storage in self.storage_modes():
            with pd.option_context("mode.string_storage", storage):
                for values in ([], [None, pd.NA, float("nan")]):
                    with self.subTest(storage=storage, values=values):
                        source = pd.Series(values, dtype="string", name="notes")
                        actual = hygiene_project(source)
                        pd.testing.assert_series_equal(actual, source)
                        # Exercise the real operations and profiler as well as
                        # the planning preview that crashed on Ubuntu.
                        frame = pd.DataFrame({"notes": source})
                        for op in (ec.op_fix_unicode, ec.op_strip_whitespace,
                                   ec.op_collapse_whitespace, ec.op_trim_paired_quotes):
                            frame = op(frame, ["notes"])
                        pd.testing.assert_series_equal(frame["notes"], source)
                        entry = profile_columns(pd.DataFrame({"notes": source}))["notes"]
                        self.assertEqual(entry["n_missing"], len(source))
                        self.assertEqual(entry["n_unique"], 0)

    def test_preview_matches_execution_without_losing_values_or_index(self):
        for storage in self.storage_modes():
            with self.subTest(storage=storage), pd.option_context("mode.string_storage", storage):
                source = pd.Series([' "Cafe\u0301\t Nord" ', None, '"  001  "', "   ", "'β'"],
                                   index=[9, 2, 2, 7, 6], dtype="string", name="label")
                expected = pd.Series(["Café Nord", None, "001", "", "β"],
                                     index=source.index, dtype="string", name="label")
                pd.testing.assert_series_equal(hygiene_project(source), expected)
                frame = pd.DataFrame({"label": source})
                for op in (ec.op_fix_unicode, ec.op_strip_whitespace,
                           ec.op_collapse_whitespace, ec.op_trim_paired_quotes):
                    frame = op(frame, ["label"])
                pd.testing.assert_series_equal(frame["label"], expected)

    def test_csv_profile_clean_and_standalone_replay_with_empty_column(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            raw = base / "study.csv"
            raw.write_text('label,notes\n" Cafe\u0301 ",\nNorth,\nSouth,\n', encoding="utf-8")
            profile = base / "profile.json"
            plan = base / "cleaning_plan.json"
            cleaned = base / "cleaned"

            def run(script, *args):
                result = subprocess.run(
                    [sys.executable, str(ROOT / "scripts" / script), *map(str, args)],
                    cwd=base, env={**os.environ, "PYTHONUTF8": "1"},
                    capture_output=True, text=True, encoding="utf-8", timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            run("profile_tabular.py", "--in", raw, "--out", profile)
            entry = json.loads(profile.read_text(encoding="utf-8"))["columns"]["notes"]
            self.assertEqual(entry["n_missing"], 3)
            run("cleaning_plan.py", "--profile", profile, "--out", plan)
            run("execute_cleaning.py", "--in", raw, "--plan", plan, "--out", cleaned)
            record = json.loads((cleaned / "cleaning_run.json").read_text(encoding="utf-8"))
            self.assertTrue(record["reproducibility_check"]["passed"], record)
            result = pd.read_csv(cleaned / "cleaned.csv", dtype=str)
            self.assertEqual(result["label"].tolist(), ["Café", "North", "South"])
            self.assertEqual(len(result), 3)
            # Dropping an all-null column is allowed only as a recorded plan op.
            if "notes" in result:
                self.assertTrue(result["notes"].isna().all())
            else:
                actions = json.loads(plan.read_text(encoding="utf-8"))["auto_actions"]
                self.assertTrue(any(a["op"] == "drop_all_null_cols" and "notes" in a["columns"]
                                    for a in actions), actions)


if __name__ == "__main__":
    unittest.main(verbosity=2)
