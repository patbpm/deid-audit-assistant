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

## Using it

```powershell
python -m deid.app --open          # a local page: drop files or paste text, watch it run, review, download
```

Drop or paste notes (text or JSON lines), CSV tables, and, with `--live`, dictation (WAV) or scanned pages. The page says what each input was taken to be, shows progress, lets you check and edit the column plan for tables, opens the review page for notes, and offers the downloads, each labeled with what it holds (`docs/APP.md`). By default it uses an **offline rules engine with no AI model**, which is much weaker (it misses names that have no cue) and is there so the page can be used without a model; `--live` uses the hosted models and sends the content to the provider, so synthetic data only.

## Status of each part

| Part | State |
|---|---|
| Synthetic note generator (600 notes, 9,015 labeled spans), frozen dev/test split | built, tested |
| Evaluation harness; regex, Presidio and Philter baselines | built, scored on the 400-note test split |
| Adversarial set (180 hard notes, nine families), baselines scored on it | built, scored |
| Detector with Muse Spark (Meta Model API) | run on all 200 dev notes: all 3,023 labeled identifiers found with exact boundaries, no false positives, no unreadable or cut-off replies. Easy template text on the split the prompt was tuned on; not a held-out result. Test split and adversarial set not run yet |
| Replacement engine | checked on the dev split with true spans; not yet on a detector's full output |
| Red-team reviewer | live smoke test on 5 dev notes (15 probes); also run on all 200 dev notes, where it rated every note low and found nothing to send back |
| Verifier, feedback loop, agent pipeline | built; live run on all 200 dev notes completed in two sessions (verifier asked about 6 spans and confirmed them; red-team found no leftovers, so the feedback loop did nothing); the loop has only been tested with a scripted model. `--workers` runs notes in parallel with identical results |
| Audit report, review page | built, tested offline and tried by hand |
| Front page (`deid.app`): drop or paste input, auto-detect type, progress, table plan, review, downloads | built; tested offline with scripted models and by hand in a browser; run once with the hosted model on its two samples (`docs/APP.md`); dictation and scans not yet run from the page |
| Dictated notes (Muse Voice Transcribe) and scanned notes (vision model) as inputs | live run on 5 synthetic dictated and 5 synthetic scanned notes (`docs/INGEST.md`); clean synthetic inputs only |
| Table mode (CSV): column typing, per-column replacement with consistent mapping across tables, small-group screen | checked on invented tables only (`docs/TABLES.md`); rules alone by default; optional model help for unplaced columns and for free-text cells, each run once live |
| Review-burden curve (recall against spans reviewed) | built and tested offline (`docs/BURDEN.md`); not yet run on a full model output |
| Muse Spark Open on partner inference (comparison) | comparison script built and tested offline (`docs/COMPARISON.md`); no run yet, needs a partner endpoint |
| Evaluation of the model-based system | dev split done (detection and cleaning); test split and adversarial set not run |

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

**Full agent run with `muse-spark-1.3` on the 200 dev notes** (`results/dev/agent-meta-dev*.json`; easy synthetic text, the split the prompt was tuned on, so not a held-out result): all 3,023 labeled identifiers found with exact boundaries and the right type, no false positives (names 1,312, dates 850, phones 361, ids 319, addresses 150, emails 31). No reply was unreadable or cut off, and all 200 notes were cleaned. None of the 3,023 identifiers appears word for word in the cleaned notes. The verifier was asked about 6 spans and confirmed them. The red-team rated all 200 cleaned notes low risk and found no leftovers. 199 changes were flagged for a person, all of them dates whose day/month order or year had to be guessed. The review-burden curve is trivial here (6 candidates under 0.8 confidence, all true). About 1.07 million tokens in two sessions, roughly 3.6 USD at list price (an estimate; reasoning-token billing is not stated). Run in parallel (4 workers) the second session took about 4 minutes.

**Smoke tests with `muse-spark-1.3`** (5 dev notes each, easy synthetic text):
- Detector: all 83 identifiers found, no false positives, no unreadable replies (`results/dev/meta-first5-dev.json`). This shows the pipeline works, not how accurate the model is.
- Red-team, on 15 probe notes built from those 5 notes (`results/dev/redteam-first5-dev.json`): 0 of 5 control notes flagged, 5 of 5 planted clues flagged and quoted, 10 of 10 withheld identifiers found. The probes are blunt and invented by us, and 5 notes give very wide intervals.

**Agent run with `muse-spark-1.3`** (5 dev notes, `docs/AGENT.md`): all stages ran, no unreadable replies; the verifier confirmed the 2 low-confidence spans, the red-team rated all 5 notes low risk with no leftovers, and 83 of 83 identifiers were found. Detection reused cached replies from the smoke test. The red-team had nothing to catch, so this does not test the feedback loop.

**Dictated and scanned input** (5 synthetic dictated and 5 synthetic scanned dev notes, `docs/INGEST.md`): the vision model copied the pages exactly; the speech model's transcripts had a 30% word error rate and respelled many names; after cleaning, none of the identifiers the check could still find in the text remained (0 of 107). The first attempt exposed a failure where notes were written out uncleaned; they are now withheld and flagged. Clean synthetic inputs, no handwriting or noisy audio.

**Harder dictation and scans** (same 5 notes with 12 dB noise, tilted, blurred, compressed scans, and one 7-minute recording, `docs/INGEST.md`): word error rate unchanged at about 30% for audio (inflated by formatting), 0.1% for scans; none of the identifiers still readable after transcription survived cleaning. Still synthetic and mild.

**Table mode** (60 invented patients and 121 encounters in two linked CSV tables, `docs/TABLES.md`): with plain headers every column was typed right; with differently worded headers 18 of 24 were, and the 4 left unplaced were withheld rather than guessed; with no headers 15 of 24. With optional model help, confirmed by the rules, those rose to 22 and 21 of 24. Free-text comment cells cleaned by the model left none of 163 embedded identifiers. In all four header styles none of the 1,247 original identifiers remained, patient and MRN links between the two tables held, and each patient's dates moved by one offset. Invented, tidy tables: no claim for real ones. A separate screen flags rows in small groups of age, ZIP and diagnosis (all 60 invented patients are unique on ZIP code alone); it counts within the table, not the population, and changes nothing.

**Replacement check** (dev split, true spans, 200 notes): no original names, IDs, phones, emails or addresses left, one date shift per patient, no inconsistent or colliding name surrogates (`results/dev/replace-dev.json`). Because true spans were given, this shows the replacement step is sound, not that the pipeline is. Known weak spot: 3 of 46 year-less dates came out a day off across a leap day.

**Not measured yet:** the model-based system on the test split and the adversarial set, the open-weights comparison, and the effect of the feedback loop (it had nothing to fix on dev). Cost so far is only an estimate at list price.

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
python -m deid.app --open                       # front page; offline rules unless --live (hosted, billed)
```

Keys live in environment variables; never commit them. API calls can be billed, so confirm credits are applied first.

## Docs

`docs/DATASET.md` (data and labeling rules) · `docs/RESULTS.md` (baselines) · `docs/ADVERSARIAL.md` · `docs/COMPARISON.md` · `docs/BURDEN.md` · `docs/INGEST.md` · `docs/TABLES.md` · `docs/APP.md` · `docs/REPLACEMENT.md` · `docs/REDTEAM.md` · `docs/AGENT.md` · `docs/AUDIT.md` · `docs/REVIEW.md` · `docs/PLAN.md` (build plan and progress log).

## What was built during the hackathon

Setup files and a smoke-test script were created on Oct 26, 2026; all project code was written during the building period, Oct 27 - Nov 4. The commit history shows what was added when.
