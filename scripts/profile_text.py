#!/usr/bin/env python3
"""Profile a text corpus without changing it.

A text corpus has its own failure modes, and none of them are visible in a
row-and-column view: the same document ingested twice under two filenames, a
UTF-8 file that is actually GBK, a 3.4 MB log file sitting next to nine 200-word
notes, a "clean" corpus that is 60% boilerplate.  The profile measures those and
stops there -- cleaning a corpus is a separate, disclosed decision.

Two input shapes are accepted:

    --in <folder>                  every .txt / .md / .csv-as-lines file
    --in <file.csv> --text-col c   one document per row

Usage
    python scripts/profile_text.py --in corpus/ --out profile.json
    python scripts/profile_text.py --in reviews.csv --text-col body --out profile.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import pandas as pd                     # noqa: E402

import dm_types                         # noqa: E402

SCHEMA_VERSION = "1.0"
TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".rst", ".log", ".tsv", ".csv"}

STOPWORDS = set("""a an and are as at be been being but by can could did do does for
from had has have he her here him his how i if in into is it its just like may me more
most my no not of on one only or other our out over own same she should so some such
than that the their them then there these they this those through to too under until
up very was we were what when where which while who why will with would you your""".split())

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]{1,}")
URL_RE = re.compile(r"https?://\S+")
WS_RE = re.compile(r"\s+")


def decode_bytes(path: Path) -> Tuple[str, str, bool]:
    """Try UTF-8 strictly, then GB18030. Report which one worked.

    A silent `errors="replace"` turns an encoding problem into a corpus full of
    U+FFFD, which then profiles as a vocabulary property rather than a defect.
    """
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8"), "utf-8", False
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("gb18030"), "gb18030", True
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace"), "utf-8-replace", True


def tokenise(text: str) -> List[str]:
    return [w.lower() for w in WORD_RE.findall(text)]


def language_mix(text: str) -> Dict[str, Any]:
    cjk = len(CJK_RE.findall(text))
    latin = len(re.findall(r"[A-Za-z]", text))
    total = cjk + latin
    if not total:
        return {"script": "other", "cjk_fraction": 0.0, "latin_fraction": 0.0}
    return {
        "script": ("cjk-dominant" if cjk > latin else
                   "latin-dominant" if latin > cjk * 3 else "mixed"),
        "cjk_fraction": round(cjk / total, 4),
        "latin_fraction": round(latin / total, 4),
    }


def profile_corpus(docs: List[Dict[str, Any]]) -> Dict[str, Any]:
    lengths = sorted(len(d["text"]) for d in docs)
    n = len(docs)
    joined = "\n".join(d["text"] for d in docs)
    tokens = tokenise(joined)
    counts = Counter(tokens)
    content = [(w, c) for w, c in counts.most_common(400) if w not in STOPWORDS]
    hashes = Counter(d["sha256"] for d in docs)
    dup_groups = [h for h, c in hashes.items() if c > 1]

    def quantile(q: float) -> Optional[float]:
        if not lengths:
            return None
        idx = min(len(lengths) - 1, max(0, int(round(q * (len(lengths) - 1)))))
        return float(lengths[idx])

    empty = [d["name"] for d in docs if not d["text"].strip()]
    return {
        "n_documents": n,
        "total_chars": len(joined),
        "n_tokens": len(tokens),
        "vocabulary_size": len(counts),
        "type_token_ratio": round(len(counts) / len(tokens), 6) if tokens else None,
        "chars": {"min": float(lengths[0]) if lengths else None,
                  "q25": quantile(0.25), "median": quantile(0.5),
                  "q75": quantile(0.75), "max": float(lengths[-1]) if lengths else None,
                  "mean": round(sum(lengths) / n, 2) if n else None},
        "empty_documents": empty,
        "duplicate_document_groups": len(dup_groups),
        "duplicate_document_examples": dup_groups[:5],
        "language": language_mix(joined),
        "top_content_terms": [{"term": w, "count": c} for w, c in content[:20]],
        "url_fraction": round(len(URL_RE.findall(joined)) / max(n, 1), 4),
        "whitespace_ratio": round(
            sum(1 for ch in joined if ch.isspace()) / max(len(joined), 1), 4),
        "rule_source": "profile_text.py#profile_corpus",
    }


def read_folder(folder: Path) -> List[Dict[str, Any]]:
    docs = []
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text, encoding, recoded = decode_bytes(path)
        docs.append({
            "name": str(path.relative_to(folder)),
            "path": str(path),
            "text": text,
            "bytes": path.stat().st_size,
            "encoding": encoding,
            "encoding_fallback": recoded,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        })
    return docs


def read_table_column(path: Path, column: str) -> List[Dict[str, Any]]:
    df = dm_types.read_table(path, read_mode="text")
    if column not in df.columns:
        raise SystemExit("--text-col %r is not a column; available: %s"
                         % (column, ", ".join(df.columns)))
    docs = []
    for i, v in enumerate(df[column].tolist()):
        text = "" if v is None or (isinstance(v, float) and math.isnan(v)) else str(v)
        docs.append({
            "name": "row-%d" % (i + 1),
            "path": "%s#%s[%d]" % (path, column, i + 2),
            "text": text,
            "bytes": len(text.encode("utf-8")),
            "encoding": "n/a (already decoded)",
            "encoding_fallback": False,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        })
    return docs


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="profile a text corpus")
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--text-col", default=None,
                    help="column holding one document per row (CSV/TSV input)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-docs", type=int, default=20000)
    args = ap.parse_args(argv)

    src = Path(args.inp)
    if not src.exists():
        print("input not found: %s" % src, file=sys.stderr)
        return 2

    if args.text_col:
        docs = read_table_column(src, args.text_col)
        source_kind = "table-column"
    elif src.is_dir():
        docs = read_folder(src)
        source_kind = "folder"
    elif src.suffix.lower() in {".csv", ".tsv"}:
        print("%s looks tabular; pass --text-col to say which column holds the text"
              % src.name, file=sys.stderr)
        return 2
    else:
        text, encoding, recoded = decode_bytes(src)
        docs = [{"name": src.name, "path": str(src), "text": text,
                 "bytes": src.stat().st_size, "encoding": encoding,
                 "encoding_fallback": recoded,
                 "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}]
        source_kind = "single-file"

    truncated = len(docs) > args.max_docs
    docs = docs[:args.max_docs]

    corpus = profile_corpus(docs)
    flags = []
    if corpus["empty_documents"]:
        flags.append({"type": "empty_documents", "severity": "P2",
                      "count": len(corpus["empty_documents"]),
                      "detail": "empty files are not empty documents; they are usually a "
                                "failed export"})
    if corpus["duplicate_document_groups"]:
        flags.append({"type": "duplicate_documents", "severity": "P1",
                      "count": corpus["duplicate_document_groups"],
                      "detail": "byte-identical documents inflate every frequency count; "
                                "deduplicate only with an explicit decision"})
    fallback = [d["name"] for d in docs if d["encoding_fallback"]]
    if fallback:
        flags.append({"type": "encoding_fallback", "severity": "P2",
                      "count": len(fallback),
                      "detail": "decoded as GB18030 or with replacement characters; "
                                "verify a sample before trusting the vocabulary",
                      "examples": fallback[:5]})
    if corpus["chars"]["max"] and corpus["chars"]["median"] and \
            corpus["chars"]["max"] > 20 * corpus["chars"]["median"]:
        flags.append({"type": "length_skew", "severity": "P2",
                      "detail": "the longest document is more than 20x the median; a "
                                "per-document mean is dominated by one file"})
    if truncated:
        flags.append({"type": "sampled", "severity": "P2",
                      "detail": "profile computed on the first %d documents" % args.max_docs})

    profile = {
        "schema_version": SCHEMA_VERSION,
        "source": str(src),
        "source_kind": source_kind,
        "modality": "text-corpus",
        "generated": datetime.now(timezone.utc).isoformat(),
        "read_mode": "text",
        "sampled": truncated,
        "shape": {"n_rows": len(docs), "n_cols": 1},
        "corpus": corpus,
        "documents": [{"name": d["name"], "path": d["path"], "bytes": d["bytes"],
                       "chars": len(d["text"]), "encoding": d["encoding"],
                       "sha256": d["sha256"]}
                      for d in docs],
        "columns": {"text": {"dtype": "string", "n_missing": len(corpus["empty_documents"]),
                             "n_unique": corpus["vocabulary_size"]}},
        "column_roles": {"text": "document-body"},
        "anomalies": {"flags": flags},
        "target_candidate": None,
        "group_candidate": {"candidates": [], "rejected": [
            {"column": "text", "reason": "free text cannot define comparison groups "
                                         "without an explicit labelling step"}]},
        "independent_unit_hint": ("one document" if source_kind != "table-column"
                                  else "one row"),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(profile, indent=2, ensure_ascii=False),
                              encoding="utf-8")
    print("profile_text: %d document(s), %d tokens, %d flag(s) -> %s"
          % (len(docs), corpus["n_tokens"], len(flags), args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
