"""Generate synthetic clinical notes with ground-truth identifier spans.

    python -m deid.synth.generate [--seed N] [--patients N] [--out DIR]

Writes notes.jsonl and manifest.json. The same seed gives byte-identical output.
"""

import argparse
import hashlib
import json
import platform
import random
from collections import Counter
from pathlib import Path

from . import GENERATOR_VERSION, formats, people, templates
from .builder import render, validate_spans
from .resolver import Resolver

DEFAULT_SEED = 20261027
DEFAULT_PATIENTS = 150
NOTES_FILE = "notes.jsonl"
MANIFEST_FILE = "manifest.json"


def note_kinds(index):
    last = "radiology_report" if index % 2 == 0 else "telephone_encounter"
    return ["history_and_physical", "progress_note", "discharge_summary", last]


def generate_notes(seed=DEFAULT_SEED, patients=DEFAULT_PATIENTS):
    rng = random.Random(seed)
    providers = people.make_providers(rng)
    notes = []
    for index in range(1, patients + 1):
        patient = people.make_patient(rng, index, providers)
        for kind in note_kinds(index):
            note_date, dates = templates.note_dates(rng, patient, kind)
            accession = formats.make_accession(rng, note_date) if kind == "radiology_report" else ""
            template = templates.BUILDERS[kind](rng, patient)
            resolver = Resolver(rng, patient, dates, accession)
            text, spans = render(template, resolver)
            validate_spans(text, spans)
            notes.append({
                "note_id": f"N{len(notes) + 1:04d}",
                "patient_id": patient.pid,
                "note_type": kind,
                "note_date": note_date.isoformat(),
                "text": text,
                "spans": spans,
            })
    return notes


def write_notes(notes, out_dir, seed, patients):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    notes_path = out_dir / NOTES_FILE
    with open(notes_path, "w", encoding="utf-8", newline="\n") as handle:
        for note in notes:
            handle.write(json.dumps(note, sort_keys=True) + "\n")
    manifest = build_manifest(notes, notes_path, seed, patients)
    with open(out_dir / MANIFEST_FILE, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return manifest


def build_manifest(notes, notes_path, seed, patients):
    by_type = Counter()
    by_subtype = Counter()
    for note in notes:
        for span in note["spans"]:
            by_type[span["type"]] += 1
            by_subtype[f"{span['type']}/{span['subtype']}"] += 1
    return {
        "generator_version": GENERATOR_VERSION,
        "python_version": platform.python_version(),
        "seed": seed,
        "patients": patients,
        "notes": len(notes),
        "notes_by_type": dict(sorted(Counter(n["note_type"] for n in notes).items())),
        "spans": sum(by_type.values()),
        "spans_by_type": dict(sorted(by_type.items())),
        "spans_by_subtype": dict(sorted(by_subtype.items())),
        "notes_sha256": hashlib.sha256(notes_path.read_bytes()).hexdigest(),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--patients", type=int, default=DEFAULT_PATIENTS)
    parser.add_argument("--out", default="data/generated")
    args = parser.parse_args(argv)
    notes = generate_notes(args.seed, args.patients)
    manifest = write_notes(notes, args.out, args.seed, args.patients)
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
