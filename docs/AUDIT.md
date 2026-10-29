# Audit report and evidence trace

Status: Day 6, built and tested offline; run once on the 5 dev notes from the first live smoke test (`runs/audit-first5.html`, git-ignored). No model is called by this step. This is an assistant for human review, not a compliance certification.

```powershell
python -m deid.audit.run --pred runs/meta-dev-first5.jsonl --detector muse-spark-1.3 `
    --log runs/meta-dev-first5.log.json --other regex=runs/regex.jsonl --out runs/audit-first5
```

It writes `<out>.json` (the trace) and `<out>.html` (one self-contained page, no external files). **Both contain the original identifiers and are as sensitive as the notes**: they stay in `runs/` and are not shared.

## The trace

Every replacement gets one entry linking it to its evidence:

| Field | Meaning |
|---|---|
| `start`, `end` | character offsets of the original span in the original note |
| `new_start`, `new_end` | where the replacement sits in the cleaned note |
| `original`, `replacement`, `rule` | what was changed, to what, and by which replacement rule |
| `detector`, `confidence` | which detector found it and the confidence it gave (none for rule-based baselines) |
| `also_found_by` | other detectors whose spans overlap it |
| `checks` | the rule-based check's decision (`accept` or `review`) and its reasons |

Checks (`deid/audit/verify.py`) are plain rules, not a model: confidence below 0.8, a replacement that fell back to a tag, a date read month-first, a date with no year, and implausible shapes (a phone with too few digits, an ID with no digit, an email with no `@`). A check never changes a replacement. `accept` means no rule objected, not that the span is right. A model-based verifier is not built.

## The review queue

Per note: spans a check objected to; strings the model listed that were not found in the note (`unmatched`); and, if red-team results are supplied (`--assessments`), its clues and risk level. The page shows the original and cleaned text side by side. Clicking a highlighted span or a table row links the original, the cleaned text and the trace row; a checkbox hides everything that needs no review.

## Limits

- The red-team risk is shown only when assessments are supplied; otherwise "not assessed". Nothing yet produces assessments for real detector output (the red-team run covers probe notes), so that link is unwired.
- The queue holds what rules and the reviewer flagged. A span the detector missed and the reviewer did not notice appears nowhere.
- `also_found_by` is overlap-based and records agreement only; it does not change a decision.
