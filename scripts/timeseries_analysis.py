#!/usr/bin/env python3
"""Audited descriptive statistics for a single time-series column.

Time-series inputs used to stop at profiling. This stage adds the statistics
that are defensible without a forecast or a causal claim, each with its test
name, n, and interval, in the same JSON discipline as the tabular pipeline:

  mann_kendall    rank trend test (S, z, two-sided p) with Kendall tau
  theil_sen       Sen's slope with a 95% CI -- the slope half of the trend
  acf / pacf      autocorrelation / partial autocorrelation with white-noise
                  bounds and the lags that exceed them
  stl             seasonal-trend decomposition with trend and seasonal
                  strength (Wang/Smith-Hyndman), when the sampling is regular
                  enough to define a period
  changepoint     CUSUM screen on the detrended residuals, with a bootstrap
                  p-value under a no-change null (seeded)

What this stage deliberately does NOT do: forecast, fit an ARIMA, or claim a
cause. A trend test says the series drifted; it does not say why, and a
changepoint candidate is a place to look, not a mechanism.

Usage:
    python timeseries_analysis.py --in sensor_log.csv \
        --profile analysis/profile.json \
        --out analysis/timeseries.json --fig charts/fig_ts_overview.png
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats as sps

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

ALPHA = 0.05
SEED = 42
BOOTSTRAP = 500
MIN_N = 20


# ------------------------------------------------------------------ statistics

def mann_kendall(x: np.ndarray) -> Dict[str, Any]:
    """Mann-Kendall trend test with tie-corrected variance and Kendall tau."""
    n = len(x)
    s = 0
    for i in range(n - 1):
        s += int(np.sign(x[i + 1:] - x[i]).sum())
    # tie correction
    _, counts = np.unique(x, return_counts=True)
    tie_term = sum(int(t * (t - 1) * (2 * t + 5)) for t in counts if t > 1)
    var_s = (n * (n - 1) * (2 * n + 5) - tie_term) / 18.0
    if var_s <= 0:
        return {"estimable": False, "reason": "no variability to rank"}
    if s > 0:
        z = (s - 1) / np.sqrt(var_s)
    elif s < 0:
        z = (s + 1) / np.sqrt(var_s)
    else:
        z = 0.0
    p = 2.0 * sps.norm.sf(abs(float(z)))
    tau = float(s) / (0.5 * n * (n - 1))
    return {
        "estimable": True,
        "method": "Mann-Kendall trend test (two-sided, tie-corrected)",
        "statistic_name": "S", "statistic": int(s),
        "z": round(float(z), 5),
        "p_raw": float(p),
        "kendall_tau": round(tau, 5),
        "n": n,
        "verdict": ("no detectable monotone trend" if p >= ALPHA
                    else f"{'upward' if s > 0 else 'downward'} monotone trend "
                         f"detected at alpha={ALPHA}"),
        "rule_source": "scripts/timeseries_analysis.py#mann_kendall",
    }


def sen_slope(x: np.ndarray, t: Optional[np.ndarray] = None) -> Dict[str, Any]:
    """Theil-Sen slope with a 95% CI, plus a per-day reading when t is seconds."""
    n = len(x)
    tt = np.arange(n, dtype=float) if t is None else np.asarray(t, dtype=float)
    res = sps.theilslopes(x, tt, alpha=0.95)
    slope, lo, hi = float(res[0]), float(res[2]), float(res[3])
    out: Dict[str, Any] = {
        "estimable": True,
        "method": "Theil-Sen slope (median of pairwise slopes), 95% CI",
        "slope_per_step": round(slope, 8),
        "ci95": [round(lo, 8), round(hi, 8)],
        "n": n,
        "excludes_zero": bool(lo > 0 or hi < 0),
        "rule_source": "scripts/timeseries_analysis.py#sen_slope",
    }
    if t is not None and len(np.unique(tt)) > 1:
        step = float(np.median(np.diff(np.sort(tt))))
        if step > 0:
            out["step_unit"] = "seconds"
            out["slope_per_day"] = round(slope * 86400.0 / step, 8)
            out["ci95_per_day"] = [round(lo * 86400.0 / step, 8),
                                   round(hi * 86400.0 / step, 8)]
    return out


def acf_pacf(x: np.ndarray, nlags: int) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    try:
        from statsmodels.tsa.stattools import acf as sm_acf, pacf as sm_pacf
    except Exception as exc:
        return {"estimable": False,
                "reason": f"statsmodels unavailable ({exc}); ACF/PACF skipped"}
    lag = min(nlags, max(1, len(x) // 5))
    a, aci = sm_acf(x, nlags=lag, alpha=ALPHA, fft=True, result_object=False)
    p, pci = sm_pacf(x, nlags=lag, alpha=ALPHA, method="ywm",
                     result_object=False)
    out.update({
        "estimable": True,
        "nlags": lag,
        "acf": [round(float(v), 5) for v in a],
        "acf_ci95": [[round(float(c[0]), 5), round(float(c[1]), 5)] for c in aci],
        "acf_significant_lags": [int(i) for i in range(1, lag + 1)
                                 if abs(a[i]) > max(abs(aci[i][0]), abs(aci[i][1]))],
        "pacf": [round(float(v), 5) for v in p],
        "pacf_ci95": [[round(float(c[0]), 5), round(float(c[1]), 5)] for c in pci],
        "pacf_significant_lags": [int(i) for i in range(1, lag + 1)
                                  if abs(p[i]) > max(abs(pci[i][0]), abs(pci[i][1]))],
        "bounds_note": f"white-noise {int((1-ALPHA)*100)}% bounds; a lag is "
                       "'significant' only when its bar exceeds them",
        "rule_source": "scripts/timeseries_analysis.py#acf_pacf",
    })
    return out


def stl_decomposition(x: np.ndarray, period: int) -> Dict[str, Any]:
    try:
        from statsmodels.tsa.seasonal import STL
    except Exception as exc:
        return {"estimable": False,
                "reason": f"statsmodels unavailable ({exc}); STL skipped"}
    if period is None or period < 2 or len(x) < 2 * period:
        return {"estimable": False, "period": period,
                "reason": "sampling too irregular to define a period, or the "
                          "series is shorter than two periods"}
    res = STL(pd.Series(x), period=period, robust=True).fit()
    t_, s_, r_ = (np.asarray(res.trend), np.asarray(res.seasonal),
                  np.asarray(res.resid))
    def strength(comp: np.ndarray) -> float:
        denom = float(np.var(comp + r_, ddof=1))
        return max(0.0, 1.0 - float(np.var(r_, ddof=1)) / denom) if denom > 0 else 0.0
    return {
        "estimable": True,
        "method": f"STL decomposition (robust, period={period})",
        "period": period,
        "trend_strength": round(strength(t_), 5),
        "seasonal_strength": round(strength(s_), 5),
        "strength_note": "Wang/Smith-Hyndman: 0 = none of that component, "
                         "1 = the residual explains nothing beyond it",
        "n": int(len(x)),
        "rule_source": "scripts/timeseries_analysis.py#stl_decomposition",
    }


def cusum_changepoint(resid: np.ndarray) -> Dict[str, Any]:
    """CUSUM screen with a permutation p-value under a no-change null.

    The test statistic is the maximum absolute cumulative sum of the centred
    residuals. The null distribution is the same statistic on permuted
    residuals (same values, order destroyed), so any autocorrelation that
    permutation does not destroy is treated as signal, which is the
    conservative direction for a screen whose output is a place to look.
    """
    r = np.asarray(resid, dtype=float)
    n = len(r)
    if n < MIN_N:
        return {"estimable": False, "reason": f"n={n} < {MIN_N}"}
    r = (r - r.mean()) / (r.std(ddof=1) or 1.0)
    def _maxcusum(v: np.ndarray) -> float:
        return float(np.max(np.abs(np.cumsum(v))))
    observed = _maxcusum(r)
    rng = np.random.default_rng(SEED)
    null = np.array([_maxcusum(rng.permutation(r)) for _ in range(BOOTSTRAP)])
    p = float((np.sum(null >= observed) + 1) / (BOOTSTRAP + 1))
    idx = int(np.argmax(np.abs(np.cumsum(r))))
    return {
        "estimable": True,
        "method": f"CUSUM screen on detrended residuals "
                  f"(permutation null, {BOOTSTRAP} draws, seed={SEED})",
        "statistic_name": "max|CUSUM|", "statistic": round(observed, 5),
        "p_raw": p,
        "candidate_index": idx,
        "verdict": ("no changepoint detected at alpha=%s" % ALPHA if p >= ALPHA
                    else "changepoint candidate detected at alpha=%s -- a place "
                         "to look, not a mechanism" % ALPHA),
        "rule_source": "scripts/timeseries_analysis.py#cusum_changepoint",
    }


def guess_period(step_seconds: Optional[float]) -> Optional[int]:
    if not step_seconds or step_seconds <= 0:
        return None
    if step_seconds < 86400:
        return max(2, int(round(86400.0 / step_seconds)))
    if abs(step_seconds - 86400.0) < 1:
        return 7
    return None


# --------------------------------------------------------------------- figure

def render_overview(times: np.ndarray, values: np.ndarray, trend: np.ndarray,
                    sen: Dict[str, Any], cp: Optional[Dict[str, Any]],
                    acf_block: Dict[str, Any], out: Path, title: str,
                    value_col: str) -> Dict[str, Any]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from render_chart import _finish
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8.6, 5.6),
                                   gridspec_kw={"height_ratios": [2.2, 1.0]})
    ax1.plot(times, values, color="#1f77b4", linewidth=0.9, alpha=0.8,
             label="observed")
    ax1.plot(times, trend, color="#ff7f0e", linewidth=2.0,
             label="STL trend" if trend is not None else "trend")
    if sen.get("estimable"):
        lo, hi = sen["ci95"]
        idx = np.arange(len(values), dtype=float)
        anchor = float(values[0])
        ax1.plot(times, sen["slope_per_step"] * idx + anchor,
                 color="#8a4b00", linewidth=1.4, label="Sen slope")
        ax1.plot(times, lo * idx + anchor, linestyle="--", linewidth=1.0,
                 color="#8a4b00", alpha=0.6, label="Sen slope 95% CI")
        ax1.plot(times, hi * idx + anchor, linestyle="--", linewidth=1.0,
                 color="#8a4b00", alpha=0.6)
    cp_drawn = bool(cp and cp.get("estimable") and cp.get("p_raw", 1.0) < ALPHA)
    if cp_drawn:
        ax1.axvline(times[cp["candidate_index"]], color="#d62728",
                    linestyle=":", linewidth=1.6,
                    label="changepoint candidate")
    ax1.set_ylabel(value_col)
    n_handles = len(ax1.get_legend_handles_labels()[0])
    ax1.legend(fontsize=7.5, frameon=False, loc="upper center",
               bbox_to_anchor=(0.5, -0.16), ncol=min(4, n_handles),
               columnspacing=1.2, handletextpad=0.5)

    if acf_block.get("estimable"):
        a = np.asarray(acf_block["acf"])
        ci = np.asarray(acf_block["acf_ci95"])
        lags = np.arange(len(a))
        ax2.bar(lags, a, width=0.5, color="#1f77b4", alpha=0.85)
        half = (ci[:, 1] - ci[:, 0]) / 2.0
        ax2.errorbar(lags, a, yerr=half, fmt="none", ecolor="#333333",
                     elinewidth=0.8, capsize=1.5)
        ax2.axhline(0.0, color="#222222", linewidth=0.8)
        ax2.set_xlabel("lag")
        ax2.set_ylabel("autocorrelation")
    decision = {"id": "fig_ts_overview", "title": title,
                "chart_type": "ts_overview"}
    # the caption names only what the figure actually shows: a marker clause on
    # a figure with no detected changepoint would point at nothing
    caption = ("Trend line and slope band describe drift, not cause."
               + (" The dotted marker is a candidate location from a "
                  "permutation screen, not a dated event." if cp_drawn else "")
               + " A lag is notable only when its bar exceeds the bounds.")
    return _finish(fig, [ax1, ax2], out, decision, caption)


# ----------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--profile", default=None,
                    help="profile.json from profile_timeseries.py (reuses the "
                         "detected time column and sampling)")
    ap.add_argument("--value", default=None,
                    help="value column (default: first numeric non-time column)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--fig", default=None, help="overview figure path")
    ap.add_argument("--title", default=None)
    args = ap.parse_args()

    profile: Dict[str, Any] = {}
    if args.profile and Path(args.profile).exists():
        try:
            profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
        except Exception:
            profile = {}
    time_col = profile.get("time_column")
    ts_cand = profile.get("timeseries_candidate") or {}

    df = pd.read_csv(args.inp)
    if time_col is None or time_col not in df.columns:
        for c in df.columns:
            parsed = pd.to_datetime(df[c], errors="coerce")
            if parsed.notna().mean() > 0.8:
                time_col = c
                break
    if time_col is None:
        print("ERROR: no parseable timestamp column found", file=sys.stderr)
        return 1
    ts = pd.to_datetime(df[time_col], errors="coerce")
    value_col = args.value
    if value_col is None:
        for c in df.columns:
            if c == time_col:
                continue
            v = pd.to_numeric(df[c], errors="coerce")
            if v.notna().sum() >= MIN_N:
                value_col = c
                break
    if value_col is None:
        print("ERROR: no numeric value column found", file=sys.stderr)
        return 1

    frame = pd.DataFrame({"t": ts, "v": pd.to_numeric(df[value_col],
                                                      errors="coerce")}).dropna()
    n_dup = int(frame["t"].duplicated().sum())
    if n_dup:
        frame = frame.groupby("t", as_index=False)["v"].mean()
    frame = frame.sort_values("t").reset_index(drop=True)
    x = frame["v"].to_numpy(dtype=float)
    n = len(x)
    seconds = (frame["t"].astype("int64") // 10**9).to_numpy(dtype=float)

    base: Dict[str, Any] = {
        "schema_version": "1.0",
        "source": args.inp,
        "time_column": time_col,
        "value_column": value_col,
        "n_obs": n,
        "n_duplicate_timestamps_averaged": n_dup,
        "first_timestamp": str(frame["t"].iloc[0]),
        "last_timestamp": str(frame["t"].iloc[-1]),
        "step_seconds": ts_cand.get("step_seconds"),
        "rule_source": "references/nature-statistics-checklist.md#descriptive-discipline",
    }

    if n < MIN_N:
        base.update({"estimable": False,
                     "reason": f"n={n} < {MIN_N}; no statistic is defensible"})
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(base, indent=2, ensure_ascii=False),
                                  encoding="utf-8")
        print(f"timeseries analysis: n={n} below minimum; written as not estimable")
        return 0

    step = ts_cand.get("step_seconds")
    mk = mann_kendall(x)
    sen = sen_slope(x, seconds if step else None)
    acf_block = acf_pacf(x, nlags=40)
    period = guess_period(step)
    stl_block = stl_decomposition(x, period)
    resid = x
    trend = None
    if stl_block.get("estimable"):
        try:
            from statsmodels.tsa.seasonal import STL
            res = STL(pd.Series(x), period=period, robust=True).fit()
            trend, resid = np.asarray(res.trend), np.asarray(res.resid)
        except Exception:
            trend, resid = None, x
    else:
        # fall back to first differences for the changepoint screen: a raw
        # CUSUM on a trending series detects the trend, which is not news
        resid = np.diff(x)
    cp = cusum_changepoint(resid)

    figure: Optional[Dict[str, Any]] = None
    if args.fig:
        title = args.title or ("%s over %s: %s"
                               % (value_col, time_col,
                                  mk.get("verdict", "overview")))
        try:
            figure = render_overview(frame["t"].to_numpy(), x, trend, sen, cp,
                                     acf_block, Path(args.fig), title, value_col)
        except Exception as exc:
            figure = {"error": "%s: %s" % (type(exc).__name__, exc)}

    base.update({
        "estimable": True,
        "stats": {
            "mann_kendall": mk,
            "sen_slope": sen,
            "acf_pacf": acf_block,
            "stl": stl_block,
            "changepoint": cp,
        },
        "figure": figure,
        "scope_note": "descriptive and screening statistics only: no forecast, "
                      "no ARIMA fit, no causal claim; a trend names a drift, "
                      "a changepoint names a place to look",
    })
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(base, indent=2, ensure_ascii=False,
                                         default=str), encoding="utf-8")
    print(f"timeseries analysis written: {args.out}")
    print(f"  n={n}  duplicates averaged={n_dup}  period={period}")
    if mk.get("estimable"):
        print("  trend : %s (tau=%s, p=%s)"
              % (mk["verdict"], mk["kendall_tau"], mk["p_raw"]))
    if sen.get("estimable"):
        print("  slope : %s per step, 95%% CI [%s, %s]"
              % (sen["slope_per_step"], *sen["ci95"]))
    if cp.get("estimable"):
        print("  change: %s (p=%s)" % (cp["verdict"], cp["p_raw"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
