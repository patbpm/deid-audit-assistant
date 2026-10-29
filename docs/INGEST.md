# Dictated and scanned notes

Status: Day 6, built and tested offline, plus one live run on 5 dictated and 5 scanned dev notes (below). Both services worked as documented on that run. These are synthetic, clean test inputs, so the numbers say little about real recordings or paper. This is an assistant for human review, not a compliance certification.

Both inputs end as plain text, so the existing pipeline (detect, verify, replace, red-team, audit, review) cleans them unchanged. What is lost on the way is stated below.

```powershell
# 1. make synthetic test inputs from dev notes (offline; nothing leaves the computer)
python -m deid.ingest.make --limit 5                     # images, WAV files, truth.jsonl in data/generated/ingest (git-ignored)

# 2. dry run: checks every file against the service limits and sizes the run
python -m deid.ingest.run --audio data/generated/ingest/audio --images data/generated/ingest/images

# 3. live (needs the key; billed unless credits apply)
python -m deid.ingest.run --audio ... --images ... --truth data/generated/ingest/truth.jsonl --live --name ingest-first5 --max-audio-seconds 700 --audio-price-per-hour 0.18

# 4. clean the transcribed and read notes, then check what survived
python -m deid.agent.run --unlabeled --notes runs/ingest-first5.notes.jsonl --live --name agent-ingest-first5
python -m deid.ingest.fidelity --truth data/generated/ingest/truth.jsonl --ingested runs/ingest-first5.notes.jsonl --cleaned runs/agent-ingest-first5.notes.jsonl --name first5
```

## First live run (Oct 29)

Muse Voice Transcribe (`muse-voice-transcribe-1.0`, `PUSH_TO_TALK`) on 5 WAV files (595 s) and `muse-spark-1.3` with prompt `ocr1` on 5 page images; the 10 resulting notes were then cleaned with `deid.agent.run --unlabeled` and checked with `deid.ingest.fidelity` (`results/dev/ingest-first5.json`, `ingest-first5-run.json`, `agent-ingest-first5.json`).

| | Dictated (audio) | Scanned (vision) |
|---|---|---|
| Word error rate vs the script | 30.4% | 0.0% |
| Character error rate | 12.2% | 0.0% |
| True identifiers still readable in the text | 66 of 83 (names 30/37, IDs 7/9, phones 8/10, dates 21/21, addresses 0/4, emails 0/2) | 83 of 83 |
| Of those, still present after cleaning (names, IDs, phones) | 0 of 45 | 0 of 62 (names, IDs, phones, emails, addresses) |

Reading the table:
- **Scans were copied exactly.** The vision model reproduced all five synthetic pages character for character. The pages are clean, large, machine-printed text with a fraction of a degree of tilt; this says nothing about handwriting, bad scans or tables.
- **Dictation lost words.** The transcripts respell names (Larsen as Larson), repeat words ("physical. physical."), write a pain score as "7 tenths", and write addresses and emails in forms the string check does not match, so addresses and emails are not covered by the audio leak check at all. "Still readable" is a lower bound: a name or address word counts if a one-letter variant is present; IDs and phones count only if the digits are intact.
- **Nothing readable survived cleaning** among the identifiers the check can see. For audio that is 45 identifiers, not 83, so it is weaker evidence than the scan result.
- **Cost at list price:** audio $0.030 (595 s at $0.18 per hour); reading the scans 6,875 in and 11,064 out tokens, $0.056; cleaning the 10 notes 12,389 in and 50,674 out tokens in the final run, $0.231. The first, flawed cleaning attempt used 17,504 in and 63,901 out tokens ($0.29), so the whole experiment cost about $0.61, inside the credit.

### Harder inputs (Oct 29)

The same five notes made harder (`python -m deid.ingest.make --harder`, `deid/ingest/degrade.py`): background noise mixed into the audio at a 12 dB signal-to-noise ratio, scans tilted, blurred, shadowed, downscaled to 65% and saved as JPEG at quality 30, and one 431-second recording (7.2 minutes, 13.8 MB) of the first patient's four notes dictated back to back. Run live, cleaned by the agent and checked as before (`results/dev/ingest-noisy*.json`, `ingest-long*.json`, `agent-ingest-noisy.json`, `agent-ingest-long.json`):

| | Clean (first run) | Noisy audio, 12 dB | Long recording, 431 s | Clean scans | Rough scans |
|---|---|---|---|---|---|
| Word error rate | 30.4% | 30.7% | 29.8% | 0.0% | 0.1% |
| Character error rate | 12.2% | 11.2% | 11.5% | 0.0% | 0.0% |
| True identifiers still readable | 66 of 83 | 66 of 83 | 55 of 64 | 83 of 83 | 82 of 83 |
| Of those, still present after cleaning | 0 of 45 | 0 of 45 | 0 of 38 | 0 of 62 | 0 of 61 |

- **Neither harder condition changed much.** The noise level and the damage were mild enough that the speech and vision models handled them: the noisy audio scored the same as the clean, and the rough scans lost one digit of one id. The long recording was accepted by the endpoint (431 s of the 600 s limit) and transcribed in about 60 seconds.
- **The word error rate is inflated and nearly constant.** It is measured against the dictation script, and the transcripts write numbers and dates their own way ("7 tenths", "April 11th"), so a floor of around 30% comes from formatting as much as from mistakes. Read the changes between columns, not the level.
- **Still easy.** One synthetic voice, white noise, a clean font and no handwriting. Real recordings (accents, crosstalk, dictation habits) and real scans (handwriting, stamps, creases, photographs) would be much harder, and nothing here predicts them. Addresses and emails still cannot be checked in the audio.
- **Nothing was left uncleaned**: no failed notes in either run (the retry fix from the first run held).
- **Cost at list price:** noisy run about $0.03 audio, $0.05 reading the scans and $0.32 cleaning; long run $0.02 audio and $0.08 cleaning.

### What the live run exposed (and the fix)

The first cleaning attempt ran with the default 4,096-token output limit. For 5 of the 10 notes the model used the whole limit on reasoning, so the reply was cut off or empty. The pipeline then wrote those notes as "cleaned" with nothing replaced: a silent failure, and the worst kind for a de-identification tool. Fixes (commit `1b7da3f`, `tests/test_failclosed.py`):
- **Fail closed.** A note whose detection reply is unreadable or cut off is not written to the cleaned file. It is listed in `<name>.failed.json`, shown with a NOT CLEANED banner in the audit page and review page, counted in the summary, and withheld from the review export. It cannot be dismissed in the review page.
- **Retry once with a larger limit** (16,384 tokens), counting both attempts' tokens; incomplete replies are never cached or reused.
After the fix all 10 notes were cleaned with no unreadable replies; the feedback loop added 1 span.

## Dictated notes (`deid/ingest/audio.py`)

`POST https://api.meta.ai/v1/asr/transcribe`, multipart: a JSON `request` part (`model: muse-voice-transcribe-1.0`, `mode`, `audioEncoding: WAV`) and the `audio` part. The reply's `transcript` becomes the note text. Limits from the docs, checked before any request: WAV only, mono, 16-bit PCM, 16 or 24 kHz, at most 10 minutes and 32 MB. Retries on 429 and 5xx; transcripts are cached by audio hash so reruns cost nothing. The price in Meta's docs is $0.18 per hour of audio (not assumed in code; pass `--audio-price-per-hour`).

Realtime streaming (WebSocket) is not used. `--mode` can be `ENDPOINTING` or `DIARIZATION`; the default `PUSH_TO_TALK` is the one the docs show, and how it treats a whole file as one turn is untested.

## Scanned notes (`deid/ingest/vision.py`)

The page image goes to `muse-spark-1.3` through chat completions as a base64 data URL, with a prompt (`ocr1`) that asks for a character-for-character copy with `[illegible]` for unreadable text. PNG, JPEG, GIF and WebP up to 50 MB. A truncated reply is flagged. Reading mistakes are not corrected; they show up as errors in the text.

## What changes downstream

- **No offsets into the original.** Redaction works on the text; there are no character offsets on the audio or the image, and the audit says nothing about where in the recording or on the page an identifier was.
- **Spoken numbers, dates and emails can come back in any written form** ("six one six seven", "6167853", "April 11th"). The detector sees whatever the transcript says; the replacement engine falls back to a flagged tag for a date it cannot parse.
- **A transcription or reading error can drop or alter an identifier before the detector sees it.** The fidelity check separates those misses (recovery) from de-identification misses (what survives cleaning).
- **Speaker labels** from `DIARIZATION` are not used.
- **Audio and images may carry identifiers that text does not** (a voice, a handwritten header, a logo). Only the transcribed text is cleaned; the original file is untouched and is as sensitive as the note.

## Test data (`deid.ingest.make`)

- **Scans**: the note text drawn in a monospace font on a page (Pillow), with a slight rotation, blur and speckle chosen from a seed.
- **Audio**: a dictation script (`dictation.py`: IDs and phones digit by digit, dates as month day and year, emails with "at" and "dot") spoken offline by a Windows voice (System.Speech) to a 16 kHz mono WAV. The five dev notes used so far come to about 10 minutes of audio.
- Both are far cleaner than real recordings and scans: a synthetic voice, no noise, no accent, no handwriting, no skew beyond a fraction of a degree. A good score here says little about real dictation or real paper.

## The fidelity check (`deid.ingest.fidelity`)

String-level, per source: word error rate (audio, against the script) and character error rate (scans, against the page text); identifier recovery by type; and with `--cleaned`, how many recovered identifiers are still present after cleaning (names, IDs, phones, emails, addresses; dates are covered by the replacement check). A surname that is also a common word can show as a false leak, so leakage is an upper bound and recovery a lower bound.

## Limits

- Confirmed on one live run: the endpoint, field names, response shape and `PUSH_TO_TALK` on files up to 164 s. Not tested: files near the 10 minute limit, other modes, noisy audio, accents, handwriting, or damaged scans.
- Two hosted services see these files; synthetic data only.
- Handwriting, tables, multi-page documents, other audio formats and languages other than English are not covered.
