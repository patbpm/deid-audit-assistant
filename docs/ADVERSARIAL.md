# Adversarial test set

Status: Day 6. A separate set of hard synthetic cases, built and scored with the three baselines, and run once with the Muse Spark agent (below). A second set (B) now exists for judging the fixes made after that run; **no model has been run on set B yet.** It is not part of the frozen dataset (`data/frozen.json` and its hashes are untouched). This is an assistant for human review, not a compliance certification.

```powershell
python -m deid.synth.adversarial                                   # writes data/generated/adversarial/ (git-ignored)
python -m deid.baselines.regex_baseline --notes data/generated/adversarial/notes.jsonl --out runs/adv-regex.jsonl
python -m deid.eval.adversarial --pred runs/adv-regex.jsonl --name regex
python -m deid.eval.adversarial --table                            # compare every saved result
```

180 short notes (20 per family), 540 labeled spans, seed 20261029, same record format and labeling conventions as docs/DATASET.md plus a `family` field. Note ids are `A0001`-`A0180`, patient ids `P9001`-`P9180`. `data/adversarial.json` (committed) records the seed, counts and the SHA-256 of the notes file (made on Python 3.14.7); `tests/test_adversarial.py` regenerates the set and checks it.

## Families

| Family | What it tests |
|---|---|
| common_word_names | Names that are also words (Hope, Will, Frank; White, Brown, Page), with the same words used as ordinary text in the same note, unlabeled. |
| odd_date_formats | `3rd of March 2025`, `3-Mar-25`, `2025.03.11`, `11Mar2025`, `Mar. 3, 2025`, year-less `03-11`, `Mar 3rd`. Pain scores, blood pressures, a bare year and `last Tuesday` stay unlabeled. |
| abbreviated_names | `J. Smith`, `Smith, J.`, `J.B. Garcia`, `SMITH, JOHN`, `smith, john`, `JF Wilson`. |
| typos_and_noise | Misspelled names, extra spaces, a letter O or l inside an MRN, `7/7//2025`, a phone with no area code. |
| non_english_names | Diacritics, hyphens and particles: `José García-López`, `Siobhan O'Reilly`, `Willem van der Meer`, `Łukasz Wiśniewski`. |
| lookalikes | Spine levels (`L4/5`), dose ratios, lab values, codes, versions, times: none labeled. Each note also has one name and one phone so recall is defined. |
| identifier_variants | `MRN#1234567`, `Acct No.`, a policy id, an SSN without dashes, fax and phone variants, emails with `+` and capitals. |
| address_variants | PO boxes, no commas, a spelled-out state, unit first, a bare town and state. |
| eponym_names | A clinician or patient whose surname is also a disease or device (`Dr. Foley` and a Foley catheter), with the eponym unlabeled. |

Labeling choices beyond DATASET.md: a bare year, `last Tuesday` and month-plus-year are not in the set as labeled spans; weekdays are not labeled; a name is labeled as written, misspellings included.

## Baseline results (type-agnostic recall, overlap; false positives per note)

| Family | Gold | philter: recall % (95% CI) / FP per note | presidio: recall % (95% CI) / FP per note | regex: recall % (95% CI) / FP per note |
|---|---|---|---|---|
| ALL | 540 | 96.3 (94.8-97.7) / 0.78 | 86.5 (83.1-89.4) / 1.16 | 14.4 (10.7-18.3) / 0.00 |
| abbreviated_names | 60 | 100.0 (100.0-100.0) / 0.00 | 98.3 (95.0-100.0) / 0.00 | 0.0 (0.0-0.0) / 0.00 |
| address_variants | 60 | 100.0 (100.0-100.0) / 0.60 | 85.0 (76.7-93.3) / 0.00 | 18.3 (10.0-25.0) / 0.00 |
| common_word_names | 40 | 100.0 (100.0-100.0) / 1.50 | 77.5 (67.5-87.5) / 0.60 | 0.0 (0.0-0.0) / 0.00 |
| eponym_names | 40 | 100.0 (100.0-100.0) / 1.75 | 97.5 (92.5-100.0) / 2.00 | 0.0 (0.0-0.0) / 0.00 |
| identifier_variants | 80 | 100.0 (100.0-100.0) / 0.50 | 97.5 (93.8-100.0) / 0.10 | 55.0 (43.8-65.0) / 0.00 |
| lookalikes | 40 | 100.0 (100.0-100.0) / 2.65 | 100.0 (100.0-100.0) / 4.75 | 50.0 (50.0-50.0) / 0.00 |
| non_english_names | 60 | 100.0 (100.0-100.0) / 0.00 | 100.0 (100.0-100.0) / 0.00 | 0.0 (0.0-0.0) / 0.00 |
| odd_date_formats | 60 | 100.0 (100.0-100.0) / 0.00 | 85.0 (78.3-91.7) / 3.00 | 3.3 (0.0-8.3) / 0.00 |
| typos_and_noise | 100 | 80.0 (80.0-80.0) / 0.00 | 58.0 (53.0-63.0) / 0.00 | 1.0 (0.0-3.0) / 0.00 |

Read these with care:
- **Not tuned.** The three baselines were fixed before this set existed and were not adjusted after seeing it.
- **The regex baseline** was written knowing the main dataset's formats (see docs/RESULTS.md), so its low score here shows how narrow it is, not how regex tools do in general.
- **Philter's near-perfect recall** comes with the most false positives on the lookalikes and eponyms; it flags a lot. Its misses are the MRNs with a letter inside the digits.
- **Presidio** finds only 77.5% of the names that are common words, none of the MRNs with a letter inside, 4 of 20 phones with no area code and 14 of 20 double-slash dates, and flags 4.75 spans per lookalike note that are not identifiers.
- **Intervals:** 20 notes per family. Where every note behaves the same (all hit or all missed) the interval collapses to a point, which is not certainty.
- **Type-agnostic:** a hit means some prediction overlaps the span, whatever its label.

## Muse Spark agent, one run (Oct 29)

The full agent (`muse-spark-1.3`: detect, verify uncertain spans, replace, red-team review, feedback) was run once on all 180 notes with 4 workers, and scored here and in `results/adversarial/agent-meta-detector.json` and `-final.json` (identical: the red-team added nothing). Prompts were the ones tuned on the main dev split; nothing was changed after seeing this set. Error analysis: `results/adversarial/agent-meta-adv-errors.json`; run summary: `results/adversarial/runs/agent-meta-adv.json`.

| Family | Gold | Agent: recall % / false positives per note | Philter | Presidio |
|---|---|---|---|---|
| ALL | 540 | 100.0 / 0.60 | 96.3 / 0.78 | 86.5 / 1.16 |
| abbreviated_names | 60 | 100.0 / 0.00 | 100.0 / 0.00 | 98.3 / 0.00 |
| address_variants | 60 | 100.0 / 0.00 | 100.0 / 0.60 | 85.0 / 0.00 |
| common_word_names | 40 | 100.0 / 1.00 | 100.0 / 1.50 | 77.5 / 0.60 |
| eponym_names | 40 | 100.0 / 1.05 | 100.0 / 1.75 | 97.5 / 2.00 |
| identifier_variants | 80 | 100.0 / 0.00 | 100.0 / 0.50 | 97.5 / 0.10 |
| lookalikes | 40 | 100.0 / 1.35 | 100.0 / 2.65 | 100.0 / 4.75 |
| non_english_names | 60 | 100.0 / 0.00 | 100.0 / 0.00 | 100.0 / 0.00 |
| odd_date_formats | 60 | 100.0 / 2.00 | 100.0 / 0.00 | 85.0 / 3.00 |
| typos_and_noise | 100 | 100.0 / 0.00 | 80.0 / 0.00 | 58.0 / 0.00 |

What the run shows, and what it does not:
- **Coverage.** Every labeled identifier was overlapped by a predicted span, including the ones the baselines miss (typos and noise, names that are common words, MRNs with a letter inside). 539 of 540 had exact boundaries; the other kept a trailing period. Each family has 20 notes or fewer, so the intervals are wide even where they collapse to a point.
- **Precision is where it loses.** 108 false positives, in two groups. (1) 41: the detector lists strings and the matcher marks every occurrence, so a surname that is also a common word or a disease name (Short, White, Page, Black, Stone, Bell, Cushing, Wilson, Foley) is replaced in "Short of breath" or "Wilson disease" as well as where it is the patient. (2) 67: "last Tuesday", "tomorrow" and "2019" were listed as dates; the dataset's rules do not label them. Philter has fewer false positives than the agent on the odd-date family (0.00 against 2.00 per note) and the same or more in every other family.
- **Review.** 68 of the 108 false positives were flagged for a person; 40 were replaced with no flag. Of the 540 true identifiers, 52 were flagged for a person and 488 were not. The verifier was asked about 64 spans, said "not an identifier" for 15 (all of them false positives) and "identifier" for 49, of which 44 were false positives.
- **Red-team.** 174 notes low risk, 6 medium (all eponym-name notes, where it quoted a rare condition such as Cushing syndrome as a clue). It added no spans, so the feedback loop did nothing here either.
- **Review-burden curve** (`results/adversarial/burden-agent-meta-adv.json`): 56 candidates under 0.8 confidence, 5 of them true. Reading them in confidence order reached 90% of the gain after 6, near the best possible 5, against 52 in random order. A perfect reviewer is assumed, and the gain is under 1 point of recall.
- **Cost.** About 685,000 tokens, 2.42 USD at list price.
- **Now a tuned set.** These errors have been read, so this set can no longer judge a fix. Any change to the prompts or matching made because of them must be judged on a new adversarial set from a different seed (set B did this; the 400 test notes were run after, `docs/TEST_RUN.md`).

## Fixes made after that run, and the second set (Oct 29)

The two causes of the 108 false positives were fixed in the code (nothing was run live afterwards):

1. **Relative and year-only dates.** The detection prompt (now `v2`) says a year on its own and relative expressions are not DATE, and `deid/detect/context.py` sets such a listed string aside with the reason recorded. HIPAA's Safe Harbor list leaves a bare year alone; relative dates carry no calendar day.
2. **Every occurrence of a listed name replaced.** A listed name directly followed by an eponym noun and without a title or label before it ("Wilson disease") is set aside by rule. For a name the detector flags as also an ordinary word, each occurrence without a title or label gets its own model check (`deid/agent/nameuse.py`). Only a clear "ordinary word" leaves it as written; it is then recorded in the audit and sent to review, where "Replace it after all" is one click. Any other answer keeps it replaced.

**Replay of the saved set-A replies through the new rules** (`python -m deid.eval.replay`, no model call; `results/adversarial/rules-replay-a.json`): recall stays 540 of 540 and false positives fall from 108 to 18 (0.10 per note), all 18 in the common-word-names family, which needs the model check that a replay cannot run. The rules were written after reading these errors, so this shows what the rules do, **not** how well they generalize. The same replay over the 200 dev notes' saved replies changes nothing (3,023 of 3,023 found, no false positives, nothing set aside).

**Set B** (`python -m deid.synth.adversarial --vocab b`, seed 20261030, `data/adversarial_b.json`): 200 notes, 609 labeled identifiers, the nine families again with different common words (Hall, Rice, Wood, Frost, Sharp...), eponyms (Marfan, Barrett, Glasgow, Apgar...), names, lookalike sentences and date phrasings, a second layout for the eponym notes, a tenth family of notes dense in relative and year-only dates, and **real patient surnames written bare** (no title or label before them, as in "Swift was cooperative throughout the visit") in about half of the common-word notes and some eponym notes.

**Why the bare surnames:** a stress test (below) showed that the first version of set B could not see the one dangerous failure of the name check, a real name wrongly released as an ordinary word, because every real surname in it had a title or was part of a full name. Set B had not been run on any model, so it was corrected before use; set A was not touched. Some eponym nouns (esophagus, sarcoma, thyroiditis, coma scale) and some relative phrasings ("a few weeks back", "in the spring", "the week before admission") are deliberately outside the rule lists, so the prompt and the model check have to do that part. Set B was written after set A's errors were known, so it is a test of the fixes, not an independent discovery set; its words are disjoint from set A's and from the examples in the prompts (tested). Baselines on set B (not tuned, run on Oct 29):

| Family | Gold | Philter: recall % / FP per note | Presidio | Regex |
|---|---|---|---|---|
| ALL | 609 | 95.9 / 0.83 | 83.6 / 1.55 | 14.0 / 0.00 |
| relative_dates | 60 | 100.0 / 0.15 | 86.7 / 5.00 | 0.0 / 0.00 |
| common_word_names | 40 | 95.0 / 1.80 | 52.5 / 0.35 | 0.0 / 0.00 |
| eponym_names | 49 | 100.0 / 1.80 | 98.0 / 1.70 | 0.0 / 0.00 |
| odd_date_formats | 60 | 100.0 / 0.55 | 81.7 / 3.75 | 5.0 / 0.00 |

(all families: `python -m deid.eval.adversarial --out results/adversarial-b --table`.)

**Stress test of the name check, no model** (`python -m deid.eval.stress`, `results/adversarial-b/stress/`): a scripted detector lists exactly the true identifiers (plus, in the common-word and eponym families, every capitalized word of a true name, as the real model did) and flags those names; the name check then gives one fixed answer. With "name" or "unsure" every time (never release): recall 609 of 609, 51 false positives (0.26 per note), all ordinary uses that stay replaced and go to review. With "ordinary_word" every time (always release, the worst case): 0 false positives but recall 96.6% (21 real bare surnames left in the text). So the design is bounded: a model that leans cautious costs false positives, and a model that leans careless costs recall, and set B can now measure which one Muse Spark does. On the original set B (no bare surnames) the worst case lost nothing, which is why it was corrected.

## Muse Spark agent on set B, one run (Oct 29)

The full agent (`muse-spark-1.3`, detection prompt `v2`, the name check, verifier, red-team, feedback) was run once on all 200 notes of set B (4 workers; 785,579 tokens, about 2.74 USD at list price). Nothing was changed between writing set B and this run. The test stated in advance: false positives per note below Philter's 0.83 with recall near 100%, and no real surname released. **It passed.** Files: `results/adversarial-b/agent-meta-advb-detector.json` and `-final.json`, error analysis `results/adversarial-b/agent-meta-advb-errors.json`, run summary `results/adversarial-b/runs/agent-meta-advb.json`.

| | Recall (type-agnostic overlap) | False positives per note |
|---|---|---|
| **Agent, detection stage** | **100.0%** (609 of 609, including all 21 bare real surnames) | **0.005** (1 false positive) |
| Agent, after red-team feedback (the run as made) | 100.0% | 0.035 (7) |
| Agent, after the red-team convention fix (re-run from saved replies, no new calls) | 100.0% | 0.005 (1) |
| Philter | 95.9% | 0.83 |
| Presidio | 83.6% | 1.55 |
| Regex | 14.0% | 0.00 |

What the run shows, and what it does not:
- **The name check did its job.** It was asked about 51 doubtful occurrences. It left 29 as written, every one an ordinary use ("Hall ambulation", "Kaposi sarcoma") and not a labeled name, and kept 22 replaced: all 21 bare real surnames and one ordinary "Hall". Nothing was unreadable or cut off. The stress test showed what a careless check would have cost (recall 96.6%); this one cost nothing here.
- **The date rules were not needed on this run.** With the v2 prompt the model never listed a year-only or relative date, so the rule set aside 0 dates (it set aside 19 eponym occurrences). The prompt change did that work. The rule is a backstop.
- **A problem the fix created, found by this run:** the red-team reviewer saw the year-only dates now left in the text, reported 6 of them as leftover dates, and the feedback loop re-added them (7 false positives in the final output against 1 from the detector). It also rated 3 notes high risk. The detection stage and the red-team stage disagreed about a convention. The red-team's leftovers now go through the same set-aside rule (they become review clues a person can redact), tested in `tests/test_redteam.py` and re-run from the saved replies for no new cost: final false positives 7 to 1, recall unchanged. Three notes still show high risk because the reviewer model itself rated them high; that rating was left as the model gave it.
- **Set B has been read for that fix.** The detection-stage numbers are from the run as made, before any change. The red-team row "after the fix" is a mechanical consistency repair, but it was made after seeing this set, so treat that row as tuned.
- **Limits.** A single run; 20 notes per family or fewer, so intervals are wide; set B was written by the project after set A's errors were known, with a corrected design (bare surnames) after the stress test; and these are short synthetic notes. This is not evidence of accuracy on real clinical text. Set A (108 false positives, prompt `v1`) and set B (1, prompt `v2`) are different sets, so the two numbers are not a like-for-like before and after.
- **Review load:** 99 review items across 86 of the 200 notes in the run as made (60 replacements flagged). The review-burden curve for this run has not been run yet.

**Dev re-run with prompt `v2` (Oct 29):** no regression. 3,023 of 3,023 labeled identifiers with exact boundaries, 0 false positives, nothing unreadable; the name check was asked about 6 occurrences and left none as written (`results/dev/agent-meta-dev-v2*.json`). Easy template text on the split the prompts were tuned on, so this shows no regression, not accuracy.

**Test split run (Oct 29 - 30):** the 400 held-out test notes were run once on the final system with the criteria written first, and all four passed (5,992 of 5,992, 0 false positives; `docs/TEST_RUN.md`). Optionally the agent with prompt `v2` on set A, for a like-for-like before and after on one set (set A is a tuned set).

## Rules for using it

- Treat it as a test set. Do not tune prompts, thresholds or rules on it; run each final system on it once for reporting.
- Reading the misses to describe failure modes is fine after the final run; changing a system because of them is not.
- If the generator changes, the recorded hash changes and every earlier score on it is stale.
