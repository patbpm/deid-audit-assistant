# The front page (`deid.app`)

One local page in front of everything else: add input, watch it run, check the plan (tables), review (notes), download.

```powershell
python -m deid.app --open                 # offline rules, no model, nothing sent anywhere
python -m deid.app --live --open          # hosted models (Meta Model API); synthetic data only
```

Listens on `127.0.0.1:8780` only (`--port` to change). Jobs are kept in `runs/app/<id>/` (git-ignored). Those folders hold the original text, so they are as sensitive as the input: synthetic data only. "Delete this job" on the page removes the folder.

## What a person does

1. **Add input.** Drop files, choose files, paste text, or load a sample (invented notes, or two invented linked tables). The page shows what each file was taken to be and why a file was refused. A text file can be switched between "note" and "table".
2. **Check the options** that apply, then start. Notes: whether they are all about one patient. Tables: header row, what to do with columns the tool cannot place, how to handle free-text columns. Hosted mode: a required tick that the content is synthetic or public, and a token cap for the job.
3. **Watch the steps.** Each step shows its state and a count (notes done, tokens used against the cap).
4. **Tables only: check the plan.** Nothing has been changed yet. Every column is listed with the type the tool chose, why, and its first three original values. Change any type, pick the key column that links tables, then clean. Columns left as "UNKNOWN" are left out of the output.
5. **Review (notes).** "Open the review" opens the existing review page for that job: accept or reject each flagged change, redact clues, select text to redact what was missed. Anything left undecided stays replaced.
6. **Download.** The files are listed with what each holds (see below).

## What it accepts

| Input | Taken as | Notes |
|---|---|---|
| `.txt`, pasted text | one note | |
| `.jsonl` / `.json` lines `{"text", "note_id"?, "patient_id"?}` | many notes | `patient_id` keeps a patient's dates and names consistent |
| `.csv`, or pasted rows with a steady column count | a table | a `.txt` that looks like a table is guessed to be one and says so |
| `.wav` (mono, 16-bit, 16 or 24 kHz, at most 10 minutes) | dictation, then a note | needs `--live` |
| `.png` `.jpg` `.gif` `.webp` | a scanned page, then a note | needs `--live` |
| `.pdf`, `.docx`, `.xlsx`, `.tsv`, `.mp3`, `.m4a` | refused, with the way forward | |

The kind is decided from the bytes, not only the name. One job holds notes (text, dictation, scans) or tables, not both: they are cleaned differently, so a mixed upload is refused with that reason.

## The two engines

**Offline rules** (default, `deid/app/offline.py`). Patterns for emails, phones, dates, labeled numbers and street addresses, and names that follow a cue (`Dr. Wu`, `Patient: Kim Reyes`, `Kim Reyes, MD`), then every other place those names appear. It runs the same pipeline as the hosted engine (replace, audit, review) but there is no verifier and no re-identification reviewer, so risk is shown as "not assessed". **It misses any name that has no cue**: in the sample notes, a first name in "Lives with Kenneth" is not found. Few or no review items therefore does not mean a note is clean, and the results page says so. The patterns were written by someone who had already seen the project's synthetic note formats; **no accuracy is claimed for this engine, and it has not been scored on the held-out set.** It exists so the front page can be used and tested without a model.

**Hosted** (`--live`). The detector, verifier and red-team reviewer of the agent (`docs/AGENT.md`), plus dictation and scan reading (`docs/INGEST.md`), and, for tables, the optional model help for unplaced columns and for free-text cells (`docs/TABLES.md`). Everything added is sent to the provider. Nothing is sent until a job is started, a job will not start without the "synthetic or public" tick, and the job stops at its token cap. It was run once from the page on the two built-in samples (below). Dictation and scans have not been run from the page.

## Live check (Oct 29)

The page was started with `--live` and each sample run once with a 100,000-token cap (`results/dev/app-live-check.json`). Synthetic data from the project's generators, `muse-spark-1.3`.

| | Offline rules | Hosted model |
|---|---|---|
| Sample notes (4 notes of one patient): replacements | 63 | 64 |
| items left for a person to review | 7 | 2 |
| re-identification risk | not assessed | low for all 4 (a model's rating, not a guarantee) |
| true identifiers still present verbatim in the cleaned text | not checked | 0 of 64 |
| a first name with no cue ("Lives with ...") | missed | found |

- **Tables, with model help for columns and the detector on free text:** the model placed the 4 columns the rules could not (a town, an age, a length of stay, an amount), the rules confirmed each, and none of the original values I looked for remained in the cleaned tables (exact-string check of ids, SSNs, phones, emails, street, town, coverage ids and name parts). All 41 free-text comments were cleaned, none left masked. Because the model typed the length of stay and the amount as safe, the small-group check now counts them, and every encounter row falls in a group under 5.
- **Size:** about 28,000 tokens for the tables and 23,000 for the notes, roughly 0.17 USD at list price in total.
- **Bugs this run exposed, fixed:** the tables page said "with your changes" when nothing was changed; it gave no progress during the long free-text step; and it left the 2,017 tokens spent on column typing out of the job's total.
- **Not a result:** four notes and two small tables of easy synthetic text, one run, an exact-string leak check. It shows the page works end to end with the hosted engine, not how accurate it is.

## What is kept, and what is offered

In `runs/app/<id>/`: `input/` (your files), `job.json`, and for notes `notes.audit.json`, `notes.audit.html`, `notes.key.json`, the review decisions beside the audit; for tables `plan.json` and `tables-out/` (cleaned CSVs, `changes.jsonl`, `key.json`, `plan.json`, `report.json`, `risk.json`, `risk-rows.csv`).

Downloads are chosen from a list the server builds for the finished job; no part of a URL is used as a file path.

| File | Holds |
|---|---|
| cleaned notes / tables, zip packages | cleaned text with your decisions applied. **Can still contain identifiers the tool missed: check before sharing.** |
| `review-log.json` | decisions and counts, no note text |
| `plan.json`, `report.json`, `risk.json` | how columns were treated, counts, the small-group check; no cell values |
| `risk-rows.csv` | rows in small groups, cleaned values only |
| `audit-report.html` | **the original identifiers**, with every change and its evidence. Offered on its own, labeled. |

The key (`notes.key.json`, `key.json`) and the table change log (`changes.jsonl`) can undo the replacement. They stay in the job folder and are not offered for download.

## Safety of the page itself

Binds to `127.0.0.1`; refuses any Host header that is not the local address (DNS rebinding); every change needs a custom header, so another website cannot post to it; uploads are the raw request body, one file per request, with size limits (50 MB a file, 250 MB and 200 files a job); the page builds its DOM with `textContent` (no `innerHTML`) and loads nothing from outside; job ids are random 12-digit hex and are validated before any path is built; file names are reduced to a safe base name and stored under a counter. Tested in `tests/test_app.py`, including attempts to download `job.json`, the key and the audit data by name.

## Not done

- No sign-in or per-user separation: anyone who can reach `127.0.0.1:8780` on this computer can see every job. Do not run it on a shared machine.
- Table cells flagged for review (41 in the sample) are counted but there is no cell-by-cell review page; `changes.jsonl` on disk lists them.
- The review page decisions are recorded under one reviewer name (`--reviewer`).
- A cancelled or restarted app marks a running job as failed; there is no resume.
- Tested on Windows with Python 3.14 only.
