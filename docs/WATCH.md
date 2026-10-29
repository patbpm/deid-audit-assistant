# Watch mode

Status: built and tested offline with a scripted model, and tried by hand on synthetic notes with the offline rules (Oct 29). **Not run with a hosted model.** Synthetic data only. This is an assistant for human review, not a compliance certification, and it is not connected to any real record system.

## What it does

`python -m deid.watch` looks at a source of notes every few seconds and keeps a cleaned copy of each note up to date:

- a **new** note is detected, replaced and reviewed by the same pipeline as a batch run (detect, name check, verify, replace, red-team, audit);
- an **edited** note (its text changed) is cleaned again; its earlier cleaned copy is withdrawn and the earlier review decisions about it are dropped, because they were about text that no longer exists;
- a **removed** note's cleaned copy, audit and decisions are deleted;
- an unchanged note is never sent to the model again.

Nothing waits for "enough data": each note is cleaned on its own, as it arrives.

## Held until reviewed

A cleaned note is written to `released/` only when nothing in its review queue is undecided. Notes with flagged spans, review clues, or a notice stay held; a note that could not be cleaned is never released. With the offline rules engine (no verifier, no second reader) every note carries a notice that a person must dismiss first, because an empty queue proves nothing from an engine that only finds names after a cue such as `Dr.` or `Patient:`. A person decides in the usual review page, opened on the watcher's audit file with `--follow` so new and changed notes appear while it is open:

```powershell
python -m deid.synth.generate                                              # once, to make data/generated/notes.jsonl
python -m deid.watch.feed --out runs/demo-feed --count 8 --interval 4      # drips synthetic notes into a folder (edits one, deletes one)
python -m deid.watch --source folder:runs/demo-feed --state runs/watch/demo # the watcher (offline rules)
python -m deid.review.server --audit runs/watch/demo/audit.json --follow --open
# status page (ids and states only, never note text): runs/watch/demo/status.html
```

With a hosted model: add `--live --synthetic-only --max-total-tokens 200000` (the flag confirms every note is synthetic; the cap stops new notes when reached and the watcher pauses).

## Sources

`folder:PATH` reads `.txt` files (one note each; the patient is the folder the file sits in, else the part of the name before `__`) and `.jsonl` files (one note per line; a later line with the same `note_id` replaces an earlier one). `sqlite:PATH#TABLE[:id_col:text_col:patient_col]` reads one table, opened read-only. Sources only read. Another source is a class with a `snapshot()` method returning `{note_id: {"patient_id", "text"}}`. A file touched in the last second is not read yet and, while one is busy, deletions are not acted on.

## One patient, the same stand-ins, over time

The replacement mapping (stand-in names, ID mappings, per-patient date shifts) is kept in `mapping.json`, so a patient's stand-in name and date shift are the same in a note that arrives next month, even after the watcher is restarted. A secret random seed is made on first use and kept there. Nothing already decided is changed when new notes arrive (`Replacer.extend`). If a real name in a new note equals a stand-in already given to someone else (it cannot be taken back), that note gets a notice.

## What is sensitive

`mapping.json`, `audits/` and `audit.json` contain original identifiers and the key that reverses the cleaning; they stay under `runs/` (git-ignored). `released/`, `events.jsonl` and `status.html` do not contain original note text, but `released/` has only passed review if a person did the review. Never share the state folder.

## Limits

- Polling, not push: a note is picked up within one interval (default 5 seconds).
- Deleting a note removes its cleaned copy, audit and decisions, but the mapping keeps the name-to-stand-in link so the same person stays consistent if they return. Deleting `mapping.json` forgets all of it (and the next run starts a new mapping).
- A real name that equals an earlier stand-in is reported, not undone.
- Review is single-user, local, last write wins.
- Not connected to any record system; a real deployment would need its own approvals, a self-hosted model so notes never reach a third party (self-hostable is not claimed until tested), and an access-controlled state folder.
- Streaming de-identification exists in other tools; this is not claimed to be new.

## Tests

`tests/test_watch.py` (scripted model): new, edited, removed and unchanged notes; held until decided and released after; a failed note never released; model errors retried three times; the token cap pausing and resuming; stand-ins the same across notes and a restart; the status page never holding note text and escaping; the review store following a rewritten audit and keeping decisions for unchanged notes; folder, jsonl and SQLite sources; the demo feeder; the offline-engine hold.
