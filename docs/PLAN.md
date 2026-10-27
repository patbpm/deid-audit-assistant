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
- Day 3 (Oct 27, started early; in progress): evaluation harness built (`deid/eval/`): per-type recall first, then precision, exact and overlap views, leaked-character rate, 95% bootstrap intervals over notes. Dev/test split fixed by patient: P0001-P0050 dev, P0051-P0150 test (400 test notes). Format-aware regex baseline scored on test: overall overlap recall 54.0% (NAME 0%, DATE 93.5%, ADDRESS 80.7%, ID/PHONE/EMAIL 100%), precision 100%; this mostly shows how easy the synthetic formats are (see docs/DATASET.md). Presidio and Philter baselines not run yet.
