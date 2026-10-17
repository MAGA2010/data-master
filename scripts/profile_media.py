#!/usr/bin/env python3
"""Profile an image set or an audio set without changing it.

Media files fail differently from tables.  A corrupt JPEG opens without error in
some readers; a 4000x6000 photo and a 64x64 thumbnail sit in the same folder; the
same image is re-exported three times at different sizes; a WAV is clipped or
90% silence.  None of that shows up in a row count.

Perceptual duplicates are detected with a 64-bit average hash.  It is deliberately
crude -- it catches re-encodes and resizes, and it will not catch a crop.  The
profile says which one it is doing.

Usage
    python scripts/profile_media.py --in images/ --kind image --out profile.json
    python scripts/profile_media.py --in audio/  --kind audio --out profile.json
    python scripts/profile_media.py --in mixed/  --kind auto  --out profile.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
import wave
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

SCHEMA_VERSION = "1.0"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
AUDIO_SUFFIXES = {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac", ".wma"}


def _round(v: Any, d: int = 6) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, d)


def ahash(path: Path, size: int = 8) -> Optional[str]:
    """64-bit average hash: resize to 8x8 grey, threshold at the mean."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            small = im.convert("L").resize((size, size), Image.Resampling.LANCZOS)
            arr = np.asarray(small, dtype=float)
        bits = (arr > arr.mean()).flatten()
        value = 0
        for b in bits:
            value = (value << 1) | int(bool(b))
        return "%016x" % value
    except Exception:
        return None


def hamming(a: str, b: str) -> int:
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except Exception:
        return 64


def profile_image(path: Path) -> Dict[str, Any]:
    out: Dict[str, Any] = {"file": path.name, "path": str(path),
                           "bytes": path.stat().st_size,
                           "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    try:
        from PIL import Image
        with Image.open(path) as im:
            im.load()
            out.update({"width": int(im.width), "height": int(im.height),
                        "mode": im.mode, "format": im.format,
                        "aspect_ratio": _round(im.width / im.height if im.height else None, 4),
                        "megapixels": _round(im.width * im.height / 1e6, 3)})
            exif = im.getexif()
            out["has_exif"] = bool(len(exif))
            if exif:
                out["exif_orientation"] = exif.get(274)
            small = im.convert("L")
            arr = np.asarray(small, dtype=float)
            out["mean_brightness"] = _round(arr.mean(), 2)
            out["contrast_sd"] = _round(arr.std(), 2)
            out["nearly_blank"] = bool(arr.std() < 2.0)
        out["ahash"] = ahash(path)
        out["ok"] = True
    except Exception as exc:
        out.update({"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)})
    return out


def _ffprobe(path: Path) -> Optional[Dict[str, Any]]:
    exe = shutil.which("ffprobe")
    if not exe:
        return None
    try:
        p = subprocess.run(
            [exe, "-v", "quiet", "-print_format", "json", "-show_streams",
             "-show_format", str(path)],
            capture_output=True, text=True, timeout=30)
        if p.returncode != 0:
            return None
        doc = json.loads(p.stdout or "{}")
        stream = next((s for s in doc.get("streams", [])
                       if s.get("codec_type") == "audio"), None)
        if not stream:
            return None
        return {"sample_rate": stream.get("sample_rate"),
                "channels": stream.get("channels"),
                "duration_s": doc.get("format", {}).get("duration"),
                "codec": stream.get("codec_name"),
                "bit_rate": doc.get("format", {}).get("bit_rate")}
    except Exception:
        return None


def profile_audio(path: Path) -> Dict[str, Any]:
    out: Dict[str, Any] = {"file": path.name, "path": str(path),
                           "bytes": path.stat().st_size,
                           "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    if path.suffix.lower() == ".wav":
        try:
            with wave.open(str(path), "rb") as w:
                ch, sw, sr, n = (w.getnchannels(), w.getsampwidth(),
                                 w.getframerate(), w.getnframes())
                raw = w.readframes(n)
            out.update({"codec": "pcm", "channels": ch, "sample_width_bytes": sw,
                        "sample_rate": sr, "n_frames": n,
                        "duration_s": _round(n / sr if sr else None, 3)})
            if sw == 2:
                data = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
            elif sw == 1:
                data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 128) / 128.0
            elif sw == 4:
                data = np.frombuffer(raw, dtype="<i4").astype(np.float64) / 2147483648.0
            else:
                data = np.array([], dtype=float)
            if data.size:
                out["peak"] = _round(np.abs(data).max(), 4)
                out["rms"] = _round(np.sqrt(np.mean(data ** 2)), 4)
                out["clip_fraction"] = _round(float((np.abs(data) >= 0.999).mean()), 6)
                frame = max(int(sr * 0.02), 1) * max(ch, 1)
                n_frames = data.size // frame
                if n_frames:
                    rms = np.sqrt((data[:n_frames * frame].reshape(n_frames, frame) ** 2)
                                  .mean(axis=1))
                    out["silence_fraction"] = _round(float((rms < 1e-4).mean()), 4)
            out["ok"] = True
        except Exception as exc:
            out.update({"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)})
        return out

    meta = _ffprobe(path)
    if meta:
        out.update({k: v for k, v in meta.items() if v is not None})
        out["duration_s"] = _round(meta.get("duration_s"), 3)
        out["sample_rate"] = int(meta["sample_rate"]) if meta.get("sample_rate") else None
        out["ok"] = True
    else:
        out.update({"ok": False,
                    "error": "ffprobe is not installed; compressed audio cannot be "
                             "decoded for clipping or silence analysis"})
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="profile an image or audio set")
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--kind", default="auto", choices=["auto", "image", "audio"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--near-duplicate-hamming", type=int, default=4,
                    help="max Hamming distance on the 64-bit aHash (default 4)")
    args = ap.parse_args(argv)

    root = Path(args.inp)
    if not root.exists():
        print("input not found: %s" % root, file=sys.stderr)
        return 2
    files = ([root] if root.is_file() else
             sorted(p for p in root.rglob("*") if p.is_file()))

    kind = args.kind
    if kind == "auto":
        n_img = sum(1 for p in files if p.suffix.lower() in IMAGE_SUFFIXES)
        n_aud = sum(1 for p in files if p.suffix.lower() in AUDIO_SUFFIXES)
        kind = "image" if n_img >= n_aud else "audio"
        if max(n_img, n_aud) == 0:
            print("no image or audio files under %s" % root, file=sys.stderr)
            return 2

    if kind == "image":
        items = [profile_image(p) for p in files if p.suffix.lower() in IMAGE_SUFFIXES]
    else:
        items = [profile_audio(p) for p in files if p.suffix.lower() in AUDIO_SUFFIXES]

    flags: List[Dict[str, Any]] = []
    if not items:
        print("no %s files under %s" % (kind, root), file=sys.stderr)
        return 2

    bad = [i["file"] for i in items if not i.get("ok")]
    if bad:
        flags.append({"type": "unreadable_files", "severity": "P1",
                      "count": len(bad), "examples": bad[:5],
                      "detail": "these files cannot be decoded; a silent skip would "
                                "change the denominator of every downstream figure"})
    exact = Counter(i["sha256"] for i in items)
    exact_dups = sum(c - 1 for c in exact.values() if c > 1)
    if exact_dups:
        flags.append({"type": "byte_identical_duplicates", "severity": "P2",
                      "count": exact_dups,
                      "detail": "byte-identical files inflate the file count"})

    summary: Dict[str, Any] = {"n_files": len(items),
                               "n_ok": sum(1 for i in items if i.get("ok")),
                               "n_unreadable": len(bad)}

    if kind == "image":
        ok = [i for i in items if i.get("ok")]
        if ok:
            widths = [i["width"] for i in ok]
            heights = [i["height"] for i in ok]
            summary.update({
                "width": {"min": min(widths), "max": max(widths),
                          "median": float(np.median(widths))},
                "height": {"min": min(heights), "max": max(heights),
                           "median": float(np.median(heights))},
                "formats": dict(Counter(i["format"] for i in ok)),
                "modes": dict(Counter(i["mode"] for i in ok)),
                "nearly_blank": [i["file"] for i in ok if i.get("nearly_blank")],
                "with_exif": sum(1 for i in ok if i.get("has_exif")),
            })
            near = []
            # Uniform images all hash to the same value, so a blank frame would
            # "match" every other blank frame. They are already reported as
            # nearly_blank; keeping them here would bury the real duplicate.
            hashed = [i for i in ok if i.get("ahash") and not i.get("nearly_blank")]
            for a in range(len(hashed)):
                for b in range(a + 1, len(hashed)):
                    dist = hamming(hashed[a]["ahash"], hashed[b]["ahash"])
                    if dist <= args.near_duplicate_hamming and \
                            hashed[a]["sha256"] != hashed[b]["sha256"]:
                        near.append({"a": hashed[a]["file"], "b": hashed[b]["file"],
                                     "hamming": dist})
            summary["near_duplicate_pairs"] = near[:50]
            summary["hash_method"] = ("64-bit average hash; catches re-encode and resize, "
                                      "not crop")
            if near:
                flags.append({"type": "near_duplicate_images", "severity": "P2",
                              "count": len(near),
                              "detail": "aHash distance <= %d; confirm these are not the "
                                        "same image exported twice"
                                        % args.near_duplicate_hamming})
            if len(set(widths)) > 1:
                flags.append({"type": "mixed_resolutions", "severity": "P3",
                              "detail": "widths range %d-%d; a pixel-level comparison "
                                        "across these images is not valid"
                                        % (min(widths), max(widths))})
    else:
        ok = [i for i in items if i.get("ok")]
        if ok:
            durations = [i["duration_s"] for i in ok if i.get("duration_s")]
            summary.update({
                "total_duration_s": _round(sum(durations), 3) if durations else None,
                "duration_s": ({"min": min(durations), "max": max(durations),
                                "median": float(np.median(durations))}
                               if durations else None),
                "sample_rates": dict(Counter(str(i.get("sample_rate")) for i in ok)),
                "channels": dict(Counter(str(i.get("channels")) for i in ok)),
                "clipped_files": [i["file"] for i in ok
                                  if (i.get("clip_fraction") or 0) > 0.001],
                "mostly_silent_files": [i["file"] for i in ok
                                        if (i.get("silence_fraction") or 0) > 0.5],
            })
            if summary["clipped_files"]:
                flags.append({"type": "clipping", "severity": "P1",
                              "count": len(summary["clipped_files"]),
                              "detail": ">0.1%% of samples sit at full scale; the waveform "
                                        "is truncated and peak amplitude is not a "
                                        "measurement"})
            if summary["mostly_silent_files"]:
                flags.append({"type": "mostly_silent", "severity": "P2",
                              "count": len(summary["mostly_silent_files"]),
                              "detail": "more than half the frames are below -80 dBFS"})
            if len(summary["sample_rates"]) > 1:
                flags.append({"type": "mixed_sample_rates", "severity": "P2",
                              "detail": "sample rates differ across files; resample "
                                        "explicitly or compare features, not waveforms"})
        if kind == "audio" and any("ffprobe" in str(i.get("error", "")) for i in items):
            flags.append({"type": "decoder_missing", "severity": "P2",
                          "detail": "compressed audio was not decoded; install ffmpeg "
                                    "to measure clipping and silence"})

    profile = {
        "schema_version": SCHEMA_VERSION,
        "source": str(root),
        "modality": "image-set" if kind == "image" else "audio-set",
        "generated": datetime.now(timezone.utc).isoformat(),
        "read_mode": "binary",
        "shape": {"n_rows": len(items), "n_cols": 1},
        "summary": summary,
        "items": items,
        "columns": {}, "column_roles": {},
        "anomalies": {"flags": flags},
        "target_candidate": None,
        "group_candidate": {"candidates": [], "rejected": [
            {"column": "file", "reason": "a filename is not a grouping variable"}]},
        "independent_unit_hint": "one %s file" % kind,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(profile, indent=2, ensure_ascii=False),
                              encoding="utf-8")
    print("profile_media: %d %s file(s), %d unreadable, %d flag(s) -> %s"
          % (len(items), kind, len(bad), len(flags), args.out))
    return 0 if len(bad) < len(items) else 1


if __name__ == "__main__":
    raise SystemExit(main())
