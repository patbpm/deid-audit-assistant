# Clinical text de-identification and audit agent

**Status: in progress (hackathon build, Oct 26 - Nov 4, 2026).** The parts below are built and tested; model-based results so far come from 5-note smoke tests only. Nothing here has been measured on real text.

A privacy-first assistant for human-reviewed de-identification of clinical free text, built for the Meta Global AI Developer Hackathon (indie track).

**This is an assistant for human review, not a compliance certification.** It does not guarantee removal of every identifier, gives no medical advice, and must not be used on real patient data. All development and evaluation use synthetic data only, and the hosted model services only ever see synthetic text.

## What it does

```
note ──► detect (Muse Spark) ──► verify uncertain spans ──► replace ──► red-team review ──┐
                                                                  ▲                      │
                                                                  └── leftovers sent back ◄┘
                                          ──► audit report with evidence trace ──► human review page ──► reviewed notes
```

- **Detect** names, dates, IDs, phones, emails and addresses with a hosted model (OpenAI-style endpoint, so the model is swappable).
- **Verify** the spans the detector was unsure about with a second model call. The verifier can confirm a span or raise doubt, but never removes one.
- **Replace** consistently: one date shift per patient so intervals are kept, one fake name per real name token across a patient's notes, same-shape IDs, fictional phones and emails. Anything it cannot rewrite safely becomes a tag and is flagged.
- **Red-team** review: a second model reads the cleaned note (replaced spans shown as tags) and reports leftover identifiers and clues such as a rare condition or a small place, with a risk level. A risk signal, not a guarantee. Leftover identifiers go back for another pass; other clues go to a person.
- **Audit report**: every change links to its character offsets, detector, confidence, the verifier's verdict and the rule that rewrote it. One self-contained HTML page.
- **Review page**: a local page where a person accepts or rejects each flag, redacts clues, and selects text to redact what the agent missed. Anything left undecided stays replaced.

## Status of each part

| Part | State |
|---|---|
| Synthetic note generator (600 notes, 9,015 labeled spans), frozen dev/test split | built, tested |
| Evaluation harness; regex, Presidio and Philter baselines | built, scored on the 400-note test split |
| Adversarial set (180 hard notes, nine families), baselines scored on it | built, scored |
| Detector with Muse Spark (Meta Model API) | live smoke test on 5 dev notes only |
| Replacement engine | checked on the dev split with true spans; not yet on a detector's full output |
| Red-team reviewer | live smoke test on 5 dev notes (15 probes) only |
| Verifier, feedback loop, agent pipeline | built, tested offline with a scripted model; **not run live** |
| Audit report, review page | built, tested offline and tried by hand |
| Review-burden curve (recall against spans reviewed) | built and tested offline (`docs/BURDEN.md`); not yet run on a full model output |
| Muse Spark Open on partner inference (comparison) | comparison script built and tested offline (`docs/COMPARISON.md`); no run yet, needs a partner endpoint |
| Full dev and test evaluation of the model-based system | not run |

## Results so far

All numbers are on synthetic notes and come from files in `results/`, reproducible with the commands in `docs/`.

**Baselines on the test split** (400 notes; type-agnostic overlap; full tables, intervals and caveats in `docs/RESULTS.md`):

| System | Recall % | Precision % |
|---|---|---|
| Format-aware regex (written knowing the synthetic formats) | 54.0 | 100.0 |
| Presidio, default settings | 94.7 | 74.3 |
| Philter, through a compatibility shim | 100.0 | 86.4 |

**Baselines on the adversarial set** (180 notes, not tuned on; `docs/ADVERSARIAL.md`):

| System | Recall % | False positives per note |
|---|---|---|
| Philter | 96.3 | 0.78 |
| Presidio | 86.5 | 1.16 |
| Regex | 14.4 | 0.00 |

**Smoke tests with `muse-spark-1.3`** (5 dev notes each, easy synthetic text):
- Detector: all 83 identifiers found, no false positives, no unreadable replies (`results/dev/meta-first5-dev.json`). This shows the pipeline works, not how accurate the model is.
- Red-team, on 15 probe notes built from those 5 notes (`results/dev/redteam-first5-dev.json`): 0 of 5 control notes flagged, 5 of 5 planted clues flagged and quoted, 10 of 10 withheld identifiers found. The probes are blunt and invented by us, and 5 notes give very wide intervals.

**Replacement check** (dev split, true spans, 200 notes): no original names, IDs, phones, emails or addresses left, one date shift per patient, no inconsistent or colliding name surrogates (`results/dev/replace-dev.json`). Because true spans were given, this shows the replacement step is sound, not that the pipeline is. Known weak spot: 3 of 46 year-less dates came out a day off across a leap day.

**Not measured yet:** the model-based system on the full dev or test split, the adversarial set, end-to-end leakage after replacement, the open-weights comparison, cost, and the effect of the feedback loop.

## Limits

- The synthetic data is template-based with easy fixed formats; scores will not predict performance on real notes.
- The model sees only synthetic text. Nothing here has been checked against real clinical text, and no claim is made that it is safe for it.
- The red-team and verifier prompts have not met a real model beyond the smoke tests.
- The replacement engine blurs season and weekday, does not aggregate ages of 90 or over, and cannot protect identifying detail in prose beyond what the red-team flags.
- The key and audit files contain original identifiers; they must never be shared with the cleaned notes.
- The code has not been tested as a local or on-premises deployment, so it is not described as running locally.

## Models and inference

Model calls go to hosted inference, not to the developer's computer: Meta Model API (Muse Spark `muse-spark-1.3`) is the primary model, and Meta's open-weights Muse Spark Open is planned on partner inference for comparison. The client speaks the OpenAI-style chat endpoint, so the host can be swapped (`--provider custom`).

## Reproduce

Tested on Python 3.14.7 on Windows only; the frozen dataset hashes were produced there and other versions are untested.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt                 # baselines only; the rest uses the standard library
python -m spacy download en_core_web_lg         # for the Presidio baseline

python -m deid.synth.generate                   # synthetic notes -> data/generated/ (git-ignored)
python -m unittest discover -s tests            # includes checks that the frozen dataset hashes are unchanged
python -m deid.synth.adversarial                # adversarial set -> data/generated/adversarial/
python -m deid.eval.report                      # regenerate docs/RESULTS.md from results/
```

Every model-calling command is a dry run unless `--live` is passed, uses the dev split, and has a token cap:

```powershell
python -m deid.agent.run                        # describes the stages and sizes a run, calls nothing
python -m deid.agent.run --live --limit 5       # real calls; set MODEL_API_KEY first (see .env.example)
python -m deid.review.server --audit runs/<name>.audit.json --open   # review page, this computer only
```

Keys live in environment variables; never commit them. API calls can be billed, so confirm credits are applied first.

## Docs

`docs/DATASET.md` (data and labeling rules) · `docs/RESULTS.md` (baselines) · `docs/ADVERSARIAL.md` · `docs/COMPARISON.md` · `docs/BURDEN.md` · `docs/REPLACEMENT.md` · `docs/REDTEAM.md` · `docs/AGENT.md` · `docs/AUDIT.md` · `docs/REVIEW.md` · `docs/PLAN.md` (build plan and progress log).

## What was built during the hackathon

Setup files and a smoke-test script were created on Oct 26, 2026; all project code was written during the building period, Oct 27 - Nov 4. The commit history shows what was added when.
