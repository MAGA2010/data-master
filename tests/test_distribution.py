"""Build and exercise the installed wheel outside the repository.

The venv inherits scientific dependencies to avoid downloading the stack for
each test. data-master itself must come from the newly built wheel.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import venv
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class InstalledDistribution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.base = Path(cls.temp.name)
        cls.work = cls.base / "outside checkout"
        cls.work.mkdir()
        wheels = cls.base / "wheels"
        built = subprocess.run([sys.executable, "-m", "pip", "wheel", str(ROOT),
                                "--no-deps", "--wheel-dir", str(wheels)],
                               capture_output=True, text=True, timeout=180)
        if built.returncode:
            raise RuntimeError(built.stdout + built.stderr)
        cls.wheel = next(wheels.glob("data_master-*.whl"))
        cls.env = cls.base / "env"
        venv.EnvBuilder(with_pip=True, system_site_packages=True).create(cls.env)
        bin_dir = cls.env / ("Scripts" if os.name == "nt" else "bin")
        cls.python = bin_dir / ("python.exe" if os.name == "nt" else "python")
        cls.executable = bin_dir / ("data-master.exe" if os.name == "nt" else "data-master")
        installed = subprocess.run([str(cls.python), "-m", "pip", "install", "--no-deps",
                                    "--force-reinstall", str(cls.wheel)],
                                   capture_output=True, text=True, timeout=90, cwd=cls.work)
        if installed.returncode:
            raise RuntimeError(installed.stdout + installed.stderr)

    def command(self, *args, expected=0):
        proc = subprocess.run([str(self.executable), *map(str, args)], cwd=self.work,
                              env={**os.environ, "PYTHONUTF8": "1", "PYTHONPATH": ""},
                              capture_output=True, text=True, encoding="utf-8", timeout=180)
        self.assertEqual(proc.returncode, expected, proc.stdout + proc.stderr)
        return proc.stdout

    def test_wheel_contains_only_runtime_and_bundled_input(self):
        with zipfile.ZipFile(self.wheel) as archive:
            names = archive.namelist()
        self.assertIn("data_master/_runtime/scripts/run_pipeline.py", names)
        self.assertIn("data_master/_runtime/requirements.txt", names)
        self.assertIn("data_master/_runtime/references/journal-reporting-standards.json", names)
        self.assertIn("data_master/_runtime/examples/independent_groups/measurements.csv", names)
        self.assertIn("data_master/_runtime/skill-package.json", names)
        self.assertIn("data_master/_runtime/skills/data-router/SKILL.md", names)
        self.assertFalse(any("/outputs/" in name or "/.git/" in name or "/tests/" in name
                             for name in names), names)

    def test_declared_package_directories_exist_in_a_clean_checkout(self):
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertNotIn('"data_master._runtime.templates"', text)

    def test_installed_version_and_help(self):
        self.assertIn("0.2.0", self.command("--version"))
        self.assertIn("analyze", self.command("--help"))
        self.assertIn("--unit-key", self.command("analyze", "--help"))
        self.assertIn("--json", self.command("verify", "--help"))
        self.command("unknown-command", expected=2)

    def test_installed_cli_can_install_the_skill_atomically(self):
        target = self.work / "codex skills" / "data-master"
        self.command("skill", "install", "--target", target)
        self.assertTrue((target / "SKILL.md").is_file())
        self.assertTrue((target / "scripts" / "run_pipeline.py").is_file())
        self.assertTrue((target / "skills" / "data-router" / "SKILL.md").is_file())
        self.command("skill", "install", "--target", target, expected=2)

    def test_doctor_uses_installed_resources_and_real_imports(self):
        result = json.loads(self.command("doctor", "--json"))
        self.assertTrue(result["healthy"], result)
        self.assertIn(str(self.env), result["runtime"])
        self.assertNotIn(str(ROOT), result["runtime"])
        self.assertEqual(result["import_errors"], {})

    def test_installed_demo_verify_resume_and_no_overwrite(self):
        out = self.work / "demo report"
        self.command("demo", "--out", out)
        self.assertTrue((out / "report.pdf").read_bytes().startswith(b"%PDF-"))
        self.assertTrue(json.loads(self.command("verify", out, "--json"))["valid"])
        report = (out / "report.pdf").read_bytes()
        self.command("demo", "--out", out, expected=2)
        self.assertEqual((out / "report.pdf").read_bytes(), report)
        self.assertIn("report: reused", self.command("resume", out / "state.json"))
        self.assertTrue(json.loads(self.command("verify", out, "--json"))["valid"])
        state = json.loads((out / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["pipeline"]["package_version"], "0.2.0")
        (out / "report.md").write_text("altered", encoding="utf-8")
        self.command("verify", out, "--json", expected=1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
