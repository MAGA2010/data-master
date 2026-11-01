"""The time-series path must refuse broken inputs with the truth.

Two contracts under test:
  - a timestamp column that parses completely but never spans two instants
    (a stuck instrument clock) is refused with evidence that says exactly
    that, and the one-command runner surfaces the profiler's reason instead
    of a generic failure;
  - a numeric column that is real but too short for descriptive statistics
    is refused with a sample-size fact, never with a false claim that no
    numeric column exists.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def make_run(base: Path, name: str, rows: dict) -> Path:
    d = base / name
    d.mkdir(parents=True)
    pd.DataFrame(rows).to_csv(d / "log.csv", index=False)
    return d


class TimeseriesHolds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.base = Path(cls.temp.name)
        cls.hours = pd.date_range("2026-01-01", periods=48, freq="h")

    def run_script(self, script, *args, cwd=None):
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / script), *map(str, args)],
            cwd=cwd or ROOT, capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "PYTHONUTF8": "1"}, timeout=240)

    def pipeline(self, d: Path):
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "run_pipeline.py"),
             "--in", str(d / "log.csv"), "--out", str(d / "out"),
             "--title", d.name],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "PYTHONUTF8": "1"}, timeout=300)

    def test_stuck_clock_is_refused_with_the_truth(self):
        rng = np.random.default_rng(1)
        d = make_run(self.base, "stuck-clock",
                     {"timestamp": [self.hours[0]] * 48,
                      "temp": rng.normal(20, 2, 48)})
        prof = self.run_script("profile_timeseries.py", "--in", d / "log.csv",
                               "--out", d / "profile.json")
        self.assertEqual(prof.returncode, 1)
        doc = json.loads((d / "profile.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["time_column"], None)
        reason = doc["time_evidence"]["reason"]
        self.assertIn("do not span two instants", reason)
        self.assertIn("timestamp", reason)
        # the router called this file time-series; the pipeline must not die
        # on a generic error but pass the profiler's verdict through
        run = self.pipeline(d)
        self.assertEqual(run.returncode, 1)
        combined = run.stdout + run.stderr
        self.assertIn("do not span two instants", combined,
                      "the profiler's reason was swallowed: %s" % combined[-400:])

    def test_short_numeric_series_is_a_sample_size_fact(self):
        d = make_run(self.base, "short-series",
                     {"timestamp": self.hours[:2], "temp": [20.0, 21.0]})
        self.run_script("profile_timeseries.py", "--in", d / "log.csv",
                        "--out", d / "profile.json")
        proc = self.run_script("timeseries_analysis.py", "--in", d / "log.csv",
                               "--profile", d / "profile.json",
                               "--out", d / "ts.json")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("fewer than 20 usable rows", proc.stderr)
        self.assertNotIn("no numeric value column", proc.stderr,
                         "the column is numeric; claiming otherwise is false")
        # the full pipeline stays equally honest
        run = self.pipeline(d)
        self.assertEqual(run.returncode, 1)
        self.assertIn("fewer than 20 usable rows", run.stdout + run.stderr)

    def test_a_file_with_no_numeric_column_says_so(self):
        d = make_run(self.base, "no-numeric",
                     {"timestamp": self.hours,
                      "label": ["a", "b"] * 24})
        self.run_script("profile_timeseries.py", "--in", d / "log.csv",
                        "--out", d / "profile.json")
        proc = self.run_script("timeseries_analysis.py", "--in", d / "log.csv",
                               "--profile", d / "profile.json",
                               "--out", d / "ts.json")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("no numeric value column", proc.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
