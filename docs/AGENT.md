# Agent loop

Status: Day 6, built and tested offline with a scripted model. **It has not been run live, so there are no scores for the loop.** It is an assistant for human review, not a compliance certification.

```powershell
python -m deid.agent.run                         # dry run: stages and sizes, calls nothing
python -m deid.agent.run --live --limit 5        # real calls on dev notes (needs Patrick's go-ahead)
```

## Stages

1. **Detect** (`deid/detect`, prompt `v1`): one model call per note; strings are located in the text and every occurrence is marked.
2. **Verify** (`deid/agent/verifier.py`, prompt `vf1`): one call per note, only if some span is uncertain: confidence below 0.8, no confidence, or a shape the rule checks dislike (a phone with too few digits, an ID with no digit). Each uncertain span goes with about 90 characters of context. The verifier answers `identifier`, `not_identifier` or `unsure`.
3. **Replace** (`deid/replace`): detection and verification run over the whole batch first, because the engine reads the names in the batch to tell first names from surnames. Replacement then runs note by note.
4. **Red-team** (`deid/redteam`, prompt `rt1`): a model reads the masked cleaned note and reports leftovers and risk clues.
5. **Feed back**: located leftover identifiers are added to the spans and the note is cleaned again, up to `--max-rounds` (default 2) extra rounds, stopping when a round finds nothing new.
6. **Audit** (`deid/audit`): every change is linked to its offsets, detector, confidence, verifier verdict, rule and checks, and everything a person should look at goes to a review queue.

Per note: at most 1 detection call, 1 verification call and 1 + `--max-rounds` red-team calls.

## Decisions the code makes

- **The verifier never removes a span.** A missed identifier costs more than an extra replacement. `identifier` clears only the low-confidence objection; `not_identifier` and `unsure` keep the span replaced and send it to a person with the verifier's reason. A span the verifier skips, or an unreadable reply, counts as `unsure`: silence is never a confirmation.
- **Spans found only by the red-team reviewer** are labelled `red-team feedback` and always sent to review, so a person sees what the detector missed.
- **Clues that are not leftover identifiers** (rare condition, occupation, small place) are never edited automatically; they appear in the review queue.
- **The token cap is checked between notes.** A note in progress can overshoot it by a few calls. Dry run is the default and the test split is refused without `--allow-test`.

## Outputs (git-ignored `runs/`)

`<name>.notes.jsonl` (cleaned notes), `<name>.detector.jsonl` and `<name>.final.jsonl` (spans before and after feedback), `<name>.audit.json` and `.html`, `<name>.key.json`. The audit and key contain original identifiers or the re-identification key: never share them. Aggregate numbers go to `results/dev/<name>.json`, and both span files are scored against the dev ground truth (`<name>-detector-dev.json`, `<name>-final-dev.json`), so the effect of the feedback loop on recall can be read directly.

## Tests

`tests/test_agent.py` uses a scripted model that withholds one phone or ID from detection, gives the first date a low confidence, and confirms or doubts verification candidates. It checks call counts, that the withheld string is found, removed and labelled, that the verifier clears or escalates correctly, that nothing but note text and the masked view is sent, the token cap, and the CLI's dry run and test-split guard. This checks the plumbing, not any model.

## Known limits

- The verifier prompt (`vf1`) and the feedback loop have never met a real model. Expect to tune them on dev only.
- The red-team sees tags, not surrogate text, and has so far only been smoke-tested on blunt probe notes.
- A span the detector misses and the reviewer also overlooks is not caught anywhere. The loop reduces leaks; it does not prove there are none.
- Dollar cost is unknown until per-token prices are supplied.
