"""Where notes come from. A source answers one question: what notes exist right now?

    snapshot() -> {note_id: {"patient_id", "text"}}  (plus .skipped: {note_id: reason})

The watcher compares snapshots, so a new note, an edited note and a deleted note are all found the same
way, whatever the source. Sources only read; they never write to the place the notes live. Two are built
in: a folder (.txt files, one note each; .jsonl files, one note per line) and a SQLite table. Another source
is a class with a snapshot() method. Real clinical systems are out of scope here: this project only handles
synthetic data, and a deployment that read a real record system would need its own approvals first.
"""

import contextlib
import json
import re
import sqlite3
import time
from pathlib import Path

MAX_NOTE_BYTES = 2_000_000
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
SAFE_ID = re.compile(r"[^A-Za-z0-9._-]+")


class FolderSource:
    """*.txt (one note; the patient is the folder it sits in, else the part of the name before '__', else
    the note itself) and *.jsonl (one JSON object per line with note_id, patient_id and text; a later line
    with the same note_id replaces an earlier one). A file touched in the last `settle` seconds is skipped
    this time, so a file still being written is not read half done."""

    def __init__(self, path, settle=1.0):
        self.path, self.settle = Path(path), settle
        self.skipped, self.incomplete = {}, False

    def snapshot(self):
        notes, self.skipped, self.incomplete = {}, {}, False
        if not self.path.is_dir():
            return notes
        now = time.time()
        for f in sorted(self.path.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in (".txt", ".jsonl"):
                continue
            rel = f.relative_to(self.path)
            if now - f.stat().st_mtime < self.settle:
                self.skipped[rel.as_posix()] = "still being written"
                self.incomplete = True  # this file may be an edit of a note we know: not a deletion
                continue
            if f.stat().st_size > MAX_NOTE_BYTES:
                self.skipped[rel.as_posix()] = "file is larger than 2 MB"
                continue
            try:
                text = f.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError) as err:
                self.skipped[rel.as_posix()] = f"could not be read as UTF-8 text ({err})"
                continue
            if f.suffix.lower() == ".txt":
                note_id = clean_id("__".join(rel.with_suffix("").parts))
                patient = rel.parts[0] if len(rel.parts) > 1 else (f.stem.split("__")[0] if "__" in f.stem else note_id)
                notes[note_id] = {"patient_id": clean_id(patient), "text": text}
            else:
                self._lines(rel, text, notes)
        return notes

    def _lines(self, rel, text, notes):
        for n, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                note_id, body = clean_id(str(row["note_id"])), row["text"]
                if not isinstance(body, str):
                    raise TypeError("text is not a string")
                notes[note_id] = {"patient_id": clean_id(str(row.get("patient_id") or note_id)), "text": body}
            except (ValueError, KeyError, TypeError) as err:
                self.skipped[f"{rel.as_posix()} line {n}"] = f"not a note ({err})"


class SqliteSource:
    """One table: an id column, a text column and (optionally) a patient column. Opened read-only."""

    def __init__(self, path, table, id_col="note_id", text_col="text", patient_col="patient_id"):
        for name in (table, id_col, text_col, patient_col):
            if name and not NAME.fullmatch(name):
                raise ValueError(f"not a plain table or column name: {name!r}")
        self.path, self.table = Path(path), table
        self.id_col, self.text_col, self.patient_col = id_col, text_col, patient_col
        self.skipped = {}

    def snapshot(self):
        self.skipped = {}
        if not self.path.is_file():
            return {}
        uri = f"file:{self.path.resolve().as_posix()}?mode=ro"
        with contextlib.closing(sqlite3.connect(uri, uri=True)) as db:
            patient = self.patient_col or self.id_col
            rows = db.execute(f"SELECT {self.id_col}, {patient}, {self.text_col} FROM {self.table}").fetchall()
        notes = {}
        for note_id, patient_id, text in rows:
            if not isinstance(text, str):
                self.skipped[str(note_id)] = "text is not a string"
                continue
            notes[clean_id(str(note_id))] = {"patient_id": clean_id(str(patient_id)), "text": text}
        return notes


def clean_id(value):
    """An id that is safe as a file name."""
    return SAFE_ID.sub("_", value).strip("._-")[:80] or "note"


def parse_source(spec):
    """'folder:PATH' or 'sqlite:PATH#TABLE[:id_col:text_col:patient_col]'."""
    kind, _, rest = spec.partition(":")
    if kind == "folder" and rest:
        return FolderSource(rest)
    if kind == "sqlite" and "#" in rest:
        path, _, table = rest.partition("#")
        table, *columns = table.split(":")
        return SqliteSource(path, table, *columns[:3])
    raise ValueError("a source is folder:PATH or sqlite:PATH#TABLE[:id_col:text_col:patient_col]")
