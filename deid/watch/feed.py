"""Drip synthetic notes into a folder, one at a time, so watch mode has something to watch.

    python -m deid.watch.feed --out runs/demo-feed --count 8 --interval 4

Writes notes of the first patients of the synthetic dataset (data/generated/notes.jsonl; make it with
python -m deid.synth.generate) as <patient>__<note>.txt. After the fifth note it edits the first one (an addendum
with a new phone number) and after the seventh it deletes the second, so a viewer sees a new note cleaned, an
edited note cleaned again with its old copy withdrawn, and a removed note's output deleted. Synthetic data only.
"""

import argparse
import json
import time
from pathlib import Path

ADDENDUM = "\nAddendum: patient phoned the clinic from 555-0100 about a refill.\n"


def read_notes(path):
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def feed(notes, out, count, interval, log=print, sleep=time.sleep):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for i, note in enumerate(notes[:count], 1):
        path = out / f"{note['patient_id']}__{note['note_id']}.txt"
        path.write_text(note["text"], encoding="utf-8", newline="\n")
        written.append(path)
        log(f"added {path.name}")
        if i == 5:
            sleep(interval)
            written[0].write_text(notes[0]["text"] + ADDENDUM, encoding="utf-8", newline="\n")
            log(f"edited {written[0].name} (an addendum with a phone number)")
        if i == 7 and len(written) > 1:
            sleep(interval)
            written[1].unlink()
            log(f"deleted {written[1].name}")
        sleep(interval)
    return written


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True)
    parser.add_argument("--notes", default="data/generated/notes.jsonl")
    parser.add_argument("--count", type=int, default=8)
    parser.add_argument("--interval", type=float, default=4.0)
    args = parser.parse_args(argv)
    feed(read_notes(args.notes), args.out, args.count, args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
