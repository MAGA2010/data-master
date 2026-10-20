# Synthetic survey example

A seeded generator produces 120 synthetic survey responses -- no real
participant data exists. The fixture carries the traps a survey export
typically has:

- `respondent_id` -- zero-padded numeric identifiers that must stay text;
- `age_years` -- uses `-999` as its explicit "not answered" code;
- `satisfaction`, `visit_frequency`, `recommend` -- labelled categorical
  answers, with genuine blanks;
- `minutes_spent` -- a numeric measurement that genuinely differs by
  satisfaction level.

```bash
python make_survey.py   # regenerates survey_responses.csv deterministically

data-master analyze survey_responses.csv --out outputs \
  --group satisfaction --unit-key respondent_id \
  --outcomes minutes_spent \
  --title "Synthetic survey responses"
```

The run finishes `SUBMISSION-READY` while withholding three decisions for a
human answer in `outputs/answers.template.json`. The values are synthetic and
support no claim about any real population.
