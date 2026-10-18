"""End-to-end check: completed runs must detect and repair altered evidence."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PipelineIntegrity(unittest.TestCase):
    def test_completed_run_verifies_repairs_and_reuses_evidence(self):
        raw = ROOT / "examples" / "independent_groups" / "measurements.csv"
        raw_hash = hashlib.sha256(raw.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "report"

            def run(script, *args, expected=0):
                proc = subprocess.run(
                    [sys.executable, str(ROOT / "scripts" / script), *map(str, args)],
                    cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                    env={**os.environ, "PYTHONUTF8": "1"}, timeout=180)
                self.assertEqual(proc.returncode, expected, proc.stdout + proc.stderr)
                return proc.stdout

            run("run_pipeline.py", "--in", raw, "--out", out, "--group", "arm",
                "--unit-key", "subject", "--outcomes", "response")
            verify = lambda expected=0: run("verify_artifacts.py", "--outdir", out,
                                            "--json", expected=expected)
            self.assertTrue(json.loads(verify())["valid"])
            audit = json.loads((out / "audit" / "final_audit.json").read_text(encoding="utf-8"))
            self.assertEqual(audit["n_fail"], 0)
            self.assertEqual(audit["n_warn"], 0)

            inference = out / "analysis" / "inferential.json"
            result = json.loads(inference.read_text(encoding="utf-8"))
            result["tests"][0]["p_raw"] = .999
            inference.write_text(json.dumps(result), encoding="utf-8")
            self.assertFalse(json.loads(verify(1))["valid"])
            log = run("run_pipeline.py", "--resume", out / "state.json")
            self.assertIn("inferential: evidence changed", log)
            self.assertIn("cleaning_execute: reused", log)
            self.assertNotIn("inferential: reused", log)
            self.assertTrue(json.loads(verify())["valid"])
            self.assertLess(json.loads(inference.read_text(encoding="utf-8"))["tests"][0]["p_raw"], .01)

            (out / "report.pdf").unlink()
            self.assertFalse(json.loads(verify(1))["valid"])
            log = run("run_pipeline.py", "--resume", out / "state.json")
            self.assertIn("report: evidence changed", log)
            self.assertIn("inferential: reused", log)
            self.assertTrue((out / "report.pdf").read_bytes().startswith(b"%PDF-"))
            self.assertTrue(json.loads(verify())["valid"])
            self.assertEqual(hashlib.sha256(raw.read_bytes()).hexdigest(), raw_hash)


if __name__ == "__main__":
    unittest.main(verbosity=2)
