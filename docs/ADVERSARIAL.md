# Adversarial test set

Status: Day 6. A separate set of hard synthetic cases, built and scored with the three baselines. **No model has been run on it yet.** It is not part of the frozen dataset (`data/frozen.json` and its hashes are untouched). This is an assistant for human review, not a compliance certification.

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
- **Now a tuned set.** These errors have been read, so this set can no longer judge a fix. Any change to the prompts or matching made because of them must be judged on a new adversarial set from a different seed, and on the 400 test notes.

## Rules for using it

- Treat it as a test set. Do not tune prompts, thresholds or rules on it; run each final system on it once for reporting.
- Reading the misses to describe failure modes is fine after the final run; changing a system because of them is not.
- If the generator changes, the recorded hash changes and every earlier score on it is stale.
