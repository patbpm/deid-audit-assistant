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

## Outcome (Oct 29 - 30)

**All four criteria passed.** One run in two sessions, 400 of 400 notes cleaned, nothing changed between them.

The first session stopped at the 2,500,000-token cap after all 400 detections, before any note finished (600,404 tokens in, 1,910,663 out, 8.87 USD at list price; the detection replies used more output tokens than the dev run did, so my 7 USD estimate was low). With Patrick's approval the same command was resumed with a 1,500,000-token cap; detections came from the cache, so only the red-team calls were new (84,282 in, 107,370 out, 0.56 USD). In all 2,702,719 tokens and 9.43 USD at list price (an estimate; reasoning-token billing is not stated). The first session's partial summary is in the commit that recorded it (74cd8c4).

| Criterion | Result |
|---|---|
| 1. Recall at least 99% | 5,992 of 5,992 labeled identifiers (100%), exact boundaries and the right type, in the detector spans and after red-team feedback (names 2,587, dates 1,700, phones 712, IDs 634, addresses 300, emails 59) |
| 2. At most 0.05 false positives per note | 0 false positives (0.00 per note) in both |
| 3. Every note cleaned, no unresolved unreadable or cut-off replies | 400 of 400 cleaned, 0 not cleaned, 0 unreadable, 0 cut off, 0 unmatched strings |
| 4. No labeled identifier verbatim in a cleaned note beyond what a review item explains | Two hits out of 5,992, both coincidences on inspection: the date "8/1" (replaced by "2/8") sits inside "Pain 8/10", and the name part "King" (from "David King", replaced) is the start of the stand-in "Kingsley". No original identifier was left in place. Run `python -m deid.eval.leak` (`deid/eval/leak.py`) to list them with context |

Other numbers from the run: the name check was asked about 11 occurrences and left none as written; the verifier's 19 verdicts were all "identifier"; median detection call 13.1 s; the red-team rated 397 notes low, 1 medium and 2 high and sent nothing back (0 spans added by feedback). The three non-low notes were all flagged for a rare-condition clue, the template generator's occasional implausible combination (a woman in her twenties with COPD on home oxygen), which is the red-team doing its job on an artifact of the synthetic data. 376 review items: 373 are date guesses (day/month order assumed, or no year) and 3 are those clues.

Reproduce: `python -m deid.agent.run --live --split test --allow-test --limit 0 --name agent-meta-test --workers 4 --max-total-tokens 2500000 --price-in 1.25 --price-out 4.25 --results-dir results/test` (billed; resume with a larger cap if it stops at the cap). Scores in `results/test/`, written by the run itself (detector and final stages). Before the resume, the detector stage was also scored offline from the saved replies (`python -m deid.eval.replay --split test --version v2 ...`, then `deid.eval.run --only-predicted`) with identical numbers; that is the `-agnostic` file.

What this does and does not show: the test notes come from the same templates as the dev notes, so a perfect score says the prompts did not overfit to the dev patients and that the pipeline holds on 400 more notes of this kind. It says nothing about real clinical text or notes unlike these, and the hard cases are in the adversarial sets, not here.
