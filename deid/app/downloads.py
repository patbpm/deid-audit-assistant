"""The files a person can download from a finished job.

Every name is looked up in a list built from the job itself; no part of the URL is
used as a path. Cleaned output holds no identifier the tool replaced, but it can still
hold one the tool missed, so each file says to check it before sharing. The audit
report, the key and the change log hold the original values (they are the evidence
trace): the key and the change log stay on disk in the job folder and are not
offered, and the audit report is offered on its own with a warning.

Each entry is (content type, loader, warning, note). A warning means the file holds
original values; the note says what the file is.
"""

import io
import json
import zipfile
from pathlib import Path

CSV = "text/csv"
JSON = "application/json"
TEXT = "text/plain"
HTML = "text/html"
ZIP = "application/zip"


def zipped(parts):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts:
            z.writestr(name, data)
    return buffer.getvalue()


def notes_files(job, directory, review):
    """-> {name: (content type, loader, warning)}. review: the job's review Store."""
    def exported(suffix):
        review.export()
        return (Path(directory) / f"notes.{suffix}").read_bytes()

    def cleaned_text():
        notes = [json.loads(line) for line in exported("reviewed.notes.jsonl").decode().splitlines() if line.strip()]
        if len(notes) != 1:
            raise ValueError("a single text file is only offered when there is exactly one cleaned note")
        return notes[0]["text"].encode()

    def package():
        return zipped([("cleaned-notes.jsonl", exported("reviewed.notes.jsonl")),
                       ("review-log.json", exported("review-log.json")),
                       ("README.txt", b"Cleaned notes after your review decisions (anything undecided stays replaced), "
                                      b"and the review log (your decisions, no note text). The cleaned notes can still "
                                      b"contain identifiers the tool missed: check them before sharing. This is an "
                                      b"assistant for human review, not a compliance certification.\n")])

    files = {
        "cleaned-notes.jsonl": (JSON, lambda: exported("reviewed.notes.jsonl"), "",
                                "the cleaned notes, with your decisions applied; check before sharing"),
        "review-log.json": (JSON, lambda: exported("review-log.json"), "", "your decisions and counts; no note text"),
        "cleaned-package.zip": (ZIP, package, "", "cleaned notes and the log together; check before sharing"),
        "audit-report.html": (HTML, lambda: (Path(directory) / "notes.audit.html").read_bytes(),
                              "contains the original identifiers", "every change with its evidence"),
    }
    if (job["result"] or {}).get("notes") == 1 and not (job["result"] or {}).get("not_cleaned"):
        files["cleaned-note.txt"] = (TEXT, cleaned_text, "", "the cleaned note as plain text; check before sharing")
    return files


def tables_files(job, directory):
    out = Path(directory) / "tables-out"
    names = list((job["result"] or {}).get("tables", {}))
    files = {f"{name}.csv": (CSV, (lambda n=name: (out / f"{n}.csv").read_bytes()), "",
                             "the cleaned table; check before sharing") for name in names}
    shared = {"plan.json": "how each column was treated; no cell values",
              "report.json": "counts per column; no cell values",
              "risk.json": "the small-group check; no row detail",
              "risk-rows.csv": "rows in small groups, cleaned values only"}
    for name, note in shared.items():
        files[name] = (CSV if name.endswith(".csv") else JSON, (lambda n=name: (out / n).read_bytes()), "", note)

    def package():
        parts = [(f"{n}.csv", (out / f"{n}.csv").read_bytes()) for n in names]
        parts += [(n, (out / n).read_bytes()) for n in shared]
        parts.append(("README.txt", b"Cleaned tables, the column plan, the report and the small-group check. The "
                                    b"cleaned tables can still contain identifiers the tool missed: check them before "
                                    b"sharing. This is an assistant for human review, not a compliance certification.\n"))
        return zipped(parts)

    files["cleaned-tables.zip"] = (ZIP, package, "", "cleaned tables with the plan and reports; check before sharing")
    return files


def available(job, directory, review=None):
    """The downloads for a finished job, or {} when it has nothing to offer."""
    if job["state"] != "done" or not job["result"]:
        return {}
    if job["result"]["kind"] == "notes":
        return notes_files(job, directory, review)
    return tables_files(job, directory)
