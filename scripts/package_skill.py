#!/usr/bin/env python3
"""Build a deterministic, installable data-master .skill archive."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SKIP_PARTS = {".git", "__pycache__", "outputs", "node_modules"}


def included_files(root: Path) -> list[Path]:
    manifest = json.loads((root / "skill-package.json").read_text(encoding="utf-8"))
    files: list[Path] = []
    for relative in manifest["include"]:
        item = root / relative
        if not item.exists():
            raise FileNotFoundError("Skill resource is missing: %s" % relative)
        candidates = item.rglob("*") if item.is_dir() else [item]
        for candidate in candidates:
            rel = candidate.relative_to(root)
            if (candidate.is_file() and not candidate.is_symlink()
                    and not any(part in SKIP_PARTS for part in rel.parts)
                    and candidate.suffix != ".pyc"):
                files.append(candidate)
    return sorted(set(files), key=lambda path: path.as_posix())


def build(output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    files = included_files(ROOT)
    if ROOT / "SKILL.md" not in files:
        raise RuntimeError("SKILL.md is not included")
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as archive:
        for source in files:
            relative = source.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo("data-master/" + relative, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if source.suffix == ".py" else 0o644) << 16
            archive.writestr(info, source.read_bytes())
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="dist/data-master-0.2.0.skill")
    args = parser.parse_args(argv)
    try:
        result = build(Path(args.out).resolve())
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print("package_skill: %s" % exc, file=sys.stderr)
        return 1
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
