"""Invented sample inputs for trying the app. Both come from the project's synthetic generators.

notes()  the four notes of the first dev patient (dev split, seed 20261027), as JSON lines
tables() two linked tables (patients, encounters) written with headers worded unlike the rules'
         hints, so some columns need a person's decision
"""

import json
import tempfile
from pathlib import Path

from deid.synth import generate
from deid.synth import tables as synth_tables


def notes():
    patient = generate.generate_notes(generate.DEFAULT_SEED, 1)
    lines = [json.dumps({"note_id": n["note_id"], "patient_id": n["patient_id"], "text": n["text"]}) for n in patient]
    return [("sample-notes.jsonl", ("\n".join(lines) + "\n").encode())]


def tables():
    patients, encounters, _ = synth_tables.make_tables(synth_tables.DEFAULT_SEED, 20)
    with tempfile.TemporaryDirectory() as tmp:
        truth = synth_tables.write_style(tmp, "unseen", patients, encounters)
        return [(meta["file"], (Path(tmp) / meta["file"]).read_bytes()) for meta in truth.values()]


SAMPLES = {"notes": notes, "tables": tables}
