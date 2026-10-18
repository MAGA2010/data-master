# Independent-groups smoke example

`measurements.csv` is synthetic: 40 independent subjects, two groups of 20,
and one numeric outcome. Values were generated with NumPy `default_rng(61)`:
group A from `normal(2, .5, 20)` and B from `normal(3, .5, 20)`. The file has
no missing values or technical replicates; it is not evidence about a real
treatment.

```bash
python scripts/run_pipeline.py --in examples/independent_groups/measurements.csv --out outputs/independent-groups --group arm --unit-key subject --outcomes response --title "Synthetic independent groups"
python scripts/verify_artifacts.py --outdir outputs/independent-groups --json
```

Expected behavior: retain 40 subjects, compare the two groups, report the effect
estimate with its interval, run sensitivity checks, and deliver a PDF and an
audit. A successful integrity verification means the recorded artifacts match
their hashes; it does not validate a research design or certify a real study.
