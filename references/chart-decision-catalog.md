# Chart Decision Catalog

Every chart decision is an entry with: `argument_task`, `chart_types`, `prefer`, `avoid`, `complexity_principles`. The agent reads this file to build `analysis/chart_decisions.json`.

> Inspired by himcm-chart-system `references/chart-types.md` + chart complexity principles. Re-implemented compactly and tied to Nature-grade uncertainty.

## Argument task → chart mapping

| Argument task | Variable types | Preferred chart | Acceptable fallback | Avoid |
|---|---|---|---|---|
| Compare 1 variable across k categories | 1 numeric + 1 categorical | Bar + 95% CI error bars | Dot plot, Cleveland dot | Pie, 3D bar, donut |
| Compare k variables across k categories | k numeric + 1 categorical | Grouped bars + CI | Heatmap (normalized) | Stacked bar (when total meaningless) |
| Show distribution of 1 numeric | numeric | Histogram + KDE + median line | Box plot (when n > 30), violin (when n > 100) | Bar (treats as categorical) |
| Show distribution across groups | numeric + categorical | Box plot + jittered points | Violin, ridgeline | Pie |
| Show 1 numeric over time | time + numeric | Line + 95% band | Connected scatter, step | Bar (loses continuity) |
| Show k series over time | time + k*numeric | Multi-line (legend in body text) | Small-multiples | Stacked area (when not summing) |
| Show 2 numeric variables relationship | numeric + numeric | Scatter + lowess + marginal histograms | Hexbin (large n), 2D density | 3D scatter |
| Show 3 numeric variables relationship | 3 numeric | Bubble (area = z) + marginal panels | Faceted scatter | 3D scatter alone |
| Show residuals / fit | numeric + predicted | Residuals vs fitted | Q-Q plot | Raw scatter without fit |
| Show counts in categories | categorical | Bar (sorted desc) | Cleveland dot | 3D bar |
| Show correlation matrix | k numeric | Annotated heatmap | Pairplot | Pie |
| Show proportion of k categories at 1 time | categorical (3-7 parts) | Stacked bar (1 column) | Single bar with annotation | Pie (always) |
| Show proportion change over time | categorical + time | 100% stacked area (k <= 5) | Small-multiples lines | Pie series |
| Show flow from k sources to k targets | source→sink weights | Sankey | Chord (small n) | Network without conserved flow |
| Show geospatial distribution | lat/lon or region | Choropleth | Hex map (large n), bubble map | 3D bar on map |
| Show ranking | k ordinal | Cleveland dot | Horizontal bar | Pie |
| Show 5-8 dimensions comparison | multi-numeric | Radar (parallel coords) | Table | Stacked bar |
| Show function response surface | 2 numeric + 1 numeric | Contour + heatmap | 3D surface as supplement | 3D alone |
| Show forecast vs actual | time + 2 numeric | Line (actual + dashed forecast) + 95% band | Connected scatter + band | Bar (loses continuity) |
| Show survival | time + event | Kaplan-Meier + CI + risk table | Cumulative incidence | Bar (loses time) |
| Show text-token frequency | text | Wordcloud (top 50) | Bar (top 20) | Pie |
| Show audio waveform | audio | Waveform | Spectrogram | Bar |

## Complexity principles (must apply)

1. **One figure, one argument task.** If the figure cannot answer "what did this change about the reader's understanding", delete it.
2. **A third dimension must change the ranking.** Never 3D / bubble for decoration.
3. **3D always pairs with 2D fallback.** Contour or heatmap as projection.
4. **A complex figure must recover its numbers.** n, CI, source visible from the figure alone.
5. **Readable in 2 minutes.** One primary comparison on first view.
6. **Uncertainty not optional.** Bar with CI; line with band; scatter with lowess.
7. **No decoration.** No Sankey without conserved flow, no chord without bidirectional exchange.
8. **The ceiling is minimum explainable complexity.** Downgrade any complex figure a simple one can replace.

## 2D vs 3D decision

| Evidence structure | Prefer | Fallback | Avoid |
|---|---|---|---|
| Categorical comparison | 2D grouped bars + error | 2D facets | 3D bars |
| Time trend | 2D line + interval | 2D small multiples | Z-axis = time |
| Bivariate function | 2D contour + heatmap | 3D surface as supplement | 3D only |
| 3-variable tradeoff | 2D bubble (area prop.) | 2D three related subplots | 3 axes in one plot |
| 3-8 dimension comparison | 2D radar / parallel | 2D standardized table | 6D 3D scatter |
| Conserved flow | 2D Sankey | 2D transition matrix | decorative network |
| Spatial location enters | 2D choropleth / flow map | 3D network (hierarchy only) | 3D bars pinned to map |

## Title — caption — body

Every chart caption has three parts:

```
[Title]  Conclusion-style, states the result.
[Figure] N. Measurement definitions, units, sources, sample size, baseline.
[Body]   Fact: ...  Interpretation: ...  Implication: ...
```

The title is the finding, not the topic.

> BAD title: "Figure 4. Sales over time"
> GOOD title: "Figure 4. Self-serve signups doubled Q4 MRR with 23% conversion lift"

## Color discipline

- Color is **secondary encoding**. Always describe by line/marker first.
- One color and one marker per alternative across all figures (within a report).
- Default palette: `["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd"]` (color-blind safer subset).
- Avoid pure red-green pairs.

## Accessibility

- Color is never the only channel: pair with line style + marker shape.
- Readable in grayscale (test by converting the PNG with `PIL.Image.convert("L")`).
- Labels not overlapping (font size >= 10 pt at figure size).
- Color-blind safe: use `cmap="cividis"` for sequential, `cmap="RdBu"` reversed for diverging.

## Chart decisions JSON structure

```json
{
  "decisions": [
    {
      "argument_task": "compare k variables across groups",
      "chart_type": "grouped_bar",
      "n_series": 4,
      "uncertainty": "95_ci_error_bar",
      "complexity_principle_applied": ["1_one_argument", "6_uncertainty"],
      "rationale": "4 numeric vars per category; bars + error bars; one primary comparison on first view",
      "rejected": [
        {"chart_type": "stacked_bar", "reason": "totals meaningless here"}
      ],
      "output_path": "outputs/charts/fig01_sales_by_region.png"
    }
  ]
}
```

## Forbidden charts

- **Pie / donut** for > 3 categories or any time comparison.
- **3D anything** without a 2D projection.
- **Dual-axis** when the two series share no scale unit.
- **Sankey / chord** without conserved flow.
- **Truncated y-axis** without explicit annotation.
- **Decorative icons / emoji** in the plot area.
- **Watermarks / "Confidential" stamps** unless user requests.

## v1 chart palette

The first version supports: bar, grouped_bar, stacked_bar, line, multi_line, scatter, hexbin, box, violin, histogram, heatmap, kde, area, stacked_area, wordcloud, choropleth (placeholder v2), sankey (placeholder v2), radar (placeholder v2), residual_plot, qq_plot, km_curve (placeholder v2), lowess, errorbar.
