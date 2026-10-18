#!/usr/bin/env python3
"""Inspect or resume a data-master run from its state ledger."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from pipeline_state import load_state, stage_summary, validate_run  # noqa: E402


def find_state(explicit: Optional[str]) -> Path:
    if explicit:
        path = Path(explicit).resolve()
        if not path.exists():
            raise SystemExit("state file not found: %s" % path)
        return path
    candidates = [Path.cwd() / "state.json", Path.cwd() / "outputs" / "state.json"]
    for path in candidates:
        if path.exists():
            return path.resolve()
    raise SystemExit(
        "state file not found; pass --state PATH "
        "(a new run writes outputs/state.json)"
    )


def validate_evidence(state: dict) -> list:
    return validate_run(state)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--state", help="path to state.json")
    action = ap.add_mutually_exclusive_group()
    action.add_argument("--show", action="store_true", help="print the stage summary")
    action.add_argument("--validate", action="store_true",
                        help="verify saved SHA-256 hashes for every completed stage")
    action.add_argument("--resume", action="store_true",
                        help="resume from the first incomplete stage")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    state_path = find_state(args.state)
    state = load_state(state_path)

    if args.resume:
        cmd = [sys.executable, str(HERE / "run_pipeline.py"),
               "--resume", str(state_path)]
        print("[resume] %s" % state_path)
        return subprocess.call(cmd)

    if args.validate:
        missing = validate_evidence(state)
        payload = {
            "state": str(state_path),
            "valid": not missing,
            "missing": missing,
            "issues": missing,
            "summary": stage_summary(state),
        }
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print("state: %s" % state_path)
            print("evidence: %s" % ("OK" if not missing else "INVALID"))
            for item in missing:
                print("  - %s: %s (%s)" % (item["stage"], item.get("path", ""), item["reason"]))
        return 0 if not missing else 1

    summary = stage_summary(state)
    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0

    print("state: %s" % state_path)
    print("status: %s" % summary["status"])
    print("input: %s" % summary["input"])
    print("outdir: %s" % summary["outdir"])
    print("stages: %d/%d completed" % (summary["completed"], summary["total"]))
    print("next: %s" % (summary["next"] or "none"))
    if summary.get("audit_verdict"):
        print("audit: %s" % summary["audit_verdict"])
    for name, status in summary["stages"].items():
        print("  %-22s %s" % (name, status))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
