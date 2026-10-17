"""Small, dependency-free state store for the one-command pipeline.

The state file is intentionally a readable JSON ledger rather than an opaque
cache. It records the input fingerprint, the options used for the run, and the
evidence produced by each completed stage. A cold resume is allowed only when
the input fingerprint still matches.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

STATE_SCHEMA = "1.0"

STAGE_ORDER = [
    "input",
    "route",
    "preflight",
    "profile",
    "cleaning_plan",
    "cleaning_execute",
    "cleaning_validate",
    "descriptive",
    "inferential",
    "chart_decisions",
    "charts",
    "report",
    "audit",
]

PROFILE_ONLY_STAGES = ["input", "route", "preflight", "profile", "report", "audit"]

_SKIP_DIRS = {
    ".git", ".hg", ".svn", ".codex-preview", "__pycache__",
    ".pytest_cache", ".ruff_cache", "outputs",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def input_fingerprint(path: Path, exclude: Optional[Path] = None) -> Dict[str, Any]:
    """Hash a file or a directory without hashing generated output directories."""
    path = path.resolve()
    exclude = exclude.resolve() if exclude else None
    if path.is_file():
        return {
            "kind": "file",
            "path": str(path),
            "sha256": _sha256_file(path),
            "bytes": path.stat().st_size,
            "files": 1,
        }
    if not path.is_dir():
        raise FileNotFoundError(str(path))

    files: List[Path] = []
    for current, dirs, names in os.walk(path):
        cur = Path(current)
        dirs[:] = sorted(
            d for d in dirs
            if d not in _SKIP_DIRS and not d.startswith(".")
            and (exclude is None or (cur / d).resolve() != exclude)
        )
        for name in sorted(names):
            candidate = (cur / name).resolve()
            if exclude and (candidate == exclude or exclude in candidate.parents):
                continue
            if name.startswith("."):
                continue
            files.append(candidate)

    h = hashlib.sha256()
    total = 0
    for candidate in sorted(files):
        rel = candidate.relative_to(path).as_posix()
        size = candidate.stat().st_size
        total += size
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(str(size).encode("ascii"))
        h.update(b"\0")
        h.update(_sha256_file(candidate).encode("ascii"))
        h.update(b"\n")
    return {
        "kind": "directory",
        "path": str(path),
        "sha256": h.hexdigest(),
        "bytes": total,
        "files": len(files),
    }


def paths_fingerprint(paths: Iterable[Path], label: str) -> Dict[str, Any]:
    """Fingerprint an explicit file list, for glob inputs."""
    resolved = sorted(path.resolve() for path in paths)
    h = hashlib.sha256()
    total = 0
    for path in resolved:
        size = path.stat().st_size
        total += size
        h.update(path.name.encode("utf-8"))
        h.update(b"\0")
        h.update(str(size).encode("ascii"))
        h.update(b"\0")
        h.update(_sha256_file(path).encode("ascii"))
        h.update(b"\n")
    return {
        "kind": "set",
        "path": label,
        "sha256": h.hexdigest(),
        "bytes": total,
        "files": len(resolved),
        "paths": [str(path) for path in resolved],
    }


def atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def load_state(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def new_state(
    input_meta: Dict[str, Any],
    outdir: Path,
    options: Dict[str, Any],
    stages: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    now = utc_now()
    return {
        "schema_version": STATE_SCHEMA,
        "status": "running",
        "started_at": now,
        "updated_at": now,
        "completed_at": None,
        "input": input_meta,
        "outdir": str(outdir.resolve()),
        "options": options,
        "stage_order": list(stages or STAGE_ORDER),
        "current_stage": None,
        "stages": {},
        "warnings": [],
    }


def record_stage(
    state: Dict[str, Any],
    stage: str,
    status: str,
    *,
    evidence: Optional[Iterable[str]] = None,
    command: Optional[List[str]] = None,
    message: Optional[str] = None,
    duration_ms: Optional[int] = None,
) -> Dict[str, Any]:
    now = utc_now()
    previous = (state.get("stages") or {}).get(stage) or {}
    entry = dict(previous)
    entry.update({
        "status": status,
        "updated_at": now,
        "evidence": list(evidence or []),
    })
    if command is not None:
        entry["command"] = list(command)
    if message is not None:
        entry["message"] = message
    if duration_ms is not None:
        entry["duration_ms"] = duration_ms
    if status == "running" and "started_at" not in entry:
        entry["started_at"] = now
    if status in ("completed", "failed", "blocked", "skipped", "not_applicable"):
        entry["finished_at"] = now
    state.setdefault("stages", {})[stage] = entry
    state["current_stage"] = stage if status == "running" else None
    state["updated_at"] = now
    return state


def mark_run(
    state: Dict[str, Any],
    status: str,
    *,
    message: Optional[str] = None,
) -> Dict[str, Any]:
    state["status"] = status
    state["updated_at"] = utc_now()
    if status in ("completed", "failed", "blocked"):
        state["completed_at"] = state["updated_at"]
    if message:
        state.setdefault("warnings", []).append(message)
    return state


def stage_completed(state: Dict[str, Any], stage: str, evidence: Iterable[str]) -> bool:
    entry = (state.get("stages") or {}).get(stage) or {}
    if entry.get("status") != "completed":
        return False
    for raw in evidence:
        if not Path(raw).exists():
            return False
    return True


def first_incomplete(state: Dict[str, Any]) -> Optional[str]:
    stages = state.get("stages") or {}
    for stage in state.get("stage_order") or STAGE_ORDER:
        if (stages.get(stage) or {}).get("status") != "completed":
            return stage
    return None


def stage_summary(state: Dict[str, Any]) -> Dict[str, Any]:
    stages = state.get("stages") or {}
    order = state.get("stage_order") or STAGE_ORDER
    return {
        "status": state.get("status"),
        "input": state.get("input", {}).get("path"),
        "outdir": state.get("outdir"),
        "completed": sum(
            1 for name in order
            if (stages.get(name) or {}).get("status") == "completed"
        ),
        "total": len(order),
        "next": first_incomplete(state),
        "audit_verdict": state.get("audit_verdict"),
        "stages": {
            name: (stages.get(name) or {}).get("status", "pending")
            for name in order
        },
    }
