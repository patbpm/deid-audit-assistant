# Table mode

Status: Day 6, built and checked on invented tables (`results/dev/tables.json`). It is rule-based and calls no model unless `--freetext-live` is given, which has been tested only with a scripted model. It has not been tried on any real table. This is an assistant for human review, not a compliance certification.

The note pipeline works on text. This mode works on tables: CSV files whose columns each hold one kind of value.

```powershell
python -m deid.synth.tables                                  # invented patients and encounters in data/generated/tables
python -m deid.tables.run --in a.csv b.csv --out-dir runs/tables-x --plan-only      # 1. look at the plan
python -m deid.tables.run --in a.csv b.csv --out-dir runs/tables-x --plan runs/tables-x/plan.json   # 2. apply it (edit plan.json first if a column is wrong)
python -m deid.tables.check                                  # score the mode against the invented tables
```

## How it works

1. **A plan per table** (`columns.py`). For each column it decides a type from the header words and the values together: `KEY` (the patient id that links rows), `ID`, `NAME`, `DATE`, `PHONE`, `EMAIL`, `STREET`, `TOWN`, `ZIP`, `STATE`, `AGE`, `FREETEXT`, `SAFE`, or `UNKNOWN`. A header that the values contradict (a "Birth Date" column that holds words) makes the column `UNKNOWN`, not trusted. Every column records how it was decided and how well its values fit. The plan is a JSON file a person reads and edits before anything changes.
2. **A rule per type** (`apply.py`):
   - Dates shift by one offset per key value (the patient), so a stay's length, an age at admission and every interval stay the same, within a table and across tables. A date that cannot be parsed becomes a tag and is flagged.
   - Names, ids, phones, emails, streets, towns and ZIP codes reuse the note engine's surrogates: the same original always gives the same fake value in every table of a run, distinct ids stay distinct, and a surname is the same fake wherever it appears (`Reyes, Kim` and `Dr. Reyes`).
   - Ages of 90 and over become `90+`. `SAFE` and `STATE` columns are kept as they are.
   - Free text is masked and flagged as not cleaned. With `--freetext-live` each cell goes through the note detector (hosted model; capped by `--max-total-tokens`) and a cell whose detection fails is masked too.
   - A column the rules cannot place is **withheld**: dropped from the output and listed. `--unknown mask` keeps the column with `[WITHHELD]` values; `--unknown keep` leaves it as is.
3. **Key choice.** The key is the column typed `KEY`; otherwise the ID column whose values repeat, otherwise the first ID column, and the plan says which and why. With no key each row moves its own dates but keeps them together.

Outputs in `--out-dir`: the cleaned CSVs, `plan.json` and `report.json` (no values), and `changes.jsonl` and `key.json`, which hold the original values and must never be shared with the cleaned tables.

## Check on invented tables (`deid.tables.check`, seed 20261030, 60 patients, 121 encounters)

Two linked tables in four header styles: `clean` and `messy` headers written while the rules were being built, `unseen` headers worded differently and written afterwards, and `headerless` (values only).

| Style | Columns typed right | Left unplaced (withheld) | Wrong type | Identifier columns kept as is | Original identifiers still found (of 1,247) | Row links broken | Patients with 2 date shifts | Stays or ages changed |
|---|---|---|---|---|---|---|---|---|
| clean | 24 of 24 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| messy | 24 of 24 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| unseen | 18 of 24 | 4 | 2 | 0 | 0 | 0 | 0 | 0 |
| headerless | 15 of 24 | 6 | 3 | 0 | 0 | 0 | 0 | 0 |

- **What is checked.** Every original name, id, phone, email, street, town and ZIP anywhere in any cleaned cell, free text included; each cleaned encounter's patient id and MRN still match its cleaned patient row; one date shift per patient across both tables; safe columns identical; ages of 90 and over shown as `90+`.
- **The safe failure.** When the rules cannot place a column, it is withheld, so the cost shows as lost utility, not leakage. In the `unseen` set the four withheld columns were Locality, Years, Days Inpatient and Billed; in the headerless set, the age, sex, town, length-of-stay, diagnosis-code and charges columns. The two wrong types in `unseen` were the patient id read as a generic id, which is harmless because the replacement is the same.
- **The unseen headers are no longer fully unseen.** They found a real bug (an amount such as `27701.51` was read as a phone number and replaced), which I fixed in the rules. The numbers above are after that fix, so treat `unseen` as a mildly tuned set. The `clean` and `messy` results mostly show that the rules know the vocabulary they were written for.
- **A free-text column is masked, not cleaned**, in all of these runs, since no model was used; the leak check covers it because the masked text contains no identifiers.

## Limits

- **Invented, uniform tables.** One generator, 60 patients, tidy values, one language. Real tables have missing and malformed cells, mixed formats within a column, codes with meaning, merged cells and wide schemas. Typing accuracy on real headers will be lower; the plan review step exists for that.
- **Header vocabulary.** The rules know a few dozen header words. Anything else relies on value shapes, and several types cannot be guessed from values alone (town, age, amounts, sex).
- **Quasi-identifiers are not assessed.** A rare diagnosis with a ZIP and an age can identify someone with no name present. This mode does not check for small groups of rows, and it keeps ZIP codes as a surrogate rather than generalizing them. It does not do k-anonymity, suppression or noise.
- **Consistency holds within a run.** All tables processed together share their mappings. Separate runs agree only if given the same seed and the same batch; the key file records one run's mapping and is not yet reloaded.
- **CSV only.** No Excel, Parquet or database connections, and no review page for tables; the plan file and the report are the review step.
- **Dates**: a date column keeps its written style; `MM/DD` ambiguity follows the note engine's rules and is flagged in the changes file by rule name.
