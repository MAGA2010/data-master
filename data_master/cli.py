"""CLI adapters preserve the scripts' argument and evidence contracts."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from . import __version__


def runtime_root() -> Path:
    installed = Path(__file__).resolve().parent / "_runtime"
    return installed if installed.is_dir() else Path(__file__).resolve().parents[1]


def run_script(name: str, arguments: list[str]) -> int:
    script = runtime_root() / "scripts" / name
    if not script.is_file():
        print("Missing runtime script: %s; reinstall data-master." % script, file=sys.stderr)
        return 2
    return subprocess.call([sys.executable, str(script), *arguments],
                           env={**os.environ, "PYTHONUTF8": "1"})


def doctor(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="data-master doctor")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--modalities", default="tabular,report")
    args = parser.parse_args(arguments)
    root = runtime_root()
    resources = ["scripts/run_pipeline.py", "scripts/verify_artifacts.py",
                 "references/journal-reporting-standards.json", "requirements.txt",
                 "examples/independent_groups/measurements.csv"]
    missing = [p for p in resources if not (root / p).is_file()]
    check = subprocess.run([sys.executable, str(root / "scripts/check_deps.py"),
                            "--modalities", args.modalities, "--json"],
                           capture_output=True, text=True, encoding="utf-8",
                           env={**os.environ, "PYTHONUTF8": "1"})
    try:
        deps = json.loads(check.stdout)
    except ValueError:
        deps = {"missing_required": ["dependency checker failed"], "error": check.stderr}
    # Metadata can survive a broken binary install. Check real imports in an
    # isolated interpreter so the CLI itself remains available for diagnosis.
    modules = [name for name, info in deps.get("deps", {}).items() if info.get("installed")]
    probe_code = """import importlib, json, sys
errors = {}
for name in json.loads(sys.argv[1]):
    try:
        importlib.import_module(name)
    except Exception as exc:
        errors[name] = type(exc).__name__ + ': ' + str(exc)
print(json.dumps(errors))
"""
    probe = subprocess.run([sys.executable, "-c", probe_code, json.dumps(modules)],
                           capture_output=True, text=True, encoding="utf-8",
                           env={**os.environ, "PYTHONUTF8": "1"})
    try:
        import_errors = json.loads(probe.stdout)
    except ValueError:
        import_errors = {"probe": probe.stderr or "import probe failed"}
    payload = {"version": __version__, "python": sys.executable,
               "runtime": str(root), "missing_resources": missing,
               "dependencies": deps, "import_errors": import_errors,
               "healthy": not missing and not deps.get("missing_required")
                          and not import_errors and check.returncode == 0}
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print("data-master %s: %s" % (__version__, "READY" if payload["healthy"] else "NEEDS ATTENTION"))
        print("Python: %s" % sys.executable)
        for item in missing:
            print("Missing resource: %s" % item)
        for item in deps.get("missing_required", []):
            print("Missing dependency: %s" % item)
        for item, message in import_errors.items():
            print("Import failed: %s (%s)" % (item, message))
        for item in deps.get("missing_optional", []):
            print("Optional dependency: %s" % item)
    return 0 if payload["healthy"] else 2


def demo(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="data-master demo")
    parser.add_argument("--out", default="outputs/data-master-demo")
    args = parser.parse_args(arguments)
    out = Path(args.out).expanduser().resolve()
    # The bundled input is copied to a new run directory. Never write into an
    # installed package or overwrite a user's previous run, even for the demo.
    try:
        out.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        print("Output already exists: %s. Choose a new --out or use data-master resume %s."
              % (out, out / "state.json"), file=sys.stderr)
        return 2
    source = runtime_root() / "examples/independent_groups/measurements.csv"
    target = out / "input" / "measurements.csv"
    target.parent.mkdir()
    shutil.copyfile(source, target)
    print("Demo uses synthetic independent groups; no real treatment claim.\nOutput: %s" % out,
          flush=True)
    return run_script("run_pipeline.py", ["--in", str(target), "--out", str(out),
                      "--group", "arm", "--unit-key", "subject", "--outcomes", "response",
                      "--title", "Synthetic independent groups"])


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="data-master", description="Auditable analysis with saved evidence.")
    parser.add_argument("--version", action="version", version="data-master " + __version__)
    parser.add_argument("command", choices=["analyze", "demo", "doctor", "resume", "verify"], nargs="?")
    if not arguments or arguments[0] in ("-h", "--help", "--version"):
        parser.parse_args(arguments)
        if not arguments:
            parser.print_help()
        return 0
    command = parser.parse_args(arguments[:1]).command
    rest = arguments[1:]
    try:
        if command == "demo":
            return demo(rest)
        if command == "doctor":
            return doctor(rest)
        if not rest or rest[0] in ("-h", "--help"):
            if command == "analyze":
                print("Usage: data-master analyze FILE [pipeline options]\n")
                return run_script("run_pipeline.py", ["--help"])
            print("Usage: data-master %s %s %s" % (
                command, "STATE" if command == "resume" else "DIRECTORY",
                "[pipeline options]" if command == "resume" else "[--json]"))
            return 0 if rest else 2
        if command == "verify":
            return run_script("verify_artifacts.py", ["--outdir", rest[0], *rest[1:]])
        return run_script("run_pipeline.py", ["--in" if command == "analyze" else "--resume",
                                              rest[0], *rest[1:]])
    except (OSError, KeyboardInterrupt) as exc:
        print("data-master: %s" % exc, file=sys.stderr)
        return 130 if isinstance(exc, KeyboardInterrupt) else 2
