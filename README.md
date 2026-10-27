# Clinical text de-identification and audit agent

**Status: in progress (hackathon build, Oct 26 - Nov 4, 2026). No results yet.**

A privacy-first, self-hostable assistant for human-reviewed de-identification of clinical free text. It is being built for the Meta Global AI Developer Hackathon (indie track).

**This is an assistant for human review, not a compliance certification.** It does not guarantee removal of every identifier and must not be used on real patient data. All development and evaluation use synthetic or public data only.

## How it works (planned; not all built yet)

- Finds identifiers (names, dates, IDs, contacts, locations) in free-text notes.
- Replaces them consistently, for example shifting dates while keeping the time between events, and using one pseudonym per real name across a patient's notes.
- Flags low-confidence spans for human review instead of guessing.
- A second "red-team" agent checks whether a cleaned note could still be traced back to a person, and reports a risk level (a signal, not a guarantee).
- Writes an audit report in which every change links to its evidence: the original span, the detector, its confidence, and the verifier's decision.
- Is evaluated on a public synthetic benchmark with reproducible runs, compared against Presidio and Philter and across models.

## Models and inference

Model calls go to hosted inference, not to the developer's computer:

- Meta Model API (Muse Spark) is the primary model.
- Meta's open-weights Muse Spark Open is run through partner inference and compared against the API.

The code uses an OpenAI-style endpoint so the model can be swapped, and the design aims to be self-hostable. It has not been tested as a local or on-premises deployment, so it should not be described as running locally.

## What was built during the hackathon

Setup files, a smoke-test script and planning notes were created on Oct 26, 2026. All project code is written during the building period, Oct 27 - Nov 4. Commit history shows what was added when.

## Setup (Windows, PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

Copy the variable names from `.env.example` into your environment and set values there. Never commit keys.

For the API smoke test set `MODEL_API_KEY`. The base URL (`https://api.meta.ai/v1`) and model (`muse-spark-1.3`) default to the values in Meta's docs; `META_API_BASE_URL` and `META_API_MODEL` override them. The local-model variables in `.env.example` are optional and are not used by the hackathon demo.

## Smoke test

```powershell
python scripts/hello.py api
```

This sends one short request to the configured model endpoint and uses synthetic text only. API calls can be billed, so confirm your credits are applied before running it.
