#!/usr/bin/env python3
"""Render the decided figures.

Every figure is produced under the same constraints, because the constraints
are what make a set of figures readable as a set:

  * the title is the finding, computed in chart_decision.py, not a topic;
  * every estimate carries its uncertainty -- intervals, a band, a smoother;
  * colour is a secondary channel, so each series also differs by marker and
    line style, and the palette is the colour-blind safer subset;
  * axis labels carry units, and sample sizes are on the figures themselves
    so a reader never has to turn back to a table to check what they are
    looking at.

Images are written at 200 dpi and also re-read and checked: a figure that
silently came out blank is worse than one that failed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import MaxNLocator

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dm_types  # noqa: E402

DPI = 200
# Colour-blind safer subset from the catalogue. Paired with distinct markers so
# the figures survive both a colour-vision deficiency and a grayscale print.
PALETTE = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd"]
MARKERS = ["o", "s", "^", "D", "v"]
LINESTYLES = ["-", "--", "-.", ":"]

plt.rcParams.update({
    "figure.dpi": DPI,
    "savefig.dpi": DPI,
    "font.size": 10,
    "axes.titlesize": 11,
    "axes.labelsize": 10,
    "axes.grid": True,
    "grid.alpha": 0.25,
    "grid.linestyle": ":",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.facecolor": "white",
    "savefig.facecolor": "white",
})


def _wrap_to_figure(fig, text: str, fontsize: float, frac: float = 0.94,
                    weight: str = "normal") -> List[str]:
    """Wrap a title to the figure width by measuring the glyphs.

    suptitle(..., wrap=True) keeps its anchor at y=0.98, so a title that wraps
    to two lines grows *downwards* into whatever was placed just below it.  On
    the three-panel iris figure that drew the title and the subtitle on top of
    each other.

    An earlier version of this function estimated characters-per-line from an
    average glyph width; the iris title then fit "by estimate" and still ran
    off the right edge of the canvas.  This measures the actual rendered width
    of each candidate line with matplotlib's own renderer, so the break is a
    fact rather than a guess.
    """
    try:
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
    except Exception:
        renderer = None

    max_pt = float(fig.get_size_inches()[0]) * 72.0 * frac

    def width_pt(s: str) -> float:
        if renderer is None:
            return len(s) * fontsize * 0.6
        t = fig.text(0, 0, s, fontsize=fontsize, fontweight=weight)
        try:
            return float(t.get_window_extent(renderer=renderer).width) * 72.0 / float(fig.dpi)
        finally:
            t.remove()

    lines: List[str] = []
    cur = ""
    for word in (text or "").split():
        cand = (cur + " " + word).strip()
        if cur and width_pt(cand) > max_pt:
            lines.append(cur)
            cur = word
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines or [""]


def _finish(fig, ax_or_axes, out_path: Path, decision: Dict[str, Any],
            subtitle: str = "") -> Dict[str, Any]:
    axes = ax_or_axes if isinstance(ax_or_axes, (list, np.ndarray)) else [ax_or_axes]
    fig_h = float(fig.get_size_inches()[1])
    title_fs, sub_fs = 12.0, 8.5
    gap_in = 0.10

    y_in = gap_in
    title_lines = _wrap_to_figure(fig, decision["title"], title_fs, weight="bold")
    for line in title_lines:
        y_in += title_fs * 1.30 / 72.0
        fig.text(0.010, 1.0 - y_in / fig_h, line, fontsize=title_fs,
                 fontweight="bold", ha="left", va="top")
    if subtitle:
        y_in += 0.06
        for line in _wrap_to_figure(fig, subtitle, sub_fs):
            y_in += sub_fs * 1.35 / 72.0
            fig.text(0.010, 1.0 - y_in / fig_h, line, fontsize=sub_fs,
                     color="#444444", ha="left", va="top")

    top = 1.0 - (y_in + 0.08) / fig_h
    fig.tight_layout(rect=[0, 0.055, 1, max(0.35, min(0.94, top))])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight", pad_inches=0.06)
    plt.close(fig)

    # A figure that saved but is blank is a failure that no exception reports.
    from PIL import Image
    with Image.open(out_path) as im:
        arr = np.asarray(im.convert("L"))
    distinct = int((arr < 245).sum())
    ratio = distinct / float(arr.size)
    return {"path": str(out_path), "bytes": out_path.stat().st_size,
            "ink_ratio": round(ratio, 5), "non_blank": distinct > 500,
            "pixels": list(im.size)}


# ------------------------------------------------------------------ figures

def render_distribution(df, d: Dict[str, Any], out: Path) -> Dict[str, Any]:
    panels = d["spec"]["panels"]
    n = len(panels)
    fig, axes = plt.subplots(1, n, figsize=(3.5 * n, 3.2))
    if n == 1:
        axes = [axes]
    for ax, p in zip(axes, panels):
        col = p["column"]
        vals = pd_numeric(df, col)
        if len(vals) == 0:
            ax.text(0.5, 0.5, f"{col}: no numeric values", ha="center", va="center")
            continue
        ax.hist(vals, bins="auto", color=PALETTE[0], edgecolor="white",
                linewidth=0.6, alpha=0.85)
        ax.axvline(p["median"], color="#222222", linewidth=1.6, label="median")
        ax.axvspan(p["q25"], p["q75"], color="#ff7f0e", alpha=0.16,
                   label="interquartile range")
        ax.set_title(p["title"].split(" (")[0], fontsize=9.5, loc="left")
        ax.set_ylabel("observations")
        ax.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=4))
        ax.legend(fontsize=7.5, frameon=False, loc="upper right")
        ax.text(0.99, 0.02, f"n = {p['n']:,}", transform=ax.transAxes,
                ha="right", va="bottom", fontsize=8, color="#444444")
    return _finish(fig, axes, out, d,
                   "Median and interquartile range marked on each panel; "
                   "box-and-whisker statistics are in Table 2.")


def render_small_multiples(df, d: Dict[str, Any], out: Path) -> Dict[str, Any]:
    panels = d["spec"]["panels"]
    group = d["spec"]["group"]
    n = len(panels)
    ncol = min(2, n)
    nrow = int(np.ceil(n / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(5.0 * ncol, 3.4 * nrow))
    axes = np.atleast_1d(axes).ravel()
    for ax, p in zip(axes, panels):
        col = p["outcome"]
        levels = list(p["means"].keys())
        xs = np.arange(len(levels))
        means = np.array([p["means"][lv] for lv in levels], dtype=float)
        errs = []
        for lv in levels:
            v = df_numeric(df, col, where=(df[group] == lv))
            n_lv = max(len(v), 1)
            se = float(np.std(v, ddof=1) / np.sqrt(n_lv)) if n_lv > 1 else 0.0
            errs.append(1.96 * se if n_lv > 1 else 0.0)
        errs = np.array(errs)
        cols = [PALETTE[i % len(PALETTE)] for i in range(len(levels))]
        ax.bar(xs, means, yerr=errs, capsize=4, color=cols, edgecolor="white",
               linewidth=0.8, width=0.62,
               error_kw={"ecolor": "#333333", "elinewidth": 1.1})
        # marker + line style on top: colour is not the only channel
        ax.plot(xs, means, ls="none", marker="o", ms=5, mfc="white",
                mec="#222222", mew=1.2, zorder=3)
        ax.set_xticks(xs)
        ax.set_xticklabels([str(lv)[:14] for lv in levels], fontsize=8.5, rotation=0)
        ax.set_title(col, fontsize=9, loc="left")
        ax.set_ylabel("mean ± 95% CI")
        base = 0
        lo = float(np.min(means - errs))
        hi = float(np.max(means + errs))
        span = (hi - lo) or (abs(hi) or 1.0)
        # a truncated y-axis must say so -- the note goes BELOW the axes,
        # because every corner inside the axes is already occupied by a bar
        if lo < 0 and base == 0:
            ax.set_ylim(max(lo - 0.15 * span, 0), hi + 0.2 * span)
        else:
            ax.set_ylim(lo - 0.25 * span, hi + 0.25 * span)
            ax.text(0.99, -0.24, "y-axis does not start at zero",
                    transform=ax.transAxes, ha="right", va="top",
                    fontsize=7, color="#8a4b00")
        sig = "BH-adjusted p = %.3g" % p["p_adjusted"]
        ax.text(0.99, 0.96, sig, transform=ax.transAxes, ha="right", va="top",
                fontsize=8, color="#444444")
    for ax in axes[len(panels):]:
        ax.set_visible(False)
    return _finish(fig, axes.tolist(), out, d,
                   "Points are group means; bars are 95% confidence intervals, "
                   "which overlap wherever the difference is not distinguishable.")


def render_scatter(df, d: Dict[str, Any], out: Path) -> Dict[str, Any]:
    panels = d["spec"]["panels"]
    n = len(panels)
    fig, axes = plt.subplots(1, n, figsize=(4.4 * n, 3.6))
    if n == 1:
        axes = [axes]
    for ax, p in zip(axes, panels):
        x, y = paired_numeric(df, p["x"], p["y"])
        ax.scatter(x, y, s=13, color=PALETTE[0], alpha=0.55,
                   edgecolors="none", marker="o")
        if len(x) >= 12:
            try:
                order = np.argsort(x)
                xs, ys = x[order], y[order]
                # a local window of ~n/6 points: _lowess expects a fraction,
                # so the count is converted here. Passing the count itself made
                # every fit global, which is why a smoother meant to show local
                # structure used to render as one straight line.
                wcount = max(int(len(xs) / 6), 3)
                frac = wcount / len(xs)
                # the band is drawn only where the data actually supports a
                # local fit: beyond the support, a bootstrap smoother fans into
                # a wedge that reads as an artifact, not as uncertainty
                span = xs.max() - xs.min()
                h = max(span * frac / 2.0, 1e-12)
                grid = np.linspace(xs.min(), xs.max(), 50)
                support = np.array([float((np.abs(xs - g) <= h).sum())
                                    for g in grid])
                keep = support >= max(8.0, wcount / 4.0)
                # both the line and the band must break where the data has a
                # gap: a smoother that bridges empty space arrives looking like
                # a trend, and a band that bridges it arrives looking certain
                gaps = np.diff(xs)
                med_gap = float(np.median(gaps)) if len(gaps) else 0.0
                gap_thr = max(3.0 * med_gap, h)
                gap_idx = np.where(gaps > gap_thr)[0]
                boundaries = [float((xs[i] + xs[i + 1]) / 2.0) for i in gap_idx]
                band = _lowess_band(xs, ys, grid, frac)
                if band is not None and keep.any():
                    seg = [-np.inf] + boundaries + [np.inf]
                    first = True
                    for lo_b, hi_b in zip(seg[:-1], seg[1:]):
                        m = keep & (grid > lo_b) & (grid < hi_b)
                        if int(m.sum()) >= 2:
                            ax.fill_between(grid[m], band[0][m], band[1][m],
                                            color=PALETTE[1], alpha=0.14,
                                            linewidth=0,
                                            label="bootstrap 95% band"
                                            if first else None)
                            first = False
                sm = _lowess(xs, ys, frac)
                cut = gap_idx + 1
                starts = np.split(np.arange(len(xs)), cut)
                line_labeled = False
                for seg_i in starts:
                    if len(seg_i) >= 2:
                        ax.plot(xs[seg_i], sm[seg_i], color=PALETTE[1],
                                linewidth=2.0, linestyle="-",
                                label="LOWESS" if not line_labeled else None)
                        line_labeled = True
            except Exception:
                pass
        ax.set_xlabel(p["x"])
        ax.set_ylabel(p["y"])
        ax.set_title(p["title"].split(" (")[0], fontsize=9, loc="left")
        ax.text(0.99, 0.02, "n = %s" % f"{p['n']:,}", transform=ax.transAxes,
                ha="right", va="bottom", fontsize=8, color="#444444")
        # the interval must belong to the coefficient it sits beside; pairing a
        # spearman estimate with a pearson interval prints a number that cannot
        # exist, which is worse than printing no interval at all
        from effect_size import pearson_r as _pearson_r, spearman_rho as _spearman_rho
        stat_name = str(p.get("statistic", "r"))
        coef: Dict[str, Any] = {}
        if "spearman" in stat_name.lower():
            coef = _spearman_rho(x, y)
            val = coef.get("spearman_rho", p.get("value"))
        else:
            coef = _pearson_r(x, y)
            val = coef.get("pearson_r", p.get("value"))
        ci = coef.get("ci95") if coef.get("estimable", False) else None
        txt = "%s = %.3g" % (stat_name, val)
        if ci and ci[0] is not None:
            txt += " (95%% CI [%.3g, %.3g])" % (ci[0], ci[1])
        ax.text(0.01, 0.96, txt,
                transform=ax.transAxes, ha="left", va="top", fontsize=8.5,
                color="#222222")
        # legend below the axes: inside a narrow panel every corner is
        # contested by the annotation, the n= label, the line or the points,
        # and a legend that overprints any of them destroys information
        if ax.get_legend_handles_labels()[0]:
            n_handles = len(ax.get_legend_handles_labels()[0])
            ax.legend(fontsize=7.5, frameon=False, loc="upper center",
                      bbox_to_anchor=(0.5, -0.32), ncol=min(2, n_handles),
                      columnspacing=1.2, handletextpad=0.5)
    return _finish(fig, axes, out, d,
                   "Association only. The smoother carries a bootstrap 95% band and "
                   "the coefficient carries its interval, so the uncertainty of the "
                   "curve is visible rather than implied. Columns that restate the "
                   "grouping variable are excluded.")


def _lowess_band(x: np.ndarray, y: np.ndarray, grid: np.ndarray, frac: float,
                 n_boot: int = 200, seed: int = 42):
    """Bootstrap percentile band around the LOWESS smoother.

    The band is what separates "a smoother was drawn" from "an estimate with
    uncertainty was drawn". Pairs are resampled whole, never per-coordinate:
    resampling x and y separately would manufacture correlation from noise.
    """
    rng = np.random.default_rng(seed)
    curves = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(x), len(x))
        xb, yb = x[idx], y[idx]
        order = np.argsort(xb)
        xb, yb = xb[order], yb[order]
        if len(np.unique(xb)) < 4:
            continue
        try:
            sm = _lowess(xb, yb, frac)
            curves.append(np.interp(grid, xb, sm))
        except Exception:
            continue
    if len(curves) < max(30, n_boot // 4):
        return None
    arr = np.asarray(curves)
    return (np.percentile(arr, 2.5, axis=0), np.percentile(arr, 97.5, axis=0))


def _lowess(x: np.ndarray, y: np.ndarray, frac: float, iters: int = 3) -> np.ndarray:
    """Local linear regression, so the figure does not need statsmodels.

    A window whose y-values are (near-)constant makes the local line fit rank
    deficient; polyfit flags it as a RankWarning and the fallback below
    already answers it with the window median. The warning is silenced here
    because a per-point conditioning notice printed hundreds of times per
    figure tells the user a chart is broken when it is not.
    """
    import warnings
    try:
        from numpy.exceptions import RankWarning  # numpy >= 2.0
    except ImportError:                            # pragma: no cover
        RankWarning = getattr(np, "RankWarning", None)
    n = len(x)
    window = max(int(n * frac), 3)
    out = np.empty(n)
    with warnings.catch_warnings():
        if RankWarning is not None:
            warnings.simplefilter("ignore", RankWarning)
        for i in range(n):
            lo = max(0, min(i - window // 2, n - window))
            hi = min(n, lo + window)
            lo = max(0, hi - window)
            xw, yw = x[lo:hi], y[lo:hi]
            w = _tricube(np.abs(x[i] - xw) / max(np.max(np.abs(x[i] - xw)), 1e-12))
            try:
                deg = np.polyfit(xw, yw, 1, w=np.sqrt(w))
                out[i] = np.polyval(deg, x[i])
            except Exception:
                out[i] = np.median(yw)
        for _ in range(iters):
            resid = y - out
            s = np.median(np.abs(resid)) * 1.4826 or 1.0
            resid = resid / s
            for i in range(n):
                lo = max(0, min(i - window // 2, n - window))
                hi = min(n, lo + window)
                lo = max(0, hi - window)
                xw = x[lo:hi]
                w = _tricube(np.abs(x[i] - xw) / max(np.max(np.abs(x[i] - xw)), 1e-12))
                w = w * _tricube(np.abs(resid[lo:hi]))
                try:
                    deg = np.polyfit(xw, y[lo:hi], 1, w=np.sqrt(w))
                    out[i] = np.polyval(deg, x[i])
                except Exception:
                    pass
    return out


def _tricube(u: np.ndarray) -> np.ndarray:
    u = np.clip(np.asarray(u, dtype=float), 0.0, 1.0)
    return (1 - u ** 3) ** 3


# ------------------------------------------------------------------ helpers

def paired_numeric(df, xcol: str, ycol: str) -> tuple:
    """Return aligned (x, y) float arrays.

    Dropping missing values from each column separately gives two arrays of
    different lengths whenever only one column has gaps, and every pairwise
    statistic computed from them is then silently wrong -- the first version of
    this function raised a broadcast error, but with equal-length luckier data it
    would have paired unrelated rows. Rows are therefore selected on the shared
    index before anything is converted.
    """
    if df is None or xcol not in df.columns or ycol not in df.columns:
        return np.array([]), np.array([])
    sub = df[[xcol, ycol]].apply(pd_numeric_dtype)
    sub = sub.dropna()
    return (sub[xcol].to_numpy(dtype=float), sub[ycol].to_numpy(dtype=float))


def pd_numeric_dtype(s):
    try:
        return s.astype(float)
    except (TypeError, ValueError):
        return s.astype("float64", errors="ignore")


def pd_numeric(df, col: str) -> np.ndarray:
    if df is None or col not in df.columns:
        return np.array([])
    s = df[col]
    try:
        return s.astype(float).dropna().to_numpy(dtype=float)
    except (TypeError, ValueError):
        return np.array([])


def df_numeric(df, col: str, where=None) -> np.ndarray:
    s = df[col] if (df is not None and col in df.columns) else None
    if s is None:
        return np.array([])
    if where is not None:
        s = s[where.reindex(s.index).fillna(False)]
    try:
        return s.astype(float).dropna().to_numpy(dtype=float)
    except (TypeError, ValueError):
        return np.array([])


RENDERERS = {
    "distribution_panel": render_distribution,
    "small_multiples_ci": render_small_multiples,
    "scatter_panel": render_scatter,
}


def main() -> int:
    p = argparse.ArgumentParser(description="render the decided figures")
    p.add_argument("--decisions", required=True)
    p.add_argument("--clean", required=True)
    p.add_argument("--outdir", required=True)
    p.add_argument("--manifest", default=None,
                   help="write a render manifest here (default: <outdir>/../charts_rendered.json)")
    a = p.parse_args()

    doc = json.loads(Path(a.decisions).read_text(encoding="utf-8"))
    df, prov = dm_types.load_cleaned(a.clean)
    outdir = Path(a.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    rendered: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    for d in doc["decisions"]:
        fn = RENDERERS.get(d["chart_type"])
        if fn is None:
            skipped.append({"id": d["id"], "chart_type": d["chart_type"],
                            "reason": "no renderer for this chart type in v1"})
            continue
        out = outdir / (Path(d["output_path"]).name)
        try:
            info = fn(df, d, out)
            info.update({"id": d["id"], "chart_type": d["chart_type"],
                         "title": d["title"], "ok": bool(info["non_blank"])})
            rendered.append(info)
        except Exception as exc:
            skipped.append({"id": d["id"], "chart_type": d["chart_type"],
                            "reason": "%s: %s" % (type(exc).__name__, exc)})

    manifest = {
        "schema_version": "1.0",
        "dtype_provenance": prov,
        "palette": doc.get("palette"),
        "n_rendered": len(rendered),
        "n_skipped": len(skipped),
        "rendered": rendered,
        "skipped": skipped,
        "note": ("ink_ratio is the fraction of non-white pixels; a figure below ~0.01 is "
                 "suspect and should be opened before it is trusted"),
        "rule_source": "references/chart-decision-catalog.md#complexity-principles",
    }
    mpath = Path(a.manifest) if a.manifest else outdir.parent / "charts_rendered.json"
    mpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"render_chart: {len(rendered)} rendered, {len(skipped)} skipped -> {outdir}")
    for r in rendered:
        print("  %-28s %7d B  ink=%.4f  %s" % (r["id"], r["bytes"], r["ink_ratio"],
                                               "ok" if r["ok"] else "BLANK?"))
    for r in skipped:
        print("  %-28s SKIPPED  %s" % (r["id"], r["reason"]))
    return 1 if skipped and not rendered else 0


if __name__ == "__main__":
    sys.exit(main())
