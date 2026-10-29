# Build plan: Oct 26 - Nov 4

Times are Central (ET minus 1 hour). Weekdays are short blocks because of other jobs; weekends are the deep days. Adjust hours to your real schedule.

Live sessions (ET, streamed on the CV page; Discord office hours are text only, 10-11 AM ET on weekdays):
- Tue Oct 27, 12-1 PM ET (11 AM CT): Agents 101, build a multimodal AI agent
- Wed Oct 28, 12-1 PM ET (11 AM CT): Agents 102, best practices for verifiable agents (directly relevant to our evaluation design)
- Fri Oct 30, 12-1 PM ET (11 AM CT): Fireworks, building specialized intelligence with Muse open models

| Day | Date | Focus | Done when |
|---|---|---|---|
| 1 | Mon Oct 26 | Claim credits; request Modal and Baseten credits (first come); join Discord and post in #intros; read the Participant Guide; ask the eligibility question in #questions; repo, venv and smoke test | Credit form submitted; credit requests sent; API smoke test passes once the credit shows |
| 2 | Tue Oct 27 | Synthetic clinical-note generator with ground-truth labels; watch Agents 101 | 500+ synthetic notes with labeled spans (names, dates, IDs, phones, addresses) |
| 3 | Wed Oct 28 | Evaluation harness and baselines; adversarial test generator (hard cases added to the fixed test set); watch Agents 102 | Precision/recall per identifier type for Presidio and Philter, including on hard cases |
| 4 | Thu Oct 29 | Detection with a hosted model: Muse Spark via Meta API first, then Muse Spark Open on partner inference (prompt, JSON schema, span matching) | First recall/precision numbers for the hosted model(s) |
| 5 | Fri Oct 30 | Replacement engine: date shifting with preserved intervals, consistent pseudonyms; Fireworks session | Output notes keep clinical meaning; consistency tests pass |
| 6 | Sat Oct 31 | Agent loop: detect, verify, flag uncertain spans; re-identification red-team agent (risk signal, sends risky notes back); Meta Model API for hard cases (only once credit is confirmed) | Open-weights (partner inference) vs Meta API comparison table (accuracy, cost, latency); red-team risk levels reported on the test set |
| 7 | Sun Nov 1 | Review interface and audit report with evidence trace (span offsets, detector, confidence, verifier decision) that look good on video | A reviewer can accept/reject flags; report lists every change with its evidence |
| 8 | Mon Nov 2 | Full evaluation runs (synthetic data only); error analysis; record a first demo take | Final tables and a list of known failures |
| 9 | Tue Nov 3 | Final 3-minute demo video, README, write-up; feature freeze. Last full day for submission questions and technical help. | Submission draft complete; repo public; video link works |
| 10 | Wed Nov 4 | Final test from a clean clone; submit on the CV platform | Submitted by 5:00 PM Central (deadline 8:00 PM) |

## Demo (25% of the score)
- Three minutes, showing only what was built during the hackathon. Mark clearly what is new.
- Show it working live: a synthetic note goes in, identifiers are found, uncertain spans flagged, a reviewer decides, the cleaned note and audit report come out.
- Show the evaluation table with the honest numbers, including failures.
- Record a rough take on Day 8 so there is time to fix problems.

## Impact and Meta tooling (55% of the score together)
- Impact: who benefits (researchers and data teams who cannot send text to a cloud API), why it matters, and how it could be used. State this plainly without invented statistics.
- Meta tooling: go beyond a basic integration. Compare the open-weights model with Muse Spark via API, use structured outputs, and make the verifier step a real part of the agent.
- The "Best Build on Meta Open Weight Models" bonus ($10K) rewards projects built on Muse Glimmer or Muse Spark Open served on your own hardware or partner inference. Using Muse Spark Open on partner inference fits (it must run on an eligible Meta open-weight model; the infrastructure partner verifies this).
- The "Best Agentic Use-Case" bonus ($5K) rewards autonomy and multi-step workflows. The detect-verify-flag loop fits.

## Evaluation (proof of technical depth)
- Metrics: recall first (a missed identifier is the failure that matters), then precision, per identifier type.
- Compare: Presidio, Philter (both run on your CPU), Muse Spark Open on partner inference, Muse Spark via Meta Model API.
- Keep the test set fixed after Day 3 so results are comparable.
- Report failures honestly, including identifier types the tool misses.

## If time runs short, cut in this order
Stretch features, then audit report polish, then the open-weights-vs-API comparison. Never cut the demo or the evaluation.

## Submission checklist
- [ ] Public repo with README, setup steps and reproducible evaluation
- [ ] 3-minute demo video, link accessible without login
- [ ] Everyone who worked on the project is listed (solo: you)
- [ ] Clear statement of what was built during the hackathon
- [ ] Limitations section (not a compliance certification)
- [ ] Submitted on the CV platform before 5:00 PM Central on Nov 4
- [ ] Optional: post the demo on X and submit the link (Most Viral prize, judged on engagement until Nov 8)

## Progress log (verified results only)
- Day 1 (Oct 26): repo, venv and smoke-test script created. The API smoke test has not been run; waiting for credits to show under Billing.
- Day 2 (Oct 27): synthetic generator built (`deid/synth/`). 600 notes, 150 patients, 9,015 labeled spans across NAME, DATE, ID, PHONE, EMAIL and ADDRESS; reproducible with seed 20261027. See docs/DATASET.md for the format, counts and limitations.
- Day 3 (Oct 27, started a day early): evaluation harness (`deid/eval/`) and three baselines scored on the 400-note test split (P0051-P0150): a format-aware regex, Presidio (default settings, spaCy en_core_web_lg) and Philter (run through a regex-flag compatibility shim on Python 3.14). Type-agnostic overall recall: regex 54.0%, Presidio 94.7%, Philter 100.0%; precision 100.0%, 74.3%, 86.4%. Full tables, intervals and caveats: docs/RESULTS.md (generated from results/*.json). Dataset and test split frozen on Oct 27 with Patrick's approval (`data/frozen.json`, guarded by `tests/test_frozen.py`; see docs/DATASET.md). Tune on dev only.
- Day 4 (Oct 27, in progress): hosted-model detector built and tested offline, **no model has been run yet and there are no model scores.** `deid/detect/` holds the prompt (v1; asks for identifier strings, not offsets), a span matcher that marks every occurrence and reports strings it cannot find, an OpenAI-style client with retries, a response cache and a token cap. `python -m deid.detect.run` is a dry run unless `--live` is passed, uses the dev split only, and sends note text only. Tests use a fake model, including an oracle that returns the gold strings (matcher recovers 100% of gold spans on 12 generated notes, which checks the matcher, not any model). First live smoke test (Oct 28, credit confirmed by Patrick): Meta API `muse-spark-1.3`, prompt v1, the first 5 dev notes (83 identifiers). All 83 found with matching types, 0 false positives, 0 parse errors, 0 unmatched strings (`results/dev/meta-first5-dev.json`). This is 5 notes of easy synthetic text, so it shows the pipeline works, not how accurate the model is. Cost/latency seen: 18,502 tokens total (3,640 in, 14,862 out, most of the output presumably reasoning), about 3.7k tokens and 13 s per note; that extrapolates to roughly 0.74M tokens for the 200 dev notes and 1.5M for the 400 test notes. Dollar price per token not yet known.
- Day 5 (Oct 28): replacement engine `deid/replace/` (design and limits: docs/REPLACEMENT.md). Per-patient date shift keeps intervals; names are mapped token by token so every written form and relatives' surnames stay linked; IDs, phones, emails and addresses keep their shape; anything unparseable is tagged and flagged. Checked on the dev split with true spans (200 notes, 3,023 spans; `results/dev/replace-dev.json`): 0 flagged, 0 original identifiers left, one shift per patient, no inconsistent or colliding name surrogates. Known weak spot: 3 of 46 year-less dates came out a day off across a leap day. Not yet run on the test split or on a detector's full output; the zero-leak figure is partly by construction because true spans were used.
- Day 6 (Oct 28, in progress): re-identification red-team `deid/redteam/` built and tested offline (design and limits: docs/REDTEAM.md). A second model reads a masked view of the cleaned note (changed spans shown as tags) and reports a risk level and clues; located leftover identifiers are sent back to the replacement step for up to two extra rounds, while rare-condition, occupation and place clues are returned as review items and never edited. Tested on dev-note probes (control, planted clue, withheld spans) with a scripted reviewer: 28 tests, 131 in the suite. **No model has been run on it yet; there are no red-team scores.** Agent loop with the detector in front, and a live run, are next.
- Day 6 (Oct 29): audit report with evidence trace `deid/audit/` (docs/AUDIT.md). Each change links to its original offsets, detector, confidence, agreeing detectors, rewrite rule and a rule-based check's decision; a review queue adds unmatched model strings and red-team clues; one self-contained HTML page shows original and cleaned text side by side with click-through highlighting. Built from the 5-note smoke-test output (83 changes, 6 sent to review: 3 month-first dates, 1 year-less date, 2 low-confidence spans); no model called. The checks are rules, not a model verifier.
- Day 6 (Oct 29): red-team first live smoke test, `muse-spark-1.3`, prompt rt1, 5 dev notes, 15 probes (`results/dev/redteam-first5-dev.json`): control 0/5 flagged, planted 5/5 flagged and cited, leak 10/10 withheld spans found. 33,840 tokens, median 4.7 s per call. Easy invented probes and a tiny sample, so this shows the pipeline works, not how good the reviewer is; the planted lines covered only 2 of 4 clue categories. Feedback loop not yet run live.
- Day 6 (Oct 29): agent loop `deid/agent/` built and tested offline (docs/AGENT.md): detect, verify uncertain spans with a second model call (the verifier confirms or raises doubt, never removes), replace, red-team review, leftovers fed back for up to two rounds, audit with the verifier's verdict in each trace. 162 tests pass, using a scripted model. **Not yet run live; no scores for the loop.** The run scores the detector's spans and the post-feedback spans separately so the feedback loop's effect on recall can be read directly.
- Day 6 (Oct 29): review interface `deid/review/` (docs/REVIEW.md): a local page where a reviewer accepts or rejects each flagged replacement, redacts or dismisses red-team clues, and selects text to redact what the agent missed; decisions are saved with who and when, undecided items stay replaced, and an export writes the reviewed notes and a review log. Tried by hand on the 5-note audit; 182 tests pass. Not used on a live agent run; one reviewer only.
- Day 6 (Oct 29): adversarial test set `deid/synth/adversarial.py` (docs/ADVERSARIAL.md): 180 short notes in nine families, 540 spans, kept separate from the frozen dataset (`data/adversarial.json`, guarded by `tests/test_adversarial.py`). Baselines scored on it (`results/adversarial/`, type-agnostic recall): Philter 96.3% (0.78 false positives per note), Presidio 86.5% (1.16), regex 14.4% (0.00); Presidio misses 22.5% of names that are common words. No model run on it yet; treat it as a test set (no tuning).
- Day 6 (Oct 29): comparison script `deid.eval.compare` (docs/COMPARISON.md): systems on identical notes, recall/precision/leak with bootstrap intervals, a paired recall difference against a reference system, tokens per note, latency, and cost only when a price is supplied. Tested offline with fake predictions and logs. No open-weights run yet (no partner endpoint or key) and no per-token prices.
