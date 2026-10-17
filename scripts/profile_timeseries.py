#!/usr/bin/env python3
"""Profile a time series without changing it.

A timestamped table is not a table with a date column.  The questions that matter
are different: is the interval regular, where are the gaps, is the series long
enough to say anything about trend, and does the sampling change halfway through
(a machine that started logging hourly instead of daily)?  Treating it as a static
table hides every one of those.

The type decision follows the same all-or-nothing rule as the tabular cleaner: a
column becomes the time index only if every non-null value parses.  A 98% parse
rate is not a time series with two bad rows; it is two different columns in one,
and the profile says so instead of picking a winner.

Usage
    python scripts/profile_timeseries.py --in data.csv [--time-col ts] --out profile.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import numpy as np                      # noqa: E402
import pandas as pd                     # noqa: E402

import dm_types                         # noqa: E402

SCHEMA_VERSION = "1.0"
MAX_EXAMPLES = 5


def _jsonable(v: Any) -> Any:
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.isoformat()
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return v


def parse_time(series: pd.Series) -> Tuple[pd.Series, Dict[str, Any]]:
    """All-or-nothing datetime parsing, with the failures kept as evidence."""
    raw = series.astype("string")
    non_null = raw.notna() & (raw.str.strip() != "")
    n_non_null = int(non_null.sum())
    parsed = pd.to_datetime(raw, errors="coerce", format="mixed")
    failed = non_null & parsed.isna()
    n_failed = int(failed.sum())
    ok = n_non_null > 0 and n_failed == 0
    evidence = {
        "n_non_null": n_non_null,
        "n_parsed": int(parsed.notna().sum()),
        "n_failed": n_failed,
        "parse_rate": round(float(parsed.notna().sum()) / n_non_null, 6) if n_non_null else 0.0,
        "all_or_nothing": True,
        "converted": bool(ok),
        "failure_examples": [str(x) for x in raw[failed].head(MAX_EXAMPLES).tolist()],
        "reason": ("every non-null value parses as a timestamp" if ok else
                   "%d of %d non-null value(s) do not parse; the column is kept as "
                   "text rather than coerced with two exceptions" % (n_failed, n_non_null)),
    }
    return (parsed if ok else pd.Series(pd.NaT, index=series.index)), evidence


def find_time_column(df: pd.DataFrame, forced: Optional[str]) -> Tuple[Optional[str], Dict[str, Any]]:
    if forced:
        if forced not in df.columns:
            raise SystemExit("--time-col %r is not a column; available: %s"
                             % (forced, ", ".join(df.columns)))
        return forced, {"origin": "user", "rule_source": "argument --time-col"}
    best = None
    for col in df.columns:
        parsed, ev = parse_time(df[col])
        if not ev["converted"]:
            continue
        uniq = parsed.nunique(dropna=True)
        # A time index needs more than one instant, and should not be a constant.
        if uniq < 2:
            continue
        score = ev["parse_rate"] * math.log1p(uniq)
        if best is None or score > best[0]:
            best = (score, col, ev)
    if best is None:
        return None, {"origin": "auto", "reason": "no column parses completely as timestamps"}
    return best[1], {"origin": "auto", "score": round(best[0], 6),
                     "rule_source": "profile_timeseries.py#find_time_column",
                     "evidence": best[2]}


def interval_profile(ts: pd.Series) -> Dict[str, Any]:
    """Regularity, gaps and sampling-regime changes."""
    ordered = ts.dropna().sort_values()
    if len(ordered) < 2:
        return {"n": int(len(ordered)), "regular": None,
                "reason": "fewer than two timestamps"}
    deltas = ordered.diff().dropna()
    secs = deltas.dt.total_seconds()
    mode = secs.mode()
    step = float(mode.iloc[0]) if len(mode) else float(secs.median())
    tol = max(step * 0.05, 1e-6)
    on_step = (secs - step).abs() <= tol
    gaps = []
    for idx, d in zip(deltas.index[~on_step], secs[~on_step]):
        gaps.append({"at": _jsonable(ordered.loc[idx]), "seconds": float(d)})
        if len(gaps) >= 10:
            break
    # Regime change: compare the head and the tail, not thirds.  A sensor that
    # switches to a finer interval for the last few hours moves fewer than a
    # third of the rows, so a third-vs-third comparison reports "no change" for
    # exactly the case it was written to catch.
    window = max(5, len(secs) // 10)
    first_med = float(secs.iloc[:window].median())
    last_med = float(secs.iloc[-window:].median())
    regime_change = (first_med > 0 and
                     abs(math.log10(max(last_med, 1e-9) / first_med)) > 0.5)
    return {
        "n": int(len(ordered)),
        "step_seconds": step,
        "step_human": human_seconds(step),
        "regular": bool(on_step.mean() >= 0.95),
        "on_step_fraction": round(float(on_step.mean()), 6),
        "n_gaps": int((~on_step).sum()),
        "gaps": gaps,
        "first_timestamp": _jsonable(ordered.iloc[0]),
        "last_timestamp": _jsonable(ordered.iloc[-1]),
        "regime_change_suspected": bool(regime_change),
        "head_median_seconds": first_med,
        "tail_median_seconds": last_med,
        "rule_source": "profile_timeseries.py#interval_profile",
    }


def human_seconds(s: float) -> str:
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if s >= size and abs(s / size - round(s / size)) < 0.01:
            n = int(round(s / size))
            return "%d %s%s" % (n, unit, "" if n == 1 else "s")
    if s >= 1:
        return "%.3g seconds" % s
    return "%.3g seconds" % s


def value_profile(series: pd.Series, name: str) -> Dict[str, Any]:
    numeric = pd.to_numeric(series, errors="coerce")
    n = int(numeric.notna().sum())
    out: Dict[str, Any] = {"column": name, "n_numeric": n,
                           "n_missing": int(series.isna().sum() + (series.astype(str).str.strip() == "").sum())}
    if n < 3:
        out["kind"] = "not-numeric"
        return out
    vals = numeric.dropna()
    out.update({
        "kind": "numeric",
        "mean": round(float(vals.mean()), 6),
        "sd": round(float(vals.std(ddof=1)), 6) if n > 1 else None,
        "min": round(float(vals.min()), 6),
        "max": round(float(vals.max()), 6),
        "n_unique": int(vals.nunique()),
        "zero_variance": bool(vals.nunique() <= 1),
    })
    return out


def trend_screen(ts: pd.Series, value: pd.Series) -> Dict[str, Any]:
    """A screen, not a test: is there enough of a slope to be worth modelling?"""
    pair = pd.DataFrame({"t": ts, "y": pd.to_numeric(value, errors="coerce")}).dropna()
    if len(pair) < 10:
        return {"estimable": False, "reason": "fewer than 10 complete pairs"}
    x = (pair["t"] - pair["t"].min()).dt.total_seconds().to_numpy(dtype=float)
    if np.nanmax(x) <= 0:
        return {"estimable": False, "reason": "the timestamps span zero seconds"}
    slope, intercept = np.polyfit(x, pair["y"].to_numpy(dtype=float), 1)
    fitted = slope * x + intercept
    resid = pair["y"].to_numpy(dtype=float) - fitted
    ss_tot = float(((pair["y"] - pair["y"].mean()) ** 2).sum())
    r2 = 1.0 - float((resid ** 2).sum()) / ss_tot if ss_tot > 0 else None
    out = {
        "estimable": True,
        "slope_per_second": float(slope),
        "r_squared": round(r2, 6) if r2 is not None else None,
        "n": int(len(pair)),
        "note": "linear screen only; it does not test stationarity or seasonality",
    }
    try:
        from statsmodels.tsa.stattools import adfuller
        if len(pair) >= 20 and float(pair["y"].std(ddof=1)) > 0:
            stat, p, *_ = adfuller(pair["y"].to_numpy(dtype=float), autolag="AIC")
            out["adf"] = {"statistic": round(float(stat), 6),
                          "p": round(float(p), 6),
                          "interpretation": ("stationarity not rejected"
                                             if p > 0.05 else
                                             "unit-root rejected; treat as stationary")}
    except Exception as exc:
        out["adf"] = {"estimable": False, "reason": "%s: %s" % (type(exc).__name__, exc)}
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="profile a time series")
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--time-col", default=None)
    ap.add_argument("--value-cols", default=None,
                    help="comma-separated; default: every numeric-looking column")
    ap.add_argument("--out", required=True)
    ap.add_argument("--read-mode", default="text", choices=["text", "infer"])
    args = ap.parse_args(argv)

    src = Path(args.inp)
    if not src.exists():
        print("input not found: %s" % src, file=sys.stderr)
        return 2

    df = dm_types.read_table(src, read_mode=args.read_mode)
    time_col, time_evidence = find_time_column(df, args.time_col)

    profile: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "source": str(src),
        "modality": "time-series",
        "generated": datetime.now(timezone.utc).isoformat(),
        "read_mode": args.read_mode,
        "shape": {"n_rows": int(df.shape[0]), "n_cols": int(df.shape[1])},
        "time_column": time_col,
        "time_evidence": time_evidence,
        "columns": {},
        "column_roles": {},
        "anomalies": {"flags": []},
        "target_candidate": None,
        "group_candidate": {"candidates": [], "rejected": []},
        "timeseries_candidate": {},
        "independent_unit_hint": "one row per timestamp",
    }

    if time_col is None:
        profile["anomalies"]["flags"].append({
            "type": "no_time_index",
            "severity": "P1",
            "detail": "no column parses completely as timestamps; this is not a "
                      "time series and must be routed to the tabular branch",
        })
    else:
        ts, ev = parse_time(df[time_col])
        profile["time_evidence"] = dict(time_evidence, parse=ev) \
            if isinstance(time_evidence, dict) else {"parse": ev}
        profile["timeseries_candidate"] = interval_profile(ts)
        dup = ts.dropna().duplicated().sum()
        if dup:
            profile["anomalies"]["flags"].append({
                "type": "duplicate_timestamps", "severity": "P1", "count": int(dup),
                "detail": "%d timestamp(s) appear more than once; a mean per instant is "
                          "not the same as an independent observation per row" % int(dup),
            })
        if not ts.dropna().is_monotonic_increasing:
            profile["anomalies"]["flags"].append({
                "type": "unsorted_or_repeated_time", "severity": "P3",
                "detail": "rows are not in ascending time order; the profile sorts for "
                          "interval analysis but the file was not reordered",
            })
        if profile["timeseries_candidate"].get("n_gaps"):
            profile["anomalies"]["flags"].append({
                "type": "irregular_gaps", "severity": "P2",
                "count": profile["timeseries_candidate"]["n_gaps"],
                "detail": "the sampling interval is not constant; a mean over rows is "
                          "then a mean over sampled instants, not over time",
            })
        if profile["timeseries_candidate"].get("regime_change_suspected"):
            profile["anomalies"]["flags"].append({
                "type": "sampling_regime_change", "severity": "P1",
                "detail": "the median interval in the last third differs from the first "
                          "third by more than 3x; check whether the instrument changed",
            })
        for col in df.columns:
            if col == time_col:
                continue
            profile["column_roles"][col] = "value-candidate"
            profile["columns"][col] = value_profile(df[col], col)

    (Path(args.out)).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(profile, indent=2, ensure_ascii=False,
                                         default=_jsonable), encoding="utf-8")
    flags = profile["anomalies"]["flags"]
    print("profile_timeseries: %s -> %s (time=%s, %d rows, %d flag(s))"
          % (src.name, args.out, time_col or "NONE", df.shape[0], len(flags)))
    return 0 if time_col else 1


if __name__ == "__main__":
    raise SystemExit(main())
