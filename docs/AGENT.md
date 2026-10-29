# Agent loop

Status: Day 6, built and tested offline with a scripted model, plus one live run on 5 dev notes (below). The feedback loop has not been exercised live. It is an assistant for human review, not a compliance certification.

```powershell
python -m deid.agent.run                         # dry run: stages and sizes, calls nothing
python -m deid.agent.run --live --limit 5        # real calls on dev notes (needs Patrick's go-ahead)
```

## Stages

1. **Detect** (`deid/detect`, prompt `v2`): one model call per note; strings are located in the text and every occurrence is marked, with three set-asides that are recorded, never silent (`deid/detect/context.py`): a year on its own or a relative date ("last Tuesday") is not an identifier; a listed name directly followed by an eponym noun ("Wilson disease", "Foley catheter") with no title or label before it is a condition, not a person; and an occurrence of a name the model flagged `also_a_word`, with no title or label before it, is doubtful and goes to step 2.
2. **Check doubtful name occurrences** (`deid/agent/nameuse.py`, prompt `nu1`): one call per note, only if step 1 left a doubtful occurrence. Each is shown with its surroundings and the model answers `name`, `ordinary_word` or `unsure`. Only a clear `ordinary_word` leaves the occurrence as written; that is recorded in the audit (`ignored`) and put in the review queue as `not-replaced`, where a person can choose "Replace it after all". Any other answer, a missing answer, a cut-off reply or an unreadable one keeps it replaced. Without a second model (offline engine) the occurrence stays replaced and is flagged.
3. **Verify** (`deid/agent/verifier.py`, prompt `vf1`): one call per note, only if some span is uncertain: confidence below 0.8, no confidence, or a shape the rule checks dislike (a phone with too few digits, an ID with no digit). Each uncertain span goes with about 90 characters of context. The verifier answers `identifier`, `not_identifier` or `unsure`.
4. **Replace** (`deid/replace`): detection and verification run over the whole batch first, because the engine reads the names in the batch to tell first names from surnames. Replacement then runs note by note.
5. **Red-team** (`deid/redteam`, prompt `rt1`): a model reads the masked cleaned note and reports leftovers and risk clues.
6. **Feed back**: located leftover identifiers are added to the spans and the note is cleaned again, up to `--max-rounds` (default 2) extra rounds, stopping when a round finds nothing new.
7. **Audit** (`deid/audit`): every change is linked to its offsets, detector, confidence, verifier verdict, rule and checks, and everything a person should look at goes to a review queue.

Per note: at most 1 detection call, 1 name-check call, 1 verification call and 1 + `--max-rounds` red-team calls.

## Decisions the code makes

- **The name check is the one model step that can leave text as written**, and only for a word the detector itself marked as also an ordinary word, only on occurrences with no title or label before them, and only on a clear `ordinary_word`. Everything it leaves is listed in the audit and the review queue. The red-team reviewer still reads the cleaned note afterwards and can send a missed occurrence back. Whether this is safe enough is a measurement still to be made (`docs/ADVERSARIAL.md`).
- **The verifier never removes a span.** A missed identifier costs more than an extra replacement. `identifier` clears only the low-confidence objection; `not_identifier` and `unsure` keep the span replaced and send it to a person with the verifier's reason. A span the verifier skips, or an unreadable reply, counts as `unsure`: silence is never a confirmation.
- **Spans found only by the red-team reviewer** are labelled `red-team feedback` and always sent to review, so a person sees what the detector missed.
- **Clues that are not leftover identifiers** (rare condition, occupation, small place) are never edited automatically; they appear in the review queue.
- **The token cap is checked between notes.** A note in progress can overshoot it by a few calls. Dry run is the default and the test split is refused without `--allow-test`.

## Outputs (git-ignored `runs/`)

`<name>.notes.jsonl` (cleaned notes), `<name>.detector.jsonl` and `<name>.final.jsonl` (spans before and after feedback), `<name>.audit.json` and `.html`, `<name>.key.json`. The audit and key contain original identifiers or the re-identification key: never share them. Aggregate numbers go to `results/dev/<name>.json`, and both span files are scored against the dev ground truth (`<name>-detector-dev.json`, `<name>-final-dev.json`), so the effect of the feedback loop on recall can be read directly.

## Tests

`tests/test_agent.py` uses a scripted model that withholds one phone or ID from detection, gives the first date a low confidence, and confirms or doubts verification candidates. It checks call counts, that the withheld string is found, removed and labelled, that the verifier clears or escalates correctly, that nothing but note text and the masked view is sent, the token cap, and the CLI's dry run and test-split guard. This checks the plumbing, not any model.

## First live run (Oct 29)

`python -m deid.agent.run --live --limit 5`, Meta API `muse-spark-1.3`, prompts detect `v1`, verify `vf1`, red-team `rt1`, the first 5 dev notes, token cap 100,000 (`results/dev/agent-first5-dev.json`, scores in `agent-first5-dev-detector-dev.json` and `-final-dev.json`).

- **Detection came from the response cache**: the same model, prompt and notes were run on Oct 28, so those replies were reused and cost no new tokens. This run's fresh calls were 1 verification call and 5 red-team calls: 12,481 tokens (4,798 in, 7,683 out). No unreadable or truncated replies.
- **Verifier**: asked about the 2 spans the detector gave confidence below 0.8 (0.70 and 0.60); it confirmed both as identifiers, which cleared their low-confidence flags.
- **Red-team**: rated all 5 notes low risk, with no clues and no leftover identifiers, so nothing was fed back (0 spans added, 5 red-team calls rather than up to 15).
- **Audit queue**: 4 review items remain, all rule-based (3 month-first dates, 1 year-less date). Before the verifier it was 6.
- **Accuracy**: detector and final spans both found 83 of 83 true identifiers with no false positives (the same numbers as the Oct 28 smoke test, as expected from the cached replies).

What this shows: the stages run end to end on a real model and the verifier clears confirmed low-confidence spans. What it does not show: how the verifier behaves when it should doubt a span, or how the feedback loop behaves when the detector misses something. Those paths need harder notes (for example the adversarial set, run once at the end) or a weaker detector setting. These 5 notes are easy synthetic text; no accuracy claim follows.

## Failure handling (added after a live run on dictated and scanned notes)

A note whose detection reply is unreadable or cut off at the output limit is **not cleaned**: it is left out of `<name>.notes.jsonl`, listed in `<name>.failed.json`, flagged in the audit and review page, and withheld from the review export. A reply cut off at the limit is first asked again once with a larger limit (`--retry-output-tokens`, default 16,384; 0 turns it off), and incomplete replies are never cached. Details: `docs/INGEST.md`.

## Known limits

- The verifier prompt (`vf1`) has met a real model only on 2 spans, both confirmed, and the feedback loop has never had anything to correct on a real model. Expect to tune them on dev only.
- The red-team sees tags, not surrogate text, and has so far only been smoke-tested on blunt probe notes.
- A span the detector misses and the reviewer also overlooks is not caught anywhere. The loop reduces leaks; it does not prove there are none.
- Dollar cost is only an estimate: pass `--price-in 1.25 --price-out 4.25` (list prices, `docs/PRICES.md`) to have a run print it.
