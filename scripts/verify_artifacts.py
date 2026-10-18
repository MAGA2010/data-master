#!/usr/bin/env python3
"""Verify saved evidence without regenerating or modifying a report.

Usage: python scripts/verify_artifacts.py --outdir outputs --json
The state ledger is the trust anchor; hashes detect accidental changes, not
malicious rewriting of both an artifact and its ledger. Scientific validity
remains the responsibility of statistical review and the report audit.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pipeline_state import load_state, validate_run


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    state_path = Path(args.outdir).resolve() / "state.json"
    try:
        state = load_state(state_path)
        issues = validate_run(state)
        if not state.get("stages"):
            issues.append({"stage": "run", "reason": "no saved stages"})
        if state.get("status") != "completed":
            issues.append({"stage": "run", "reason": "run is not completed"})
        payload = {"valid": not issues, "issues": issues,
                   "state": str(state_path), "audit_verdict": state.get("audit_verdict"),
                   "scope": "artifact integrity, not scientific approval"}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        payload = {"valid": False, "issues": [{"reason": str(exc)}]}
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print("Evidence integrity: %s" % ("PASS" if payload["valid"] else "FAIL"))
        for issue in payload["issues"]:
            print("  %s: %s" % (issue.get("path", issue.get("stage", "run")), issue["reason"]))
    return 0 if payload["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
