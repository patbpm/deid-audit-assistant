"""Decide what an uploaded file or pasted text is.

    kind_of_file("notes.csv", data)  -> Detected("table", "CSV table", ...)
    kind_of_text(text)               -> Detected("note", "pasted text", ...)

Four kinds: "note" (text, or JSON lines of notes), "table" (CSV), "audio" (WAV) and
"scan" (image). The kind comes from what the bytes are, not only from the file name,
and the page shows the guess so a person can see it. Anything else is refused with a
reason. Notes, audio and scans all end up as notes ("notes family"); tables are
cleaned a different way, so one job holds one family.
"""

import csv
import io
import json
from dataclasses import dataclass

NOTES_FAMILY = ("note", "audio", "scan")
MAX_TEXT_BYTES = 5_000_000
IMAGE_MAGIC = {b"\x89PNG\r\n\x1a\n": "png", b"\xff\xd8\xff": "jpg", b"GIF87a": "gif", b"GIF89a": "gif"}
UNSUPPORTED = {
    ".mp3": "MP3 audio is not accepted: convert it to a mono 16-bit WAV (16 or 24 kHz) first",
    ".m4a": "M4A audio is not accepted: convert it to a mono 16-bit WAV (16 or 24 kHz) first",
    ".pdf": "PDF files are not accepted yet: save each page as an image (PNG or JPG)",
    ".docx": "Word files are not accepted yet: paste the text or save it as .txt",
    ".xlsx": "Excel files are not accepted yet: save each sheet as CSV",
    ".xls": "Excel files are not accepted yet: save each sheet as CSV",
    ".tsv": "TSV files are not accepted yet: save the table as CSV",
}


@dataclass
class Detected:
    kind: str | None  # note, table, audio, scan; None when refused
    label: str
    reason: str = ""  # why it was refused, or what to know about the guess

    @property
    def ok(self):
        return self.kind is not None


def refuse(why):
    return Detected(None, "not supported", why)


def looks_like_table(text):
    """True when the text parses as CSV with a steady number of columns on every line."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return False
    try:
        rows = list(csv.reader(io.StringIO("\n".join(lines))))
    except csv.Error:
        return False
    width = len(rows[0])
    if width < 2:
        return False
    steady = sum(len(r) == width for r in rows)
    return steady / len(rows) >= 0.9 and sum(len(r) for r in rows) / len(rows) < 80


def notes_from_jsonl(text):
    """Notes from JSON lines {"note_id"?, "text", "patient_id"?}, or None when it is not that."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines or not all(ln.lstrip().startswith("{") for ln in lines):
        return None
    notes = []
    for number, line in enumerate(lines, 1):
        try:
            record = json.loads(line)
        except ValueError:
            return None
        if not isinstance(record, dict) or not isinstance(record.get("text"), str):
            return None
        notes.append(record)
    return notes


def decode(data):
    """Text from bytes (UTF-8, with or without a byte-order mark), or None."""
    if b"\x00" in data[:4096]:
        return None
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def kind_of_text(text):
    if not text.strip():
        return refuse("there is no text")
    if len(text.encode()) > MAX_TEXT_BYTES:
        return refuse(f"the text is larger than {MAX_TEXT_BYTES:,} bytes")
    if notes_from_jsonl(text) is not None:
        return Detected("note", "notes (JSON lines)")
    if looks_like_table(text):
        return Detected("table", "CSV table", "guessed from the shape: the same number of columns on every line")
    return Detected("note", "note text")


def kind_of_file(name, data):
    ext = ("." + name.rsplit(".", 1)[1].lower()) if "." in name else ""
    if ext in UNSUPPORTED:
        return refuse(UNSUPPORTED[ext])
    if not data:
        return refuse("the file is empty")
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return Detected("audio", "dictated audio (WAV)")
    if ext == ".wav":
        return refuse("this does not look like a WAV file")
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return Detected("scan", "scanned page (image)")
    for magic in IMAGE_MAGIC:
        if data.startswith(magic):
            return Detected("scan", "scanned page (image)")
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        return refuse("this does not look like an image of the type its name says")
    text = decode(data)
    if text is None:
        return refuse("this is not a text, CSV, WAV or image file")
    if len(data) > MAX_TEXT_BYTES:
        return refuse(f"the file is larger than {MAX_TEXT_BYTES:,} bytes")
    if not text.strip():
        return refuse("the file has no text")
    if ext == ".csv":
        return Detected("table", "CSV table") if looks_like_table(text) else refuse(
            "this .csv does not have a steady number of columns on every line")
    if ext in (".jsonl", ".ndjson", ".json"):
        if notes_from_jsonl(text) is not None:
            return Detected("note", "notes (JSON lines)")
        return refuse('expected one JSON object per line, each with a "text" field (and optionally "note_id", "patient_id")')
    guess = kind_of_text(text)
    if guess.kind == "table":
        return Detected("table", "CSV table (guessed)", guess.reason)
    return Detected("note", "note text")


def family(kind):
    return "notes" if kind in NOTES_FAMILY else "tables"
