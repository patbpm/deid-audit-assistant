# Re-identification red-team

Status: Day 6, built and tested offline, plus one live smoke test on 5 dev notes (below). It is a risk signal for a human reviewer, not a guarantee that a note is safe, and not a compliance certification.

`deid/redteam/` adds a second model that reads a cleaned note the way an adversary would and reports what could still point to one person. It complements the detector: the detector looks for identifiers by type, the red-team looks at what is left.

```powershell
python -m deid.redteam.run                          # dry run: shows the prompt and one masked probe, calls nothing
python -m deid.redteam.run --live --limit 5         # real calls on the dev split (needs Patrick's go-ahead)
python -m deid.redteam.run --live --feedback        # also send leftovers back and re-clean leak probes
```

## What the reviewer sees

A masked view of the cleaned note: every span the replacement engine changed is shown as its type tag (`[NAME]`, `[DATE]`...). Surrogate values are never shown, because a made-up name cannot be told apart from a real one. So a name, date, number or place written in plain text is something the detector missed. Only this text is sent; never the original values or the answers.

It replies with a risk level (`low`, `medium`, `high`) and a list of clues, each with an exact quote, a category and a one-line reason. Categories: `LEFTOVER` (an identifier left in plain text, with its type), `RARE_CONDITION`, `OCCUPATION`, `EMPLOYER_OR_SCHOOL`, `SMALL_PLACE`, `PUBLIC_EVENT`, `FAMILY`, `OTHER`.

Each quote is located in the masked view and mapped back to character offsets in the original note (`assess.py`). Two rules are applied in code, not by the model:
- A located `LEFTOVER` identifier of a known type makes the note `high`, whatever level the model gave.
- An unreadable reply is reported as `unknown`, never as `low`.

## The feedback loop

`loop.py`: clean the note, show the masked result to the reviewer, add any located leftover identifier to the spans, clean again; up to two extra rounds, stopping when a round finds nothing new. This is what "sends risky notes back" means here: the reviewer's leftovers are fed back to the replacement step. It does not re-run the detector.

Clues that are not leftover identifiers (a rare condition, an occupation, a small town) are **not** edited automatically, because changing clinical content could change its meaning. They are returned as review items for a person.

## How it is tested

The frozen dataset has almost no identifying prose, so the reviewer is tested on probes built from dev notes (`probes.py`; the notes file and its hashes are untouched). Each probe ends with an ADDITIONAL HISTORY line, so the line's presence gives nothing away:

| Variant | What it is | What a good reviewer does |
|---|---|---|
| control | benign line; every true span replaced | rates it `low`, reports no leftover |
| planted | an invented line that makes the person easier to find (rare condition, occupation, public event, small place) | rates it `medium` or `high` and quotes the planted line |
| leak | benign line; two true spans withheld from the replacement step, as a detector's misses would be | finds the leftovers (`withheld_found`) |

`score.py` reports each rate with a 95% Wilson interval. With 5 notes the intervals are very wide, so a small run shows the pipeline works, not how good the model is.

Offline tests (`tests/test_redteam.py`) use a scripted reviewer. They check masking, offset mapping, clue cleaning, the risk rules, the cache, probe construction, scoring, the loop and the dry-run and test-split guards. They do not measure any model.

## First live smoke test (Oct 29)

Meta API `muse-spark-1.3`, prompt `rt1`, the first 5 dev notes, 15 probes (`results/dev/redteam-first5-dev.json`). 15 of 15 replies were readable, none truncated.

| Variant | Result (5 notes each) |
|---|---|
| control | 0 of 5 flagged medium or high; 0 reported a leftover |
| planted | 5 of 5 flagged and quoted the planted line |
| leak | 10 of 10 withheld spans found (6 names, 2 phones, 1 date, 1 email); all 5 notes rated high |

Cost and speed: 33,840 tokens (12,803 in, 21,037 out), median 4.7 s per call; dollar price per token still unknown. No feedback loop was run (`--feedback` off).

What this does and does not show: the pipeline works end to end and the model handled blunt, invented clues without false alarms on 5 notes. It does not show the reviewer is good. The probes are easy, 5 notes give intervals of roughly 0.57-1.0 for 5 of 5, and the 5 planted lines happened to cover only the public-event and small-place categories (rare condition and occupation were not exercised). Treat it as a smoke test.

## Known limits

- The planted sentences are short, blunt and invented by us. A model that catches them has shown it can read an obvious clue, not that it finds subtle ones. They are not a benchmark of real re-identification risk.
- The reviewer sees tags, not shifted dates or surrogate text, so it cannot judge risk from date patterns or from how surrogates read.
- `withheld_still_present` (feedback runs) is a plain string check on the cleaned text.
- Risk levels are the model's judgment plus one deterministic rule. They are not calibrated against real re-identification outcomes.
- Prompt wording (`rt1`) was written once, before any run; tune on the dev split only.
