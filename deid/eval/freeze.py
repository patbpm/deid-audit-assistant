"""Record or check the frozen dataset and test split.

    python -m deid.eval.freeze --write     # (re)write data/frozen.json from data/generated/
    python -m deid.eval.freeze             # check data/generated/ against data/frozen.json

data/frozen.json is committed. Changing it means the test set changed, so every
earlier result is out of date and must be re-run.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

from .run import DEV_MAX_PATIENT, split_of

FROZEN_PATH = Path("data/frozen.json")
NOTES_PATH = Path("data/generated/notes.jsonl")
MANIFEST_PATH = Path("data/generated/manifest.json")


def describe(notes_path):
    """Hashes and counts that pin down the notes file and its dev/test split."""
    raw = Path(notes_path).read_bytes()
    lines = [line for line in raw.split(b"\n") if line.strip()]
    notes = [json.loads(line) for line in lines]
    test_lines = [line for line, n in zip(lines, notes) if split_of(n["patient_id"]) == "test"]
    patients = {"dev": set(), "test": set()}
    for n in notes:
        patients[split_of(n["patient_id"])].add(n["patient_id"])
    return {
        "notes_sha256": hashlib.sha256(raw).hexdigest(),
        "test_notes_sha256": hashlib.sha256(b"\n".join(test_lines) + b"\n").hexdigest(),
        "notes": len(notes),
        "dev_max_patient": DEV_MAX_PATIENT,
        "dev_patients": len(patients["dev"]),
        "test_patients": len(patients["test"]),
        "dev_notes": len(notes) - len(test_lines),
        "test_notes": len(test_lines),
    }


def build(notes_path, manifest_path):
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    frozen = {key: manifest[key] for key in ("generator_version", "seed", "patients", "spans")}
    frozen["python_version_generated_with"] = manifest["python_version"]
    frozen.update(describe(notes_path))
    return frozen


def load(path=FROZEN_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def differences(frozen, current):
    return {k: (frozen[k], current.get(k)) for k in frozen if k in current and frozen[k] != current[k]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    if args.write:
        FROZEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(FROZEN_PATH, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(build(NOTES_PATH, MANIFEST_PATH), handle, indent=2, sort_keys=True)
            handle.write("\n")
        print(f"wrote {FROZEN_PATH}")
        return 0
    diff = differences(load(), describe(NOTES_PATH))
    if diff:
        print(f"{NOTES_PATH} does not match {FROZEN_PATH}: {diff}")
        return 1
    print("dataset and test split match data/frozen.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
