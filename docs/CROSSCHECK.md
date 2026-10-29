# Two-model cross-check

Status: built and tested offline with scripted models (Oct 29). **No real second model has been run.** It needs a second endpoint: Muse Spark Open on partner inference (Baseten, Fireworks, Modal or another OpenAI-style host) next to Muse Spark on the Meta Model API. This is an assistant for human review, not a compliance certification.

## Idea

A model's confidence number says how sure that model is. Two different models reading the same note independently and disagreeing says something else: a span that one found and the other did not is where a person's time is best spent. The cross-check uses both Meta models in one pipeline and puts the disagreements in front of the reviewer. Whether disagreement is a better review signal than confidence is a measurement still to be made (below), not an assumption.

## How it works (`deid/agent/crosscheck.py`)

- The primary model detects as before (including the name check). The second model reads the same note alone with the same prompt; its doubtful name occurrences get the same check.
- The primary decides what is replaced; the second can only add. A span both found (overlapping spans) is `agree`; a span only the primary found stays replaced and is marked `only primary`; a span only the second found is added, replaced, and marked `only second`, because a missed identifier costs more than an extra replacement. Overlapping spans with different types agree on place and are flagged for the type.
- Every disagreement goes to the review queue with both models named ("only A found this; B did not") and to the verifier for a third opinion the reviewer can read. The verifier's answer does not clear the flag: a person decides.
- Agreeing spans list the other model under "also found by" in the audit.
- If the second model's reply is unreadable or cut off, the note is still cleaned from the primary alone and gets a `notice` in the review queue saying one model checked it. Nothing fails because of the second model.
- The second model's tokens count against the cap. Only synthetic data is ever sent to either model.

## Use

```powershell
# primary: Meta Model API (META_API_KEY); second: any OpenAI-style host
$env:DETECT_BASE_URL = "https://inference.baseten.co/v1"
$env:DETECT_MODEL    = "meta-models/muse-spark-open-1026"
$env:DETECT_API_KEY  = "<your key>"
python -m deid.agent.run --live --provider meta --second-provider custom --split dev --limit 0 --name cross-dev --workers 4
```

Extra outputs: `runs/<name>.second.jsonl` (what the second model found alone, scorable on its own), a `cross_check` block in the run summary (agree / only primary / only second / type disagreements / notes checked by one model only), and a `cross` mark on every merged span in `<name>.detector.jsonl`.

## Measuring it

```powershell
python -m deid.eval.burden --pred runs/cross-dev.detector.jsonl --name cross-dev-confidence          # confidence ranking
python -m deid.eval.burden --pred runs/cross-dev.detector.jsonl --name cross-dev-disagreement --cross  # disagreement needs a look
```

Compare how many spans a person must review to reach 90% of the recall that review can add, and what each policy costs in review load. The question to answer: does disagreement catch real identifiers that confidence alone sends unreviewed, and at what cost in extra reviews? Report the answer whichever way it goes. Also report recall and false positives of each model alone and merged (`deid.eval.compare` for the pairwise comparison with intervals).

## Tests

`tests/test_crosscheck.py` (scripted models): the merge rules, a third opinion for disagreements and none for agreement, the audit reasons naming both models, a second model that fails costing only a notice, a failed primary not calling the second, the command's outputs and summary, the burden option. These check the plumbing and the policy; they say nothing about how Muse Spark and Muse Spark Open actually disagree.

## Limits

- Two models trained on related data may make the same mistake, in which case they agree and the span goes unflagged.
- Adding the second model's spans can add false positives; the cost is more review, which the burden comparison shows.
- The front page (`deid.app`) does not use the cross-check yet; it is a command-line option of `deid.agent.run`.
