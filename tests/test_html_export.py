"""The HTML export must be a faithful, verified deliverable of the run.

Checks the contract the export claims:
  - it exists next to report.md for a completed run, on both report paths;
  - it is self-contained (figures embedded, no external asset references);
  - its numbers are those of report.md -- the sha256 of the source markdown is
    stamped into the file, and distinctive values from report.md survive;
  - artifact verification owns it: an altered or missing report.html fails
    verify_artifacts.py exactly like an altered report.pdf would.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from export_html import render_report_html  # noqa: E402


class HtmlExport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.out = Path(cls.temp.name) / "report"

        def run(script, *args, expected=0):
            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / script), *map(str, args)],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                env={**os.environ, "PYTHONUTF8": "1"}, timeout=180)
            if proc.returncode != expected:
                raise AssertionError("exit %d (wanted %d)\n%s%s"
                                     % (proc.returncode, expected,
                                        proc.stdout, proc.stderr))
            return proc.stdout

        cls.execute = staticmethod(run)
        raw = ROOT / "examples" / "independent_groups" / "measurements.csv"
        run("run_pipeline.py", "--in", raw, "--out", cls.out, "--group", "arm",
            "--unit-key", "subject", "--outcomes", "response")

    def verify(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "verify_artifacts.py"),
             "--outdir", str(self.out), "--json"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "PYTHONUTF8": "1"}, timeout=60)
        return proc.returncode, json.loads(proc.stdout)

    def test_export_exists_self_contained_and_owned_by_the_ledger(self):
        html_path = self.out / "report.html"
        self.assertTrue(html_path.is_file(), "a completed run must deliver report.html")
        html = html_path.read_text(encoding="utf-8")
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        # self-contained: every figure rides inside the file
        self.assertIn("data:image/png;base64,", html)
        self.assertNotIn('src="charts/', html,
                         "the export must not depend on an asset folder")
        state = json.loads((self.out / "state.json").read_text(encoding="utf-8"))
        evidence = state["stages"]["report"]["evidence"]
        self.assertTrue(any(p.endswith("report.html") for p in evidence),
                        "report.html is not report-stage evidence")
        code, doc = self.verify()
        self.assertEqual(code, 0, doc)

    def test_numbers_are_those_of_report_md(self):
        html = (self.out / "report.html").read_text(encoding="utf-8")
        md = (self.out / "report.md").read_text(encoding="utf-8")
        # the export names the exact report.md it renders
        sha = hashlib.sha256(md.encode("utf-8")).hexdigest()
        self.assertIn(sha, html, "the source markdown hash is not recorded")
        # numbers a reader would quote are the saved ones, not recalculated
        numbers = re.findall(r"\d+\.\d+", md)
        self.assertGreater(len(numbers), 50)
        sampled = {n for n in numbers if len(n) >= 4}
        missing = {n for n in sampled if n not in html}
        self.assertFalse(missing, "numbers absent from the export: %s"
                         % sorted(missing)[:10])
        # and the rebuild block pins the same provenance
        build = json.loads((self.out / "report_build.json").read_text(encoding="utf-8"))
        self.assertEqual(build["html"]["source_md_sha256"], sha)
        self.assertTrue(build["html"]["self_contained"])

    def test_altered_or_missing_export_fails_verification(self):
        html_path = self.out / "report.html"
        original = html_path.read_bytes()

        html_path.write_bytes(original + b"<!-- appended -->")
        code, doc = self.verify()
        self.assertEqual(code, 1, "an altered export still verified: %s" % doc)
        self.assertTrue(any("report.html" in str(i.get("path", ""))
                            for i in doc["issues"]), doc)

        html_path.unlink()
        code, doc = self.verify()
        self.assertEqual(code, 1, "a missing export still verified: %s" % doc)
        self.assertTrue(any("report.html" in str(i.get("path", ""))
                            for i in doc["issues"]), doc)

        html_path.write_bytes(original)
        code, doc = self.verify()
        self.assertEqual(code, 0, doc)

    def test_export_is_deterministic_and_reports_missing_figures(self):
        # re-rendering the same evidence with the same title reproduces the
        # bytes the pipeline delivered
        build = json.loads((self.out / "report_build.json").read_text(encoding="utf-8"))
        first = (self.out / "report.html").read_bytes()
        render_report_html(self.out / "report.md", outdir=self.out,
                           title=build["title"])
        self.assertEqual((self.out / "report.html").read_bytes(), first,
                         "an unchanged report re-exported to different bytes")
        # a figure that is gone is called out on the page, not dropped
        with tempfile.TemporaryDirectory() as td:
            run = Path(td)
            (run / "report.md").write_text(
                "# T\n\n![Figure 1: x](charts/gone.png)\n", encoding="utf-8")
            info = render_report_html(run / "report.md", outdir=run)
            self.assertEqual(info["images_missing"], ["charts/gone.png"])
            page = (run / "report.html").read_text(encoding="utf-8")
            self.assertIn("not found", page)
            self.assertFalse(info["self_contained"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
