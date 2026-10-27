"""Shared helpers for baselines: read notes, write predictions."""

import json
from pathlib import Path


def read_notes(path="data/generated/notes.jsonl"):
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_predictions(predictions, out_path):
    """predictions: {note_id: [{"start", "end", "type"}, ...]}"""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as handle:
        for note_id in sorted(predictions):
            record = {"note_id": note_id, "spans": predictions[note_id]}
            handle.write(json.dumps(record, sort_keys=True) + "\n")
