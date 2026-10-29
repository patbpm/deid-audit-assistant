# Review-burden curve (stretch goal)

Status: Day 6, built and tested offline. **It has not been run on a full model output**: the only model run with confidences is the 5-note smoke test, where it is degenerate (2 spans below the threshold, both true). An illustrative synthetic example was used only to check the chart draws. This is an assistant for human review, not a compliance certification.

```powershell
python -m deid.eval.burden --pred runs/<detector>.jsonl --split dev --name <name> [--only-predicted] [--hi 0.8]
```

Writes `results/dev/burden-<name>.json` (the curves and the spans-to-reach table) and `burden-<name>.svg`.

## The question

A detector's confidence scores let you decide which spans a person must look at. The curve asks: if everything at or above a confidence threshold (`--hi`, default 0.8) is redacted without review, and the candidates below it are redacted only when a person looks at them, how much recall does each reviewed span buy?

Reviewing candidates one at a time, most confident first, gives recall after 0, 1, 2... reviewed spans. Two reference orders put it in context:
- **random**: the same candidates in random order (mean over 200 shuffles). The gap between "ranked" and "random" is what the confidence scores are worth.
- **oracle**: the candidates that add new true identifiers first, the best any ranking could do.

The table gives the number of spans reviewed to reach 50%, 90% and 100% of the available gain, for each order.

## What it assumes

- **A perfect reviewer.** A candidate is redacted exactly when it overlaps a true identifier, so every curve is an upper bound on what real people achieve.
- **Identifiers no candidate overlaps stay missed** at any burden. They are reported separately ("never reachable by reviewing candidates") and can only be found by reading the note; the review page lets a person do that.
- **Type labels are ignored** (any overlap counts), and spans with no confidence count as above the threshold.
- This measures the choice of threshold and ordering, not the quality of the confidence numbers: a model that answers 1.0 for everything has an empty band and a flat curve.

## Limits

- The curve is only as informative as the confidences. Muse Spark's self-reported confidences have not been checked for calibration.
- One threshold is plotted at a time; try several with `--hi`.
- Tune on dev; run on the test split once, with `--allow-test`, for reporting.

## Other stretch items

- **Muse Voice Transcribe (dictated notes)** and a **vision model for scanned notes** are not started. Both need API access and documentation that is not in the repository, and neither is needed for the core demo. No claim is made for either, and the README does not mention them.
