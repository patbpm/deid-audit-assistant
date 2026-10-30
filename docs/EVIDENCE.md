# Evidence: every result, with its conditions

All numbers are on synthetic notes and come from files in `results/`, reproducible with the commands in `docs/CLAIMS.md` and the docs named below. Cost figures are estimates from token counts at list price (`docs/PRICES.md`); reasoning-token billing is not stated by the vendor. Nothing here has been measured on real text.

## Baselines on the test split

400 notes; type-agnostic overlap; full tables, intervals and caveats in `docs/RESULTS.md`.

| System | Recall % | Precision % |
|---|---|---|
| Format-aware regex (written knowing the synthetic formats) | 54.0 | 100.0 |
| Presidio, default settings | 94.7 | 74.3 |
| Philter, through a compatibility shim | 100.0 | 86.4 |

## Full agent on the 400 held-out test notes

Pre-registered in `docs/TEST_RUN.md` before the run and run once (two sessions, no change between them), Muse Spark `muse-spark-1.3`, prompt v2 with the name check, 4 workers. Notes P0051-P0150, frozen Oct 27, never used for tuning. Easy template text, the same generator as dev.

All four pre-stated criteria passed: 5,992 of 5,992 labeled identifiers found with exact boundaries and the right type (names 2,587, dates 1,700, phones 712, IDs 634, addresses 300, emails 59), 0 false positives, 400 of 400 notes cleaned with no unreadable or cut-off replies, and no original identifier left word for word (two search hits, both coincidences: the date "8/1" inside "Pain 8/10", and "King" at the start of the stand-in "Kingsley"). The name check was asked about 11 occurrences and left none as written; the red-team rated 397 low, 1 medium and 2 high (all three for the template generator's implausible combination of a young woman with COPD on home oxygen) and sent nothing back; 376 review items, 373 of them date guesses. 2.70 million tokens, about 9.43 USD at list price (the first session hit its token cap before the red-team stage and was resumed with approval; details in `docs/TEST_RUN.md`). A held-out result for the model-based system on this kind of text; it does not show performance on real notes, and the hard cases are in the adversarial sets.

## Adversarial set A (180 notes, nine families)

Written before any fix. The agent was run on it once; it is now a tuned set. `docs/ADVERSARIAL.md`.

| System | Recall % | False positives per note |
|---|---|---|
| Philter | 96.3 | 0.78 |
| Presidio | 86.5 | 1.16 |
| Regex | 14.4 | 0.00 |
| Muse Spark agent (detect, verify, replace, red-team), prompt v1, one run | 100.0 | 0.60 |

The agent covered all 540 labeled identifiers (type-agnostic overlap; 539 with exact boundaries) but made 108 false positives. Two causes make up all of them: a name that is also a common word or a disease name ("Short of breath", "Wilson disease") is replaced everywhere it appears once it is listed as a name (41), and relative or year-only dates ("last Tuesday", "2019") were listed as dates (67). 68 of the 108 were flagged for a person; 40 were replaced silently. The review-burden curve is informative here: 56 candidates fell under 0.8 confidence and only 5 were true, and ranking by confidence reached 90% of the gain after 6 reviews against 52 in random order (with a perfect reviewer assumed). One run on 180 synthetic notes (20 per family in most), wide intervals, a set the project wrote. About 2.42 USD.

## The two fixes, and set B

Fixes (`docs/ADVERSARIAL.md`): detection prompt v2 (year-only and relative dates are not dates; the model marks a name that is also an ordinary word); rules that set such dates aside and a name followed by an eponym noun with no title before it; and a per-occurrence name check with its own call that fails closed (only a clear "ordinary word" leaves text as written, and a person can choose "Replace it after all"). Replaying set A's saved model replies through the new rules, with no model call, takes false positives from 108 to 18 with recall unchanged. The rules were written after reading those errors, so that is a tuned set, not evidence.

Set B was built to judge the fixes: 200 notes, 609 labeled identifiers, a new seed (20261030) and different vocabulary, ten families, 21 real surnames written bare with no title. It was corrected once before any model saw it, after an offline stress test showed the first version could not detect a wrongly released real name.

| System on set B | Recall % | False positives per note |
|---|---|---|
| Philter | 95.9 | 0.83 |
| Presidio | 83.6 | 1.55 |
| Regex | 14.0 | 0.00 |
| Muse Spark agent, prompt v2 with name check, detection stage, one run | 609 of 609 covered | 0.005 (1 in total) |
| same, after red-team feedback, as first run | 609 of 609 | 0.035 (7) |
| same, after fixing the red-team stage | 609 of 609 | 0.005 (1) |

The pre-stated test (every one of 609 covered, including the 21 bare surnames, and fewer false positives than the baselines) passed. The name check was asked about 51 doubtful occurrences, released 29 ordinary uses and kept 22 replaced (all 21 bare surnames and one ordinary use); no reply was unreadable or cut off. About 2.74 USD. The 7-to-1 change came from a stage disagreement my date fix created (the red-team reviewer reported year-only dates left in place and the feedback loop re-added them); the fix was made after reading set B's errors, so that row is tuned, and the run was re-played from saved replies at no cost.

Stress test (scripted perfect detector, name check answering one fixed answer, `deid.eval.stress`): if the check never releases a doubtful occurrence, recall is 609 of 609 with 51 false positives; if it always releases, 0 false positives but recall 96.6% (21 bare surnames left in). This shows the design's bounds, not anything about Muse Spark.

## Full agent run on the 200 dev notes

`results/dev/agent-meta-dev*.json`. Easy synthetic text and the split the prompts were tuned on, so not a held-out result. Run with prompt v1 and again with prompt v2.

Prompt v1: all 3,023 labeled identifiers found with exact boundaries and the right type, no false positives (names 1,312, dates 850, phones 361, ids 319, addresses 150, emails 31). No reply was unreadable or cut off, and all 200 notes were cleaned. None of the 3,023 identifiers appears word for word in the cleaned notes. The verifier was asked about 6 spans and confirmed them. The red-team rated all 200 cleaned notes low risk and found no leftovers. 199 changes were flagged for a person, all of them dates whose day/month order or year had to be guessed. About 1.07 million tokens in two sessions, roughly 3.6 USD. With 4 workers the second session took about 4 minutes.

Prompt v2 with the name check (`agent-meta-dev-v2*`): the same 3,023 of 3,023 with 0 false positives; the name check was asked about 6 occurrences and left none as written; red-team rated all 200 low; about 3.75 USD. No regression shown.

## Smoke tests with `muse-spark-1.3` (5 dev notes each)

- Detector: all 83 identifiers found, no false positives, no unreadable replies (`results/dev/meta-first5-dev.json`). This shows the pipeline works, not how accurate the model is.
- Red-team, on 15 probe notes built from those 5 notes (`results/dev/redteam-first5-dev.json`): 0 of 5 control notes flagged, 5 of 5 planted clues flagged and quoted, 10 of 10 withheld identifiers found. The probes are blunt and invented by us.
- Agent run (`docs/AGENT.md`): all stages ran; the verifier confirmed the 2 low-confidence spans, the red-team rated all 5 notes low, and 83 of 83 identifiers were found.

## Dictated and scanned input

5 synthetic dictated and 5 synthetic scanned dev notes (`docs/INGEST.md`): the vision model copied the pages exactly; Muse Voice Transcribe's transcripts had a 30% word error rate and respelled many names; after cleaning, none of the identifiers the check could still find in the text remained (0 of 107). The first attempt exposed a failure where notes were written out uncleaned; they are now withheld and flagged. Harder inputs (12 dB noise, tilted, blurred, compressed scans, one 7-minute recording): word error unchanged at about 30% for audio (inflated by formatting), 0.1% for scans; none of the identifiers still readable after transcription survived cleaning. Clean or mildly degraded synthetic inputs, no handwriting or real recordings.

## Table mode (CSV)

60 invented patients and 121 encounters in two linked tables (`docs/TABLES.md`): with plain headers every column was typed right; with differently worded headers 18 of 24 were, and the 4 left unplaced were withheld rather than guessed; with no headers 15 of 24. With optional model help, confirmed by the rules, those rose to 22 and 21 of 24. Free-text comment cells cleaned by the model left none of 163 embedded identifiers. In all four header styles none of the 1,247 original identifiers remained, patient and MRN links between the two tables held, and each patient's dates moved by one offset. Invented, tidy tables: no claim for real ones. A separate screen flags rows in small groups of age, ZIP and diagnosis (all 60 invented patients are unique on ZIP code alone); it counts within the table, not the population, and changes nothing.

## Front page with the hosted model

Run once on its two samples (`docs/APP.md`, `results/dev/app-live-check.json`): notes job 64 replacements, 2 review items, risk low on all 4, 0 of 64 true identifiers left verbatim, and a first name with no cue that the offline engine misses was found. Tables job: 4 columns placed by the model with the rules confirming, 41 of 41 free-text comments cleaned. About 0.17 USD.

## Replacement check

Dev split, true spans, 200 notes: no original names, IDs, phones, emails or addresses left, one date shift per patient, no inconsistent or colliding name surrogates (`results/dev/replace-dev.json`). Because true spans were given, this shows the replacement step is sound, not that the pipeline is. Known weak spot: 3 of 46 year-less dates came out a day off across a leap day.

## Open-weights model as the detector (dev notes, one run)

Muse Spark Open (`meta-models/muse-spark-open`, Baseten Model APIs), detector only, prompt v2, the 200 dev notes, scored against the saved Muse Spark (`muse-spark-1.3`) detector output on the same notes: **99.2% recall (98.8-99.5), 100.0% precision, 0 false positives, -0.8 points of recall against Muse Spark (paired interval -1.2 to -0.5).** All 25 misses of 3,023 identifiers are names, and all are bare repeat mentions of a name (for example "Mrs. Kim" or "Karen reports") that the model did not list as a separate string; whether the replacement step would catch them anyway was not measured for this model.

Cost and speed of the open model (estimated at list price, $1.25 in / $4.25 out per million tokens): the first run used a 4,096-token output limit with no retry and 82 of 200 replies were cut off (recall 51.8% at that setting: a setting problem, not a measure of the model). The rerun, which asked the cut-off notes again once at 16,384 tokens, finished all 200. Both runs together used 310,161 input and 1,187,479 output tokens, about $5.43; first-attempt latency was 10.6 s median (13.5 s p90); the 82 retried notes took 20.1 s median counting both attempts. The model reasons at length, so output limit and retry matter.

Caveats: one run each; easy template notes; the dev notes are the split the prompts were tuned on, with Muse Spark, so the open model used a prompt that was not tuned for it; only the detector was run, not the verifier, name check or red-team, and not the held-out or adversarial sets; Muse Spark's own cost and latency were not measured with the same command, so no cost or latency comparison between the two models is claimed. Files and commands: `docs/COMPARISON.md`.

### Held-out notes (all 400)

Muse Spark Open, detector only, prompt v2, all 400 held-out test notes, scored against the saved Muse Spark detector output on the same notes: **98.9% recall (98.6-99.1) of 5,992 labeled identifiers, 100.0% precision, 0 false positives, -1.1 points of recall against Muse Spark (paired interval -1.4 to -0.9).** All 67 misses are names (name recall 97.4%); dates, IDs, phones, emails and addresses were all found. Cost about $9.26 at list price ($1.25 in / $4.25 out per million tokens; 527,789 in / 2,022,963 out tokens in total); no cut-off replies and no parse errors. The run was done in two parts: the first hit its 2.2M-token cap after 340 notes (99.0% recall on those 340, about $8.00) and the last 60 were run afterwards with the first 340 replies reused from the saved copy (about $1.26). Latency: median 12.3 s per note on the first 340 and 16.3 s on the last 60 (not pooled). Caveats: one run; easy template text; detector only; the test split has now been used for this run, so it is no longer untouched for tuning.

## Built, tested with scripted models only

- Two-model cross-check (`docs/CROSSCHECK.md`): no real second model run; no claim that disagreement is a better review signal than confidence.
- Watch mode (`docs/WATCH.md`): tried by hand on synthetic notes with the offline rules; not run with a hosted model.

## Not measured

Muse Spark Open on the held-out or adversarial sets, inside the full agent, or its cost and latency against Muse Spark's under the same command; the two-model cross-check with a real second model; watch mode with a hosted model; any real clinical text; any reviewer other than the developer.
