---
name: visualizer
description: "Decide and render one figure per argument: chart type chosen against alternatives, title states the finding, caption defines the encoding, body gives fact -> interpretation -> implication."
parent: data-master
stage: 3a
---

# visualizer

**Stage 3a of the data-master pipeline.** The router in `../../SKILL.md` owns the
end-to-end run; this skill owns one stage and one gate. Read the parent contract before
changing anything here: the invariants in `../../SKILL.md` (additive-only, types decided
once, default-FAIL gates, three-part provenance) are not restated, they are inherited.

## When to invoke

After statistics exist. The decision layer runs even when no figure is produced --
"no chart says anything a table does not" is itself a recorded decision.

## Inputs

- cleaned data
- `analysis/profile.json`, `descriptive.json`, `inferential.json`

## Outputs

- `analysis/chart_decisions.json`: `palette, markers, decisions[{id, chart_type, spec,
  uncertainty, title, caption, body{fact, interpretation, implication}, rationale,
  rejected, output_path, order}], rules, dtype_provenance`
- `outputs/charts/*.png` at 200 dpi
- `outputs/charts_rendered.json`: per-figure `bytes, ink_ratio, non_blank, pixels`

## Commands

```powershell
python scripts/chart_decision.py --clean outputs/cleaned/cleaned.csv --profile outputs/analysis/profile.json --descriptive outputs/analysis/descriptive.json --inferential outputs/analysis/inferential.json --out outputs/analysis/chart_decisions.json
python scripts/render_chart.py --clean outputs/cleaned/cleaned.csv --decisions outputs/analysis/chart_decisions.json --outdir outputs/charts
```

## Gate (default FAIL)

- every decision names the chart types it rejected and why;
- every title states a finding, not a topic;
- every figure passes its blank-page check (`non_blank: true`, ink ratio above zero);
- a comparison figure states its interval (error bars, band or CI).

## Failure modes seen in real runs

- **A title and a subtitle drawn at the same anchor.** `suptitle(wrap=True)` keeps
  y=0.98 and grows downward into whatever sits below it; wrap by measured width and
  place each line explicitly.
- **A blank figure that saves without error.** Ink ratio is read back from the PNG after
  save, because a successful `savefig` proves only that a file exists.
- **The same argument drawn as three separate figures.** Panels, not repeats.

## Do not

- do not use 3D unless it changes the ranking;
- do not use a rainbow palette for an ordered variable;
- do not render a figure whose decision record has no rejected alternative.

## Upstream / downstream

- previous: `../statistical-analyzer/SKILL.md`
- next: `../report-generator/SKILL.md`
- catalog: `../../references/chart-decision-catalog.md`
