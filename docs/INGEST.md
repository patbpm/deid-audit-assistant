# Dictated and scanned notes

Status: Day 6, built and tested offline against mocked services. **No live Muse Voice Transcribe or vision call has been made, so there are no accuracy numbers.** The API shapes come from Meta's documentation (read Oct 29, 2026) and may differ in practice until a first live run. This is an assistant for human review, not a compliance certification.

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

- Untested against the real services: field names, the response shape, `PUSH_TO_TALK` behavior on a long file, and how the vision model handles the scan damage are all assumptions from the docs.
- Two hosted services see these files; synthetic data only.
- Handwriting, tables, multi-page documents, other audio formats and languages other than English are not covered.
