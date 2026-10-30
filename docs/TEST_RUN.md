# Held-out test run (pre-registered Oct 29, 2026)

Written and committed **before** the run. Patrick approved one run of the full agent on the 400-note test split (patients P0051-P0150, frozen Oct 27, never used to tune a prompt or rule; `data/frozen.json`). Synthetic data only. This is an assistant for human review, not a compliance certification.

## What is run

Muse Spark (`muse-spark-1.3`, Meta Model API) as detector, verifier, name check and red-team, detection prompt v2, the code at the commit that adds this file. Once, with 4 workers, token cap 2,500,000, list prices 1.25 USD in and 4.25 USD out per million tokens (estimate about 7 USD). No change to any prompt, rule or code between this commit and the end of the run; no tuning afterwards.

```powershell
python -m deid.agent.run --live --split test --allow-test --limit 0 --name agent-meta-test --workers 4 --max-total-tokens 2500000 --price-in 1.25 --price-out 4.25 --results-dir results/test
```

## Pass criteria (stated before the run)

Scored on the detector's spans and on the final spans after red-team feedback, type-agnostic overlap, against the labeled spans:

1. Recall of labeled identifiers at least 99%.
2. At most 0.05 false positives per note.
3. No unreadable or cut-off replies left unresolved: every note cleaned, none withheld as failed.
4. No labeled identifier appearing word for word in a cleaned note beyond what a flagged review item explains.

Whatever happens is reported as it comes out, including a failed criterion. If the token cap stops the run early, the notes processed are reported as a partial run and not completed by a second run that changes anything.

## How to read it

The test notes come from the same templates as the dev notes. A pass shows the prompts did not overfit to the dev patients; it does not show performance on real notes or on notes unlike these.

## Outcome so far (Oct 29)

The run stopped at the 2,500,000-token cap after all 400 detections (2.04 million tokens) and 8 red-team first looks, with no note finished, so no final (post-red-team) output exists and the run is partial. Cost 8.87 USD at list price (600,404 tokens in, 1,910,663 out), above the 7 USD estimate: the detection replies used more output tokens than the dev run did.

Detector stage, scored offline from the saved replies with no model call (`python -m deid.eval.replay --split test --version v2 ...` then `deid.eval.run --only-predicted`; the name check left none of its 11 occurrences as written, so the replay, which cannot run that check, matches the run): 5,992 of 5,992 labeled identifiers found with exact boundaries and the right type, 0 false positives, 0 unreadable or cut-off replies, 0 unmatched strings. Name check asked about 11 occurrences, left none as written. The verifier's 19 verdicts were all "identifier". Median detection call 13.1 s.

Criteria 1 and 2 (recall at least 99%, at most 0.05 false positives per note) pass at the detector stage. Criteria 3 and 4 (every note cleaned; no labeled identifier verbatim in a cleaned note) and the final-stage scores cannot be judged until the red-team and cleaning stages have run.
