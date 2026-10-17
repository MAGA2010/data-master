"""Build a fixture whose every column is a coercion trap.

Each column is named after the mistake a naive cleaner makes on it. The expected
verdicts are asserted in tests/test_pipeline_invariants.py, so this file and that
test must change together.

Columns that MUST be auto-coerced (parse cleanly, no ambiguity):
  weight_kg      plain numeric text
  turnover       thousands separators only, e.g. "1,234.56"
  signup_date    ISO dates

Columns that MUST NOT be auto-coerced (they parse, but to the WRONG number):
  postcode       leading zeros are data: "02134" -> 2134 would merge two ZIPs
  phone          leading zeros plus separators: "(0123) 456-7890"
  revenue        currency symbol: strip vs divide-by-100 are different answers
  growth_pct     percent sign: 12% could be 12 or 0.12

Columns that must be left alone for lack of evidence:
  mostly_text    only 10% numeric -- below the parse-fraction gate, so no signal
  batch_code     alphanumeric, parses as nothing

Whitespace/case trap:
  region         "  North " / "north" / "NORTH" collapse only after hygiene runs,
                 so the raw level count and the post-hygiene count differ.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

REGIONS = ["North", "South", "East", "West"]
POSTCODES = ["02134", "02139", "10001", "10002", "30301", "30302"]


def build(n: int = 240, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({
        "region": [REGIONS[i] for i in rng.integers(0, len(REGIONS), n)],
        "postcode": [POSTCODES[i] for i in rng.integers(0, len(POSTCODES), n)],
    })

    # ---- whitespace + case: only a hygiene pass reveals the true level count ----
    pad = rng.random(n) < 0.35
    df["region"] = [f"  {v}  " if pad[i] else v for i, v in enumerate(df["region"])]
    flip = rng.random(n) < 0.30
    df["region"] = [v.upper() if flip[i] else v for i, v in enumerate(df["region"])]

    # ---- MUST auto-coerce ----
    df["weight_kg"] = [f"{v:.1f}" for v in rng.normal(72, 11, n)]
    df["turnover"] = [f"{v:,.2f}" for v in rng.lognormal(9, 1.1, n)]
    base = np.datetime64("2024-01-01")
    df["signup_date"] = [str(base + np.timedelta64(int(d), "D"))
                         for d in rng.integers(0, 500, n)]

    # ---- MUST NOT auto-coerce ----
    df["phone"] = [f"(0{100 + int(v)}) 456-{int(w):04d}"
                   for v, w in zip(rng.integers(0, 90, n), rng.integers(0, 9999, n))]
    df["revenue"] = [f"${v:,.2f}" for v in rng.lognormal(10, 0.8, n)]
    df["growth_pct"] = [f"{v:.1f}%" for v in rng.normal(6, 9, n)]

    # ---- no signal: too few numeric values to justify a type change ----
    vals = [f"{v:.1f}" for v in rng.normal(50, 5, n)]
    for i in rng.choice(n, size=int(0.10 * n), replace=False):
        vals[int(i)] = "unknown"
    df["mostly_text"] = vals
    df["batch_code"] = [f"B{v:04d}" for v in rng.integers(0, 400, n)]

    return df


if __name__ == "__main__":
    out = build()
    # next to this script, not next to the caller's cwd: the fixture is an input to
    # tests/ and must not depend on where the generator happened to be invoked.
    path = Path(__file__).resolve().parent / "traps_dirty.csv"
    out.to_csv(path, index=False)
    print(f"wrote {path}: {out.shape[0]} rows x {out.shape[1]} cols")
    for c in out.columns:
        print(f"  {c:<14} {out[c].dtype}  n_unique={out[c].nunique()}")
