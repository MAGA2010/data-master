#!/usr/bin/env python3
"""Run data-master end to end from one input path.

Tabular files with one comparison group run the full cleaning, statistics,
figure, report and audit chain. Other modalities, mixed folders and multi-file
inputs run the profile-only report path. The distinction is explicit in
`state.json` and in the delivered report.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from pipeline_state import (  # noqa: E402
    PROFILE_ONLY_STAGES,
    STAGE_ORDER,
    atomic_write_json,
    input_fingerprint,
    invalidate_stages_from,
    load_state,
    mark_run,
    new_state,
    paths_fingerprint,
    pipeline_provenance,
    record_stage,
    stage_completed,
)
from route_input import expand  # noqa: E402


def log(message: str) -> None:
    print("[data-master] %s" % message, flush=True)


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-").lower()
    return slug or "input"


def display_title(input_path: Path) -> str:
    name = input_path.stem if input_path.is_file() else input_path.name
    return "%s analysis" % (name or "Dataset")


def default_outdir(raw_input: str) -> Path:
    if any(token in raw_input for token in ("*", "?", "[")):
        return Path.cwd() / "outputs"
    path = Path(raw_input).expanduser().resolve()
    return path.parent / "outputs"


def fingerprint_for(raw_input: str, exclude: Optional[Path]) -> Dict[str, Any]:
    if any(token in raw_input for token in ("*", "?", "[")):
        matches = expand(raw_input)
        if not matches:
            raise FileNotFoundError("no files matched %s" % raw_input)
        return paths_fingerprint(matches, raw_input)
    return input_fingerprint(Path(raw_input), exclude=exclude)


def command_text(cmd: List[str]) -> str:
    return " ".join('"%s"' % part if " " in part else part for part in cmd)


class Pipeline:
    def __init__(self, state: Dict[str, Any], state_path: Path, force: bool) -> None:
        self.state = state
        self.state_path = state_path
        self.force = force

    def save(self) -> None:
        atomic_write_json(self.state_path, self.state)

    def skip(self, stage: str, evidence: Iterable[str]) -> bool:
        evidence = [str(item) for item in evidence]
        if not self.force and stage_completed(self.state, stage, evidence):
            record_stage(self.state, stage, "completed", evidence=evidence,
                         message="reused from state.json; input fingerprint unchanged")
            self.save()
            log("%s: reused" % stage)
            return True
        return False

    def run(self, stage: str, cmd: List[str], evidence: Iterable[str],
            expected: Tuple[int, ...] = (0,), label: Optional[str] = None) -> int:
        evidence = [str(item) for item in evidence]
        if self.skip(stage, evidence):
            return 0
        record_stage(self.state, stage, "running", command=cmd, evidence=evidence)
        self.save()
        started = time.monotonic()
        print()
        log("%s: %s" % (stage, command_text(cmd)))
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONHASHSEED": "0"},
        )
        duration = int((time.monotonic() - started) * 1000)
        if proc.stdout:
            print(proc.stdout.rstrip())
        if proc.stderr:
            print(proc.stderr.rstrip(), file=sys.stderr)
        if proc.returncode not in expected:
            message = (proc.stderr or proc.stdout or "exit %d" % proc.returncode).strip()
            record_stage(self.state, stage, "failed", evidence=evidence,
                         command=cmd, message=message[-2000:],
                         duration_ms=duration)
            mark_run(self.state, "failed", message="%s failed" % (label or stage))
            self.save()
            return proc.returncode or 1
        record_stage(
            self.state,
            stage,
            "completed",
            evidence=evidence,
            command=cmd,
            duration_ms=duration,
            message=(proc.stdout or "").strip()[-1000:] or None,
        )
        self.save()
        return 0

    def write_stage(self, stage: str, evidence: Iterable[str], message: str,
                    status: str = "completed") -> None:
        evidence = [str(item) for item in evidence]
        if not self.force and stage_completed(self.state, stage, evidence):
            log("%s: reused" % stage)
            return
        record_stage(self.state, stage, status, evidence=evidence, message=message)
        self.save()


DEFAULT_MAX_INPUT_MB = 300.0   # text-mode reads hold ~3-5x the file in memory


def input_size_gate(route: Dict[str, Any], options: Dict[str, Any]) -> Optional[str]:
    """Block inputs too large for the in-memory text-mode contract.

    Every reader in this pipeline reads whole, as text, by design -- that is
    what keeps a leading zero alive. The price is memory, and a 2 GB CSV
    should fail with a decision the user can act on, not a MemoryError half
    an hour into a run. An explicit --max-input-mb is the user overriding the
    default limit and is honoured with a warning.
    """
    limit_mb = options.get("max_input_mb") or DEFAULT_MAX_INPUT_MB
    explicit = bool(options.get("max_input_mb"))
    total = 0
    for f in route.get("files") or []:
        try:
            total += Path(str(f.get("path"))).stat().st_size
        except OSError:
            pass
    total_mb = total / (1024.0 * 1024.0)
    if total_mb <= limit_mb:
        return None
    if explicit:
        return ("WARNING: input is %.0f MB, above the %.0f MB default but "
                "explicitly allowed via --max-input-mb; the run may exhaust "
                "memory because every reader holds the file whole, as text"
                % (total_mb, limit_mb))
    return ("BLOCKED: input is %.0f MB and the in-memory contract is %.0f MB. "
            "Options: sample the file, split it, or re-run with "
            "--max-input-mb %.0f to accept the memory risk explicitly."
            % (total_mb, DEFAULT_MAX_INPUT_MB, total_mb))


VALID_JOURNALS = ("nature", "nejm", "science", "lancet")


def apply_answers_run_block(answers_path: Optional[str], options: Dict[str, Any],
                            profile_path: Path) -> Dict[str, Any]:
    """Apply the answers file's run-level declarations to the run options.

    The answers file can now settle everything the audit will otherwise flag
    as AUTHOR_INPUT_NEEDED -- unit key, grouping, design, journal -- in the
    same file as the cleaning decisions. Command-line and recorded-state
    values always win; the run block only fills blanks, and every value it
    fills is validated (columns against the profile, design against the
    routing table) before the run continues.
    """
    if not answers_path:
        return {}
    path = Path(answers_path)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit("answers file could not be read: %s" % exc)
    run = doc.get("run")
    if not isinstance(run, dict):
        return {}

    columns: Optional[set] = None
    if profile_path.exists():
        try:
            columns = set((json.loads(profile_path.read_text(encoding="utf-8"))
                           .get("columns") or {}).keys())
        except Exception:
            columns = None
    designs: set = set()
    std_path = ROOT / "references" / "journal-reporting-standards.json"
    if std_path.exists():
        try:
            designs = set((json.loads(std_path.read_text(encoding="utf-8"))
                           .get("designs") or {}).keys())
        except Exception:
            pass

    applied: Dict[str, Any] = {}
    errors: List[str] = []

    def _unset(key: str, default: Any = None) -> bool:
        val = options.get(key)
        return val is None or val == "" or val == default

    for key, value in run.items():
        if key not in ("unit_key", "unit", "group", "outcomes", "design",
                       "journal", "covariates"):
            errors.append("run block: unknown key %r (accepted: unit_key, unit, "
                          "group, outcomes, design, journal, covariates)" % key)
            continue
        if not _unset(key, "auto" if key in ("design", "journal") else None):
            continue  # an explicit CLI/state value wins; the run block stays quiet
        if key in ("unit_key", "group") and columns is not None and value not in columns:
            errors.append("run block: %s=%r is not a column of this dataset" % (key, value))
            continue
        if key in ("outcomes", "covariates"):
            cols = [c.strip() for c in str(value).split(",") if c.strip()]
            if columns is not None:
                bad = [c for c in cols if c not in columns]
                if bad:
                    errors.append("run block: %s names unknown column(s): %s"
                                  % (key, ", ".join(bad)))
                    continue
            value = ",".join(cols)
        if key == "journal" and value not in VALID_JOURNALS:
            errors.append("run block: journal=%r; accepted: %s"
                          % (value, ", ".join(VALID_JOURNALS)))
            continue
        if key == "design" and designs and value not in designs:
            errors.append("run block: design=%r; accepted ids: %s"
                          % (value, ", ".join(sorted(designs))))
            continue
        options[key] = value
        applied[key] = value

    if errors:
        print("ERROR: answers run block rejected -- nothing was applied:",
              file=sys.stderr)
        for e in errors:
            print("  - %s" % e, file=sys.stderr)
        raise SystemExit(2)
    return applied


def augment_answers_template(outdir: Path, options: Dict[str, Any],
                             group_used: Optional[str]) -> None:
    """Add the run-level questions to answers.template.json.

    One file should carry every question the pipeline will not answer itself:
    the cleaning holds (written by cleaning_plan.py) and the run declarations
    the audit flags as AUTHOR_INPUT_NEEDED when left blank.
    """
    path = outdir / "answers.template.json"
    if not path.exists():
        return
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    run: Dict[str, Any] = {}
    if not options.get("unit_key"):
        run["unit_key"] = {
            "value": None,
            "why": "gate 1 fails without a declared independent unit; name the "
                   "column that identifies one unit",
            "required": True}
    if not options.get("group") and group_used:
        run["group"] = {
            "value": None,
            "why": "the grouping column was auto-selected as %r; name it "
                   "explicitly to pin the research question" % group_used,
            "required": False}
    if options.get("design") in (None, "auto"):
        run["design"] = {
            "value": None,
            "why": "the EQUATOR checklist is undetermined; pass a design id "
                   "(see references/journal-reporting-standards.json)",
            "required": False}
    if options.get("journal") in (None, "auto"):
        run["journal"] = {
            "value": None,
            "why": "journal family defaults to nature; one of nature/nejm/"
                   "science/lancet",
            "required": False}
    if run:
        doc["run"] = run
        doc.setdefault("run_instructions",
                       "fill 'value' for any entry you want to declare; "
                       "unset entries keep their current behaviour")
        path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")


def parse_options(args) -> Dict[str, Any]:
    return {
        "input": args.inp,
        "out": str(Path(args.out).resolve()) if args.out else None,
        "title": args.title,
        "group": args.group,
        "outcomes": args.outcomes,
        "unit": args.unit,
        "unit_key": args.unit_key,
        "report": args.report,
        "journal": args.journal,
        "design": args.design,
        "profile_only": bool(args.profile_only),
        "pdf_backend": args.pdf_backend,
        "modality": args.modality,
        "answers": str(Path(args.answers).resolve()) if args.answers else None,
        "export_lockfile": bool(args.export_lockfile),
        "covariates": args.covariates,
        "max_input_mb": float(args.max_input_mb) if args.max_input_mb else None,
    }


def answers_fingerprint(path: Optional[str]) -> Optional[Dict[str, Any]]:
    """Hash the answers file so a resume can tell an unchanged answer set
    (reuse the recorded stages) from a changed one (the cleaning and every
    stage downstream of it are stale and must re-run)."""
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        raise SystemExit("answers file not found: %s" % p)
    import hashlib
    return {"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}


def export_lockfile(outdir: Path) -> Path:
    """Snapshot the exact environment next to the evidence it produced.

    requirements.txt pins floors ('>='), which is right for installing but
    wrong for reproducing: a year later the floors admit different versions
    and nothing on disk can detect the difference. This file is the floor plus
    the ceiling that actually ran.
    """
    import importlib.metadata as md
    reqs = [
        line.strip()
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    lines = [
        "# data-master lockfile -- exact versions that produced this run's artifacts.",
        "# Install with:  python -m pip install -r lockfile.txt",
    ]
    prov = pipeline_provenance(ROOT)
    if prov.get("git_commit"):
        lines.append("# pipeline commit: %s%s" % (
            prov["git_commit"], " (dirty working tree)" if prov.get("git_dirty") else ""))
    else:
        lines.append("# pipeline commit: unknown (%s)" % prov.get("note"))
    lines.append("# python: %s on %s" % (platform.python_version(), platform.platform()))
    for req in reqs:
        name = re.split(r"[><=~!;]", req, maxsplit=1)[0].strip()
        try:
            lines.append("%s==%s" % (name, md.version(name)))
        except Exception:
            lines.append("# %s: not installed in this environment" % name)
    path = outdir / "lockfile.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="data-master: one command from input to audited report"
    )
    ap.add_argument("--in", dest="inp", help="file, folder, or glob")
    ap.add_argument("--out", help="output directory (default: input parent/outputs)")
    ap.add_argument("--title", help="report title")
    ap.add_argument("--group", help="grouping column; otherwise the profile's top candidate")
    ap.add_argument("--outcomes", help="comma-separated outcome columns")
    ap.add_argument("--unit", default="row",
                    help="what one row represents (descriptive statistics)")
    ap.add_argument("--unit-key", help="column identifying the independent unit")
    ap.add_argument("--report", default="nature",
                    help="report template label recorded in the PDF")
    ap.add_argument("--journal", default="auto",
                    choices=["auto", "nature", "nejm", "science", "lancet"])
    ap.add_argument("--design", default="auto", help="EQUATOR design id or auto")
    ap.add_argument("--modality", help="force a router modality")
    ap.add_argument("--answers", help="decisions.json answering the plan's "
                                      "never-automatic flags (see answers.template.json)")
    ap.add_argument("--covariates", help="comma-list of numeric covariates; "
                                         "the adjusted (ANCOVA) comparison becomes primary")
    ap.add_argument("--max-input-mb", type=float,
                    help="override the %g MB in-memory input limit (the run may "
                         "then exhaust memory; the default exists because every "
                         "reader holds the file whole, as text)"
                         % DEFAULT_MAX_INPUT_MB)
    ap.add_argument("--export-lockfile", action="store_true",
                    help="write lockfile.txt with the exact versions that ran")
    ap.add_argument("--profile-only", action="store_true",
                    help="stop after profiling and build a profile-only report")
    ap.add_argument("--pdf-backend", default="auto",
                    choices=["auto", "reportlab", "fpdf2", "headless-browser"])
    ap.add_argument("--resume", metavar="STATE", help="resume a previous state.json")
    ap.add_argument("--force", action="store_true",
                    help="re-run stages even when the state says they completed")
    return ap


def choose_group(profile: Dict[str, Any]) -> Optional[str]:
    candidates = ((profile.get("group_candidate") or {}).get("candidates") or [])
    columns = profile.get("columns") or {}
    id_like = re.compile(
        r"(^|_)(id|code|key|uuid|guid|index|idx|number|no)($|_)", re.I
    )
    ordered = (
        [c for c in candidates if not id_like.search(str(c.get("column") or ""))]
        + [c for c in candidates if id_like.search(str(c.get("column") or ""))]
    )
    for candidate in ordered:
        name = candidate.get("column")
        n_unique = candidate.get("n_unique")
        case_info = (columns.get(name) or {}).get(
            "residual_case_variants_post_hygiene"
        ) or {}
        if case_info.get("n_after_casefold") is not None:
            n_unique = case_info["n_after_casefold"]
        missing = (columns.get(name) or {}).get("missing_pct")
        if not name or n_unique is None:
            continue
        if 2 <= int(n_unique) <= 12 and (missing is None or float(missing) <= 50.0):
            return str(name)
    return None


def write_skipped_inference(path: Path, clean_path: Path, profile: Dict[str, Any],
                            reason: str, unit_key: Optional[str]) -> None:
    payload = {
        "schema_version": "1.1",
        "source": str(clean_path),
        "group": None,
        "group_levels": [],
        "group_sizes": {},
        "alpha": 0.05,
        "n_rows": int((profile.get("shape") or {}).get("n_rows") or 0),
        "unit_of_analysis": {
            "unit_key": unit_key,
            "n_rows": int((profile.get("shape") or {}).get("n_rows") or 0),
            "note": ("no --unit-key given; row is assumed to be the independent unit"
                     if not unit_key else "unit declared by the user"),
        },
        "tests": [],
        "multiple_comparisons": {
            "primary_family": {
                "method": None,
                "family_size": 0,
                "adjusted": [],
            },
            "note": "no inferential family was formed",
        },
        "correlations": {
            "matrix": [],
            "family": {"family_size": 0, "adjusted": []},
            "note": "not run because no comparison structure was established",
        },
        "skipped": {"reason": reason},
        "rule_source": "references/nature-statistics-checklist.md#gates-3-5",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def profile_command(modality: str, source: Path, out: Path,
                    forced_modality: Optional[str] = None) -> List[str]:
    base = [sys.executable]
    if modality == "tabular":
        return base + [str(HERE / "profile_tabular.py"), "--in", str(source),
                       "--out", str(out)]
    if modality == "time-series":
        return base + [str(HERE / "profile_timeseries.py"), "--in", str(source),
                       "--out", str(out)]
    if modality == "text-corpus":
        return base + [str(HERE / "profile_text.py"), "--in", str(source),
                       "--out", str(out)]
    if modality in ("image-set", "audio-set"):
        kind = "image" if modality == "image-set" else "audio"
        return base + [str(HERE / "profile_media.py"), "--in", str(source),
                       "--kind", kind, "--out", str(out)]
    if modality == "geospatial":
        return base + [str(HERE / "profile_geospatial.py"), "--in", str(source),
                       "--out", str(out)]
    raise ValueError("no profiler for modality %r (forced=%r)"
                     % (modality, forced_modality))


def stage_branch_folder(files: List[Path], outdir: Path, modality: str) -> Path:
    """Expose a branch's files as a folder without copying huge inputs when the
    filesystem supports hard links."""
    staged = outdir / "analysis" / "branch_inputs" / safe_slug(modality)
    staged.mkdir(parents=True, exist_ok=True)
    for source in files:
        target = staged / source.name
        if target.exists():
            continue
        try:
            os.link(source, target)
        except OSError:
            shutil.copy2(source, target)
    return staged


def profile_all(pipe: Pipeline, route: Dict[str, Any], outdir: Path,
                forced_modality: Optional[str]) -> Tuple[Path, List[str]]:
    analysis = outdir / "analysis"
    analysis.mkdir(parents=True, exist_ok=True)
    jobs: List[Dict[str, Any]] = []
    plan_count = len(route.get("plan") or [])
    raw_source = Path(str(route.get("source") or "")).expanduser()
    raw_is_dir = raw_source.is_dir()
    for branch in route.get("plan") or []:
        modality = branch.get("modality")
        if modality == "unknown":
            continue
        files = [Path(item) for item in (branch.get("files") or [])]
        if not files:
            continue
        can_profile_folder = modality in ("text-corpus", "image-set", "audio-set")
        if can_profile_folder and plan_count == 1 and raw_is_dir:
            jobs.append({
                "modality": modality,
                "source": raw_source.resolve(),
                "out": analysis / "profile.json",
            })
            continue
        if can_profile_folder and len(files) > 1:
            jobs.append({
                "modality": modality,
                "source": stage_branch_folder(files, outdir, modality),
                "out": analysis / "profile.json" if plan_count == 1
                else analysis / "modalities" / ("%s.json" % safe_slug(modality)),
            })
            continue
        for index, source in enumerate(files, 1):
            if len(files) == 1:
                out = analysis / "profile.json" if plan_count == 1 \
                    else analysis / "modalities" / ("%s_%s.json" % (
                        safe_slug(modality), safe_slug(source.stem)))
            else:
                out = analysis / "modalities" / ("%s_%02d_%s.json" % (
                    safe_slug(modality), index, safe_slug(source.stem)))
            jobs.append({
                "modality": modality,
                "source": source,
                "out": out,
            })

    aggregate_path = analysis / "profile.json"
    expected = [str(job["out"]) for job in jobs] + [str(aggregate_path)]
    expected = sorted(set(expected))
    if pipe.skip("profile", expected):
        return aggregate_path, expected

    branch_records: List[Dict[str, Any]] = []
    evidence: List[str] = []
    for job in jobs:
        modality = job["modality"]
        source = job["source"]
        out = job["out"]
        out.parent.mkdir(parents=True, exist_ok=True)
        cmd = profile_command(modality, source, out, forced_modality)
        started = time.monotonic()
        print()
        log("profile [%s]: %s" % (modality, command_text(cmd)))
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONHASHSEED": "0"},
        )
        if proc.stdout:
            print(proc.stdout.rstrip())
        if proc.stderr:
            print(proc.stderr.rstrip(), file=sys.stderr)
        if proc.returncode != 0:
            record_stage(
                pipe.state, "profile", "failed", evidence=[str(out)],
                command=cmd,
                message=(proc.stderr or proc.stdout)[-2000:],
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            mark_run(pipe.state, "failed", message="profile failed")
            pipe.save()
            raise RuntimeError("profile failed for %s" % source)
        evidence.append(str(out))
        branch_profile = read_json(out)
        branch_records.append({
            "modality": modality,
            "source": str(source),
            "profile_path": str(out),
            "shape": branch_profile.get("shape") or {},
        })

    if len(branch_records) == 1:
        single = read_json(Path(branch_records[0]["profile_path"]))
        if Path(branch_records[0]["profile_path"]) != aggregate_path:
            aggregate_path.write_text(
                json.dumps(single, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            evidence.append(str(aggregate_path))
    else:
        modalities = sorted({rec["modality"] for rec in branch_records})
        aggregate = {
            "schema_version": "1.0",
            "source": route.get("source"),
            "modality": "mixed" if len(modalities) > 1 else modalities[0],
            "shape": {
                "n_rows": sum(int((rec.get("shape") or {}).get("n_rows") or 0)
                              for rec in branch_records),
                "n_cols": sum(int((rec.get("shape") or {}).get("n_cols") or 0)
                              for rec in branch_records),
            },
            "independent_unit_hint": "one item in each branch; see branch profiles",
            "branches": branch_records,
            "anomalies": {"flags": [], "n_flags": 0},
        }
        aggregate_path.write_text(
            json.dumps(aggregate, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        evidence.append(str(aggregate_path))

    unique_evidence = sorted(set(evidence + [str(aggregate_path)]))
    pipe.write_stage(
        "profile",
        unique_evidence,
        "profiled %d file(s) across %d branch(es)"
        % (len(branch_records), len({rec["modality"] for rec in branch_records})),
    )
    return aggregate_path, unique_evidence


def write_profile_audit(outdir: Path, profile_path: Path,
                        build_path: Path) -> List[str]:
    audit_dir = outdir / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    build = read_json(build_path) if build_path.exists() else {}
    ts_path = outdir / "analysis" / "timeseries.json"
    has_ts = False
    if ts_path.exists():
        try:
            has_ts = bool(read_json(ts_path).get("estimable"))
        except Exception:
            has_ts = False
    # the profile path now carries real p-values when time-series statistics
    # ran, so the no-upgrade phrase scan applies there too -- a banned
    # construction does not stop being banned because the report is shorter
    phrase_hits: List[str] = []
    report_md = outdir / "report.md"
    if has_ts and report_md.exists():
        try:
            from final_audit import FORBIDDEN, DISCLAIMER_MARKERS
            for number, line in enumerate(
                    report_md.read_text(encoding="utf-8").splitlines(), 1):
                low = line.lower()
                if any(m in low for m in DISCLAIMER_MARKERS):
                    continue
                for pattern, why in FORBIDDEN:
                    m = re.search(pattern, line, flags=re.IGNORECASE)
                    if m:
                        phrase_hits.append("line %d: %r -- %s"
                                           % (number, m.group(0), why))
        except Exception:
            pass
    payload = {
        "schema_version": "1.1",
        "mode": "profile-only",
        "verdict": ("PROFILE COMPLETE -- DESCRIPTIVE TIME-SERIES STATISTICS"
                    if has_ts else "PROFILE COMPLETE"),
        "scope": ("routing, profiling and descriptive time-series statistics "
                  "(trend, slope with CI, autocorrelation, STL strengths, "
                  "changepoint screen); no forecast, no imputation, no "
                  "deduplication, no causal claim"
                  if has_ts else
                  "routing and profiling only; no statistical inference, "
                  "imputation, deduplication or causal claim"),
        "profile": str(profile_path),
        "timeseries": str(ts_path) if has_ts else None,
        "phrase_scan": {"status": "FAIL" if phrase_hits else "PASS",
                        "hits": phrase_hits[:10]},
        "pdf_written": bool((build.get("pdf") or {}).get("pdf_written")),
        "open_questions": [
            "AUTHOR_INPUT_NEEDED: what one independent unit represents",
            "AUTHOR_INPUT_NEEDED: which anomalies are genuine defects",
            "AUTHOR_INPUT_NEEDED: which comparison or prediction question is intended",
        ],
    }
    json_path = audit_dir / "profile_only.json"
    md_path = audit_dir / "profile_only.md"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")
    md = [
        "# %s audit" % ("Time-series descriptive" if has_ts else "Profile-only"),
        "",
        "- Verdict: **%s**" % payload["verdict"],
        "- Scope: %s." % payload["scope"],
        "- PDF written: **%s**" % ("yes" if payload["pdf_written"] else "no"),
        "- Phrase scan: **%s** (%d forbidden construction(s) outside disclaimers)"
        % (payload["phrase_scan"]["status"], len(phrase_hits)),
        "- Profile artifact: `%s`" % profile_path,
        *(["- Time-series artifact: `%s`" % ts_path] if has_ts else []),
        "",
        "## Open questions",
        "",
        *["- %s" % item for item in payload["open_questions"]],
        "",
    ]
    md_path.write_text("\n".join(md), encoding="utf-8")
    return [str(json_path), str(md_path)]


def run_full_tabular(pipe: Pipeline, input_path: Path, outdir: Path,
                     options: Dict[str, Any], profile: Dict[str, Any]) -> int:
    analysis = outdir / "analysis"
    cleaned = outdir / "cleaned"
    charts = outdir / "charts"
    profile_path = analysis / "profile.json"
    plan_path = outdir / "cleaning_plan.json"
    clean_csv = cleaned / "cleaned.csv"
    run_path = cleaned / "cleaning_run.json"
    validation_path = cleaned / "validation.json"
    descriptive_path = analysis / "descriptive.json"
    inferential_path = analysis / "inferential.json"
    decisions_path = analysis / "chart_decisions.json"
    manifest_path = outdir / "charts_rendered.json"
    report_path = outdir / "report.md"
    audit_path = outdir / "audit" / "final_audit.json"

    code = pipe.run("cleaning_plan", [
        sys.executable, str(HERE / "cleaning_plan.py"),
        "--profile", str(profile_path), "--out", str(plan_path),
        *(["--answers", str(options["answers"])] if options.get("answers") else []),
    ], [plan_path])
    if code:
        return code

    code = pipe.run("cleaning_execute", [
        sys.executable, str(HERE / "execute_cleaning.py"),
        "--in", str(input_path), "--plan", str(plan_path),
        "--out", str(cleaned),
    ], [clean_csv, run_path])
    if code:
        return code

    code = pipe.run("cleaning_validate", [
        sys.executable, str(HERE / "validate_clean.py"),
        "--raw", str(input_path), "--clean", str(clean_csv),
        "--profile", str(profile_path), "--out", str(validation_path),
    ], [validation_path])
    if code:
        return code

    code = pipe.run("descriptive", [
        sys.executable, str(HERE / "stats_descriptive.py"),
        "--clean", str(clean_csv), "--out", str(descriptive_path),
        "--unit", str(options.get("unit") or "row"),
        *(["--unit-key", str(options["unit_key"])] if options.get("unit_key") else []),
    ], [descriptive_path])
    if code:
        return code

    group = options.get("group") or choose_group(profile)
    if group:
        log("inferential: auto-selected group column %r" % group)
        infer_cmd = [
            sys.executable, str(HERE / "stats_inferential.py"),
            "--clean", str(clean_csv), "--out", str(inferential_path),
            "--group", str(group),
        ]
        if options.get("outcomes"):
            infer_cmd.extend(["--outcomes", str(options["outcomes"])])
        if options.get("covariates"):
            infer_cmd.extend(["--covariates", str(options["covariates"])])
        if options.get("unit_key"):
            infer_cmd.extend(["--unit-key", str(options["unit_key"])])
        code = pipe.run("inferential", infer_cmd, [inferential_path])
        if code:
            return code
    else:
        if not pipe.skip("inferential", [inferential_path]):
            reason = (
                "no defensible grouping variable was found in the profile; "
                "a group comparison was not forced"
            )
            write_skipped_inference(
                inferential_path, clean_csv, profile, reason,
                options.get("unit_key"),
            )
            record_stage(pipe.state, "inferential", "skipped",
                         evidence=[str(inferential_path)], message=reason)
            pipe.save()
            log("inferential: skipped -- %s" % reason)

    # ---- sensitivity: perturb the primary analysis (gate 6 reads this) ----
    sensitivity_path = analysis / "sensitivity.json"
    sens_cmd = [
        sys.executable, str(HERE / "sensitivity_analysis.py"),
        "--clean", str(clean_csv),
        "--inferential", str(inferential_path),
        "--out", str(sensitivity_path),
    ]
    if options.get("group"):
        sens_cmd.extend(["--group", str(options["group"])])
    code = pipe.run("sensitivity", sens_cmd, [sensitivity_path])
    if code:
        return code

    # the template should carry the run-level questions too, so one file
    # answers everything the audit would otherwise flag
    augment_answers_template(outdir, options, options.get("group") or group)

    code = pipe.run("chart_decisions", [
        sys.executable, str(HERE / "chart_decision.py"),
        "--clean", str(clean_csv),
        "--profile", str(profile_path),
        "--descriptive", str(descriptive_path),
        "--inferential", str(inferential_path),
        "--out", str(decisions_path),
    ], [decisions_path])
    if code:
        return code

    code = pipe.run("charts", [
        sys.executable, str(HERE / "render_chart.py"),
        "--clean", str(clean_csv),
        "--decisions", str(decisions_path),
        "--outdir", str(charts),
        "--manifest", str(manifest_path),
    ], [manifest_path])
    if code:
        return code

    code = pipe.run("report", [
        sys.executable, str(HERE / "assemble_report.py"),
        "--raw", str(input_path), "--outdir", str(outdir),
        "--title", str(options["title"]), "--template", str(options["report"]),
        "--pdf-backend", str(options["pdf_backend"]),
    ], [report_path, outdir / "report_build.json"])
    if code:
        return code

    audit_cmd = [
        sys.executable, str(HERE / "final_audit.py"),
        "--outdir", str(outdir),
        "--journal", str(options["journal"]),
        "--design", str(options["design"]),
        "--template", _audit_template(str(options["report"])),
    ]
    code = pipe.run("audit", audit_cmd, [audit_path], expected=(0, 1))
    if code not in (0, 1):
        return code
    audit = read_json(audit_path)
    pipe.state["audit_verdict"] = audit.get("verdict")
    mandatory = audit.get("mandatory_failures") or []
    structural_fail = any(
        item.get("status") == "FAIL" for item in (audit.get("structural") or [])
    )
    unit_only = bool(mandatory) and all(
        item.get("gate") == 1 for item in mandatory
    ) and not structural_fail
    if structural_fail:
        mark_run(pipe.state, "failed",
                 message="structural audit failed")
        pipe.save()
        return 1
    if mandatory and not unit_only:
        mark_run(pipe.state, "completed",
                 message="report written with unresolved audit failures")
        pipe.save()
        return 1
    return 0


def _audit_template(report_template: str) -> str:
    low = report_template.lower()
    if "executive" in low:
        return "executive"
    if "standard" in low:
        return "standard"
    return "nature"


def run_profile_only(pipe: Pipeline, outdir: Path, options: Dict[str, Any],
                     profile_path: Path, route_path: Path) -> int:
    code = pipe.run("report", [
        sys.executable, str(HERE / "assemble_profile_report.py"),
        "--profile", str(profile_path), "--route", str(route_path),
        "--outdir", str(outdir), "--title", str(options["title"]),
        "--pdf-backend", str(options["pdf_backend"]),
    ], [outdir / "report.md", outdir / "report_build.json"])
    if code:
        return code
    evidence = write_profile_audit(
        outdir, profile_path, outdir / "report_build.json"
    )
    pipe.write_stage(
        "audit", evidence, "profile audit written; no inferential claim made"
    )
    audit_doc = outdir / "audit" / "profile_only.json"
    try:
        pipe.state["audit_verdict"] = read_json(audit_doc).get("verdict")
    except Exception:
        pipe.state["audit_verdict"] = "PROFILE COMPLETE"
    return 0


def fresh_state(args, state_path: Path) -> Tuple[Dict[str, Any], Path]:
    raw_input = args.inp
    input_path = Path(raw_input).expanduser()
    if not any(token in raw_input for token in ("*", "?", "[")):
        input_path = input_path.resolve()
        if not input_path.exists():
            raise SystemExit("input not found: %s" % input_path)
    outdir = Path(args.out).expanduser().resolve() if args.out \
        else default_outdir(raw_input)
    outdir.mkdir(parents=True, exist_ok=True)
    meta = fingerprint_for(raw_input, exclude=outdir)
    options = parse_options(args)
    options["out"] = str(outdir)
    options["title"] = args.title or display_title(input_path)
    state = new_state(meta, outdir, options)
    # the code that produced this run is part of the evidence, not an
    # environment detail: a resume on a different commit must be visible
    state["pipeline"] = pipeline_provenance(ROOT)
    state["answers"] = answers_fingerprint(options.get("answers"))
    input_evidence = meta.get("paths") or [meta["path"]]
    record_stage(state, "input", "completed", evidence=input_evidence,
                 message="input fingerprint %s" % meta["sha256"][:16])
    atomic_write_json(state_path, state)
    return state, outdir


def verify_resume(state: Dict[str, Any], state_path: Path) -> Path:
    outdir = Path(state.get("outdir") or ".").resolve()
    meta = state.get("input") or {}
    label = meta.get("path")
    if not label:
        raise SystemExit("state file has no input path: %s" % state_path)
    if meta.get("kind") == "set":
        current = paths_fingerprint(expand(label), label)
    else:
        current = input_fingerprint(Path(label), exclude=outdir)
    if current.get("sha256") != meta.get("sha256"):
        raise SystemExit(
            "input changed since this state was written; start a fresh run "
            "instead of resuming"
        )
    return outdir


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    state_path: Path
    if args.resume:
        state_path = Path(args.resume).expanduser().resolve()
        if not state_path.exists():
            print("state file not found: %s" % state_path, file=sys.stderr)
            return 2
        state = load_state(state_path)
        outdir = verify_resume(state, state_path)
        options = state.get("options") or {}
        if args.answers:
            options["answers"] = str(Path(args.answers).resolve())
        if args.force:
            options["force"] = True
        # an answers file whose contents changed makes the recorded cleaning
        # and everything downstream of it stale, even though the input itself
        # did not change; those stages are invalidated rather than trusted
        current_answers = answers_fingerprint(options.get("answers"))
        recorded_answers = state.get("answers")
        if (current_answers or recorded_answers) and current_answers != recorded_answers:
            stale = invalidate_stages_from(
                state, "cleaning_plan",
                "answers file %s" % ("changed" if recorded_answers else "supplied"))
            state["answers"] = current_answers
            if stale:
                log("answers: %d stage(s) invalidated and will re-run" % len(stale))
        if state.get("status") == "completed" and not args.force:
            log("run already completed: %s" % state_path)
            print("audit: %s" % (state.get("audit_verdict") or "unknown"))
            return 0
    else:
        if not args.inp:
            print("--in is required unless --resume is used", file=sys.stderr)
            return 2
        if args.out and not args.title:
            args.title = display_title(Path(args.inp))
        outdir = Path(args.out).expanduser().resolve() if args.out \
            else default_outdir(args.inp)
        state_path = outdir / "state.json"
        if state_path.exists() and not args.force:
            previous = load_state(state_path)
            try:
                verify_resume(previous, state_path)
                log("found matching state; resuming %s" % state_path)
                state = previous
                options = state.get("options") or {}
                if args.answers:
                    options["answers"] = str(Path(args.answers).resolve())
                current_answers = answers_fingerprint(options.get("answers"))
                recorded_answers = state.get("answers")
                if (current_answers or recorded_answers) \
                        and current_answers != recorded_answers:
                    stale = invalidate_stages_from(
                        state, "cleaning_plan",
                        "answers file %s"
                        % ("changed" if recorded_answers else "supplied"))
                    state["answers"] = current_answers
                    if stale:
                        log("answers: %d stage(s) invalidated and will re-run"
                            % len(stale))
            except SystemExit:
                state, outdir = fresh_state(args, state_path)
                options = state.get("options") or {}
        else:
            state, outdir = fresh_state(args, state_path)
            options = state.get("options") or {}
        if not options.get("title"):
            options["title"] = display_title(Path(str(options["input"])))

    pipe = Pipeline(state, state_path, force=bool(args.force or options.get("force")))
    mark_run(pipe.state, "running")
    pipe.save()

    try:
        route_path = outdir / "route.json"
        route_cmd = [
            sys.executable, str(HERE / "route_input.py"),
            "--in", str(options["input"]), "--out", str(route_path), "--deep",
        ]
        if options.get("modality"):
            route_cmd.extend(["--modality", str(options["modality"])])
        code = pipe.run("route", route_cmd, [route_path], expected=(0, 1))
        if code not in (0, 1):
            return code
        route = read_json(route_path)
        known_modalities = [
            name for name in (route.get("by_modality") or {}) if name != "unknown"
        ]
        if not known_modalities:
            record_stage(pipe.state, "route", "blocked", evidence=[str(route_path)],
                         message="unknown modality; use references/research-protocol.md")
            mark_run(pipe.state, "blocked",
                     message="routing produced an unknown modality")
            pipe.save()
            print("routing blocked: unknown input; see %s" % route_path,
                  file=sys.stderr)
            return 2
        if (route.get("by_modality") or {}).get("unknown"):
            log("route: %d unknown file(s) will be listed but not profiled"
                % route["by_modality"]["unknown"])

        # ---- input size gate: fail with a decision, not a MemoryError ----
        size_verdict = input_size_gate(route, options)
        if size_verdict and size_verdict.startswith("BLOCKED"):
            record_stage(pipe.state, "preflight", "blocked",
                         evidence=[str(route_path)], message=size_verdict)
            mark_run(pipe.state, "blocked", message="input exceeds the "
                     "in-memory contract; use --max-input-mb to override")
            pipe.save()
            print(size_verdict, file=sys.stderr)
            return 2
        if size_verdict:
            log(size_verdict)

        modalities = sorted(route.get("by_modality", {}))
        modalities = [name for name in modalities if name != "unknown"]
        preflight_path = outdir / "preflight.json"
        if not pipe.skip("preflight", [preflight_path]):
            preflight_cmd = [
                sys.executable, str(HERE / "check_deps.py"),
                "--modalities", ",".join(modalities + ["report"]), "--json",
            ]
            started = time.monotonic()
            record_stage(pipe.state, "preflight", "running",
                         command=preflight_cmd, evidence=[str(preflight_path)])
            pipe.save()
            proc = subprocess.run(
                preflight_cmd, cwd=ROOT, text=True, encoding="utf-8",
                errors="replace", capture_output=True,
                env={**os.environ, "PYTHONUTF8": "1", "PYTHONHASHSEED": "0"},
            )
            try:
                preflight = json.loads(proc.stdout)
            except Exception:
                preflight = {"missing_required": ["unknown"],
                             "raw_stdout": proc.stdout,
                             "raw_stderr": proc.stderr}
            preflight_path.write_text(
                json.dumps(preflight, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            if proc.returncode != 0:
                record_stage(
                    pipe.state, "preflight", "blocked",
                    evidence=[str(preflight_path)], command=preflight_cmd,
                    message=proc.stderr or proc.stdout,
                    duration_ms=int((time.monotonic() - started) * 1000),
                )
                mark_run(pipe.state, "blocked",
                         message="required dependencies are missing")
                pipe.save()
                print("missing required dependencies: %s"
                      % ", ".join(preflight.get("missing_required") or []),
                      file=sys.stderr)
                return 2
            record_stage(
                pipe.state, "preflight", "completed",
                evidence=[str(preflight_path)], command=preflight_cmd,
                duration_ms=int((time.monotonic() - started) * 1000),
            )
            pipe.save()
            log("preflight: dependencies OK")

        files = route.get("files") or []
        full_tabular = (
            not options.get("profile_only")
            and len(files) == 1
            and files[0].get("modality") == "tabular"
        )
        single_timeseries = (
            not options.get("profile_only")
            and len(files) == 1
            and files[0].get("modality") == "time-series"
        )
        pipe.state["stage_order"] = (
            list(STAGE_ORDER) if full_tabular
            else (list(PROFILE_ONLY_STAGES[:4]) + ["timeseries"]
                  + list(PROFILE_ONLY_STAGES[4:]) if single_timeseries
                  else list(PROFILE_ONLY_STAGES))
        )
        pipe.state["execution_mode"] = (
            "full-tabular" if full_tabular
            else "time-series" if single_timeseries
            else "profile-only")
        pipe.save()

        profile_path, _ = profile_all(
            pipe, route, outdir, options.get("modality")
        )
        profile = read_json(profile_path)

        # ---- run-level answers: validate and merge before any stage uses them
        if options.get("answers"):
            applied_run = apply_answers_run_block(
                options["answers"], options, outdir / "analysis" / "profile.json")
            if applied_run:
                pipe.state.setdefault("options_from_answers", {}).update(applied_run)
                pipe.save()
                log("answers run block applied: %s"
                    % ", ".join("%s=%s" % kv for kv in sorted(applied_run.items())))

        if full_tabular:
            input_path = Path(files[0]["path"]).resolve()
            code = run_full_tabular(
                pipe, input_path, outdir, options, profile
            )
        elif single_timeseries:
            log("execution mode: time-series (descriptive statistics; "
                "no forecast or causal claim)")
            ts_input = Path(files[0]["path"]).resolve()
            ts_out = outdir / "analysis" / "timeseries.json"
            ts_fig = outdir / "charts" / "fig_ts_overview.png"
            code = pipe.run("timeseries", [
                sys.executable, str(HERE / "timeseries_analysis.py"),
                "--in", str(ts_input),
                "--profile", str(profile_path),
                "--out", str(ts_out),
                "--fig", str(ts_fig),
                "--title", str(options["title"]),
            ], [ts_out])
            if code:
                return code
            code = run_profile_only(pipe, outdir, options, profile_path, route_path)
        else:
            log("execution mode: profile-only (no inferential claim will be made)")
            code = run_profile_only(pipe, outdir, options, profile_path, route_path)
        if code:
            mark_run(pipe.state, "failed", message="pipeline returned %d" % code)
            pipe.save()
            return code
        mark_run(pipe.state, "completed")
        pipe.save()

        if options.get("export_lockfile"):
            lock = export_lockfile(outdir)
            record_stage(pipe.state, "lockfile", "completed", evidence=[str(lock)],
                         message="exact dependency versions snapshotted")
            pipe.save()
            log("lockfile: %s" % lock)

        print()
        log("complete: %s" % outdir)
        print("  report:  %s" % (outdir / "report.pdf"))
        print("  markdown:%s" % (outdir / "report.md"))
        print("  audit:   %s" % pipe.state.get("audit_verdict", "n/a"))
        print("  state:   %s" % state_path)
        template = outdir / "answers.template.json"
        if template.exists():
            print("  answers: %s holds the decisions the pipeline will not "
                  "make; fill it and re-run with --answers" % template)
        if full_tabular and pipe.state.get("audit_verdict") != "SUBMISSION-READY":
            print("  note:    report is complete but not submission-ready; "
                  "see audit/final_audit.md")
        return 0
    except Exception as exc:
        mark_run(pipe.state, "failed", message="%s: %s" % (type(exc).__name__, exc))
        pipe.save()
        print("pipeline failed: %s: %s" % (type(exc).__name__, exc),
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
