# Clinical text de-identification and audit assistant

An open-source assistant that finds and replaces identifiers in clinical free text with Meta's Muse Spark, shows the evidence for every change, and leaves the doubtful calls to a person. Built for the Meta Global AI Developer Hackathon (indie track, "Build for Your World"), Oct 27 - Nov 4, 2026.

**This is an assistant for human review, not a compliance certification.** It does not guarantee removal of every identifier, gives no medical advice, and must not be used on real patient data. All development and evaluation use synthetic data only, and the hosted model services only ever see synthetic text. Nothing here has been checked on real clinical text.

[Demo video (3 min): link added at submission] · Write-up: `docs/SUBMISSION.md` · Evidence for every number: `docs/EVIDENCE.md`

## The problem

Notes cannot be shared for research until names, dates, IDs and contact details are removed, and tools get it wrong in both directions. A name can also be an ordinary word: in "Patient: Sage Fair ... Fair skin ... Sage tea ... Ms. Fair", only the first and last "Fair" are the person. Replace every match and the clinical content is damaged; skip common words and a real name stays. Either way the reviewer gets no evidence of what changed or why.

## What it does

```
note ──► detect ──► verify doubtful spans ──► check name uses ──► replace ──► red-team review ──┐
          (Muse Spark, each its own role)                            ▲                          │
                                                                     └── leftovers sent back ◄──┘
                                   ──► audit report with evidence trace ──► human review page ──► reviewed notes
```

- **Detect** names, dates, IDs, phones, emails and addresses with a hosted model (OpenAI-style endpoint, so the model is swappable).
- **Verify** the spans the detector was unsure about with a second call. The verifier can confirm a span or raise doubt, but never removes one.
- **Check name uses**: when a name is also an ordinary word, a narrow call reads each doubtful occurrence in context. Only a clear "ordinary word" answer leaves text as written; failure, truncation or doubt keeps the name replaced, and a person can choose "Replace it after all".
- **Replace** consistently: one date shift per patient so intervals are kept, one fake name per real name token across a patient's notes, same-shape IDs, fictional phones and emails. Anything it cannot rewrite safely becomes a tag and is flagged.
- **Red-team**: a second agent reads the cleaned note (replaced spans shown as tags) and reports leftover identifiers and clues such as a rare condition or a small place, with a risk level. A risk signal, not a guarantee. Leftover identifiers go back for another pass; other clues go to a person.
- **Audit report**: every change links to its character offsets, detector, confidence, the verifier's verdict and the rule that rewrote it. One self-contained HTML page.
- **Review page**: a local page where a person accepts or rejects each flag, redacts clues, and selects text to redact what the agent missed. Anything left undecided stays replaced.
- **Also built**: a front page for notes, CSV tables, dictation and scans; watch mode (notes cleaned as they arrive in a folder or SQLite table, re-cleaned when the original changes); a two-model cross-check; a review-burden curve.

## Results (all synthetic notes; one run each; details and caveats in `docs/EVIDENCE.md`)

**Hard cases, adversarial set B** (200 short notes, 609 labeled identifiers, written by the project: common-word names, 21 real surnames written bare, odd dates, typos, eponyms, relative dates). The pass test was written before the run.

| System | Identifiers covered | False positives per note |
|---|---|---|
| Philter | 95.9% | 0.83 |
| Presidio, default settings | 83.6% | 1.55 |
| Regex | 14.0% | 0.00 |
| Muse Spark agent (detection stage) | 609 of 609 | 0.005 (1 in total) |
| Muse Spark agent (final output, after the red-team fix) | 609 of 609 | 0.005 (1 in total) |

About 2.74 USD at list price (an estimate). The first run of the final stage had 7 false positives because my date fix made the red-team reviewer re-add year-only dates; fixing that stage took it to 1, and that row was fixed after reading set B's errors, so it is a tuned row. The 108 false positives that the first adversarial set (set A) exposed, and the two fixes that followed, are in `docs/ADVERSARIAL.md`; set A is now a tuned set.

**Easy template notes** (200 dev notes, the split the prompts were tuned on, so no held-out claim): 3,023 of 3,023 identifiers found with no false positives, and none left word for word. This shows no regression, not accuracy.

**Baselines on 400 held-out synthetic notes** (regex written knowing the synthetic formats): recall / precision regex 54.0 / 100.0, Presidio 94.7 / 74.3, Philter 100.0 / 86.4 (`docs/RESULTS.md`).

**Not measured:** the model-based system on the 400-note test split (not run, by decision); Muse Spark Open or any open-weights model (a comparison was planned and **not run**); the two-model cross-check with a real second model; watch mode with a hosted model; any real clinical text; any reviewer other than the developer. The cross-check and watch mode are built and pass their tests with scripted models only.

## How it uses Meta's models

- **Muse Spark (`muse-spark-1.3`) through the Meta Model API** in four separate roles with their own prompts and fail-closed behavior: detector, verifier, name-use check and re-identification red-team. The same model reads scanned pages and, optionally, types unlabeled table columns and cleans free-text cells.
- **Muse Voice Transcribe** turns dictation into notes that go through the same pipeline (30% word error on synthetic speech; names get respelled, so cleaning the transcript is what matters).
- The client speaks an OpenAI-style endpoint (`--provider custom`), so a partner-hosted open-weights model could be tried; that has not been done.

## Using it

```powershell
python -m deid.app --open          # a local page: drop files or paste text, watch it run, review, download
python -m deid.app --live --open   # same, with the hosted models (billed; synthetic data only)
```

Drop or paste notes (text or JSON lines) or CSV tables; with `--live`, also dictation (WAV) or scanned pages. By default the page uses an **offline rules engine with no AI model**, which is much weaker (it misses names that have no cue) and is there so the page can be used without a model; `--live` sends the content to the provider. See `docs/APP.md`. For the agent, review and watch commands see `docs/AGENT.md`, `docs/REVIEW.md` and `docs/WATCH.md`.

## Limits

- The synthetic data is template-based, short and easy; scores will not predict performance on real notes.
- Both adversarial sets were written by the project, with 20 notes or fewer per family, so intervals are wide; one run each, and the prompts and rules were changed after reading set A and the red-team stage after reading set B.
- The red-team's risk level is a model's opinion. The replacement engine blurs season and weekday, does not aggregate ages of 90 or over, and cannot protect identifying detail in prose beyond what the red-team flags.
- The key and audit files contain original identifiers; they must never be shared with the cleaned notes.
- Hosted inference only. The code has not been tested as a local or on-premises deployment, so it is not described as running locally or as self-hostable.
- No sign-in or per-user separation on the local pages; one reviewer at a time.

## Reproduce

Tested on Python 3.14.7 on Windows only; the frozen dataset hashes were produced there and other versions are untested.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt                 # baselines only; the rest uses the standard library
python -m spacy download en_core_web_lg         # for the Presidio baseline

python -m deid.synth.generate                   # synthetic notes -> data/generated/ (git-ignored)
python -m unittest discover -s tests            # includes checks that the frozen dataset hashes are unchanged
python -m deid.synth.adversarial --vocab b      # adversarial set B -> data/generated/adversarial-b/
python -m deid.eval.report                      # regenerate docs/RESULTS.md from results/
```

Every model-calling command is a dry run unless `--live` is passed, uses the dev split, and has a token cap:

```powershell
python -m deid.agent.run                        # describes the stages and sizes a run, calls nothing
python -m deid.agent.run --live --limit 5       # real calls; set MODEL_API_KEY first (see .env.example)
python -m deid.review.server --audit runs/<name>.audit.json --open   # review page, this computer only
```

The exact command behind each number is in `docs/CLAIMS.md`. Keys live in environment variables; never commit them. API calls can be billed, so confirm credits are applied first.

## Docs

`docs/EVIDENCE.md` (every result) · `docs/ADVERSARIAL.md` · `docs/RESULTS.md` (baselines) · `docs/DATASET.md` · `docs/AGENT.md` · `docs/REDTEAM.md` · `docs/REPLACEMENT.md` · `docs/AUDIT.md` · `docs/REVIEW.md` · `docs/APP.md` · `docs/WATCH.md` · `docs/CROSSCHECK.md` · `docs/BURDEN.md` · `docs/INGEST.md` · `docs/TABLES.md` · `docs/COMPARISON.md` · `docs/CLAIMS.md` (claims ledger) · `docs/SUBMISSION.md` · `docs/DEMO_SCRIPT.md` · `docs/PLAN.md` (build log).

## What was built during the hackathon

Setup files and a smoke-test script were created on Oct 26, 2026; all project code was written during the building period, Oct 27 - Nov 4. No earlier code was imported, and no real patient data or data from any research project was used. The commit history shows what was added when. Solo project.
