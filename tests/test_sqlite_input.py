"""SQLite is a first-class, auditable single-table input."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from dm_types import read_table, source_spec  # noqa: E402


class SQLiteInput(unittest.TestCase):
    def make_db(self, path: Path, extra_table: bool = False) -> None:
        conn = sqlite3.connect(path)
        try:
            conn.execute("CREATE TABLE measurements (subject TEXT, arm TEXT, response REAL)")
            conn.executemany(
                "INSERT INTO measurements VALUES (?, ?, ?)",
                [("001", "control", 1.0), ("002", "treated", 2.5)],
            )
            if extra_table:
                conn.execute("CREATE TABLE metadata (key TEXT, value TEXT)")
            conn.commit()
        finally:
            conn.close()

    def test_single_table_reads_with_declared_schema_and_routes_as_tabular(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "study.sqlite"
            route = Path(td) / "route.json"
            profile = Path(td) / "profile.json"
            self.make_db(db)

            frame = read_table(db)
            self.assertEqual(list(frame.columns), ["subject", "arm", "response"])
            self.assertEqual(frame["subject"].tolist(), ["001", "002"])
            self.assertEqual(source_spec(db)["read_mode"], "native")

            proc = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "route_input.py"),
                 "--in", str(db), "--out", str(route)],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=60,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            doc = json.loads(route.read_text(encoding="utf-8"))
            self.assertEqual(doc["by_modality"], {"tabular": 1})
            self.assertEqual(doc["files"][0]["modality"], "tabular")

            profiled = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "profile_tabular.py"),
                 "--in", str(db), "--out", str(profile)],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=60,
            )
            self.assertEqual(profiled.returncode, 0, profiled.stdout + profiled.stderr)
            profile_doc = json.loads(profile.read_text(encoding="utf-8"))
            self.assertEqual(profile_doc["shape"], {"n_rows": 2, "n_cols": 3})

    def test_multiple_tables_fail_loudly_instead_of_picking_one(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "study.db"
            self.make_db(db, extra_table=True)
            with self.assertRaisesRegex(ValueError, "exactly one user table"):
                read_table(db)


if __name__ == "__main__":
    unittest.main(verbosity=2)
