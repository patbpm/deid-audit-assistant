# What each stage adds

Status: measured Oct 31, 2026 from runs already made (no model call; `python -m deid.eval.ablation --all`). One run of each set; recall is type-agnostic overlap, as in `docs/ADVERSARIAL.md`. This is an assistant for human review, not a compliance certification.

Why: a 2026 study of an LLM de-identifier found that none of 14 multi-agent or ensemble setups beat one well-calibrated prompt (https://arxiv.org/abs/2608.17051). This page asks the same question of this pipeline: the detector alone, then each added stage, scored on the sets the project already has.

### 200 dev notes (easy template text, the split the prompts were tuned on)

200 notes; saved run `agent-meta-dev-v2`.

| Stage | Labeled identifiers | Recall % (95% CI) | False positives | Leaked chars % |
|---|---|---|---|---|
| detector | 3023 | 100.0 (100.0-100.0) | 0 | 0.00 |
| + name check | 3023 | 100.0 (100.0-100.0) | 0 | 0.00 |
| + red-team feedback | 3023 | 100.0 (100.0-100.0) | 0 | 0.00 |

Verifier (changes no text; a doubt sends the span to a person): said identifier: 10 real, 0 not real

Name check (settles doubtful name occurrences): left nothing as written.

Red-team feedback added 0 spans: 0 real identifiers, 0 not identifiers.

### adversarial set B (200 short notes written to be hard; the name check and a red-team fix were tuned on set A and read set B)

200 notes; saved run `agent-meta-advb-rtfix`.

| Stage | Labeled identifiers | Recall % (95% CI) | False positives | Leaked chars % |
|---|---|---|---|---|
| detector | 609 | 100.0 (100.0-100.0) | 30 | 0.00 |
| + name check | 609 | 100.0 (100.0-100.0) | 1 | 0.00 |
| + red-team feedback | 609 | 100.0 (100.0-100.0) | 1 | 0.00 |

Verifier (changes no text; a doubt sends the span to a person): said identifier: 26 real, 0 not real; said unsure: 0 real, 1 not real

Name check (settles doubtful name occurrences): left as written, not an identifier (a false positive avoided): 29

Red-team feedback added 0 spans: 0 real identifiers, 0 not identifiers.

### 400 held-out test notes (easy template text, used once)

400 notes; saved run `agent-meta-test`.

| Stage | Labeled identifiers | Recall % (95% CI) | False positives | Leaked chars % |
|---|---|---|---|---|
| detector | 5992 | 100.0 (100.0-100.0) | 0 | 0.00 |
| + name check | 5992 | 100.0 (100.0-100.0) | 0 | 0.00 |
| + red-team feedback | 5992 | 100.0 (100.0-100.0) | 0 | 0.00 |

Verifier (changes no text; a doubt sends the span to a person): said identifier: 19 real, 0 not real

Name check (settles doubtful name occurrences): left nothing as written.

Red-team feedback added 0 spans: 0 real identifiers, 0 not identifiers.

## What this shows, and what it does not

- **On the easy template sets (dev and held-out test) the detector alone is already at 100% recall and 0 false positives**, so later stages have nothing to add there. Do not read the later rows as "no effect"; they show the sets are easy. Dev is the split the prompts were tuned on.
- **The name check is the stage that earns its place, on the hard set.** On adversarial set B the detector alone has 30 false positives (ordinary words and condition names that are also surnames, listed as names); the name check releases 29 of them and leaves recall at 100%. The name check was designed after reading set A's errors, and set B was read for a later fix, so this is a tuned result and not an estimate of how it generalizes.
- **The verifier changes no text.** It answered about 27 spans on set B: 26 real identifiers confirmed and one unsure, which went to a person (and was not a real identifier). On dev and test it confirmed 10 and 19 real identifiers and found nothing wrong, since nothing was wrong. Its value, sending doubtful spans to a person, cannot show up as recall or false positives.
- **Red-team feedback added no span in any of the three runs.** It rated notes and listed clues for a person, but it did not recover a missed identifier here, because the detector missed none. Whether it recovers misses from a weaker detector is not shown by these runs (a weaker detector exists: the open-weights run, see `docs/COMPARISON.md`).
- **No cost or latency per stage is reported here.** The stages' token use is in the run summaries.
- The Safe Harbor rules (`docs/REPLACEMENT.md`) are not in the table: no labeled note has an age of 90 or more, a ZIP outside an address, a URL or an IP address.

Reproduce (needs the git-ignored `runs/` folder from the original runs, including `runs/cache`): `python -m deid.eval.ablation --all`. Per-set results: `results/ablation/`.
