"""De-identify notes: replace the detected spans with consistent surrogates.

    python -m deid.replace.run --pred runs/meta-dev.jsonl --out runs/deid-dev
    python -m deid.replace.run --pred gold --out runs/deid-dev-oracle   # true spans, to test the engine alone

Writes three files:
  <out>.notes.jsonl    {"note_id", "text"}: the de-identified notes
  <out>.changes.jsonl  every change with the original string (contains identifiers: do not share)
  <out>.key.json       the mapping tables, i.e. the re-identification key (do not share)

Dates are shifted per patient; patient_id from the notes file is the patient key.
"""

import argparse
import json
from pathlib import Path

from deid.baselines.common import read_notes
from deid.eval.run import read_jsonl, split_of

from .engine import Replacer


def write_jsonl(path, records):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--notes", default="data/generated/notes.jsonl")
    parser.add_argument("--pred", required=True, help="predictions JSONL, or 'gold' for the true spans")
    parser.add_argument("--split", choices=("dev", "test"), default="dev")
    parser.add_argument("--allow-test", action="store_true")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if args.split == "test" and not args.allow_test:
        parser.error("the test split is for the final reporting run; pass --allow-test")

    notes = [n for n in read_notes(args.notes) if split_of(n["patient_id"]) == args.split]
    if args.pred != "gold":
        spans = {r["note_id"]: r["spans"] for r in read_jsonl(args.pred)}
        notes = [n for n in notes if n["note_id"] in spans]
    inputs = [{"note_id": n["note_id"], "patient_key": n["patient_id"], "text": n["text"],
               "spans": n["spans"] if args.pred == "gold" else spans[n["note_id"]]} for n in notes]

    replacer = Replacer(args.seed).fit(inputs)
    texts, changes = [], []
    for note in inputs:
        text, ch = replacer.apply(note)
        texts.append({"note_id": note["note_id"], "text": text})
        changes.append({"note_id": note["note_id"], "changes": ch})
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(f"{out}.notes.jsonl", texts)
    write_jsonl(f"{out}.changes.jsonl", changes)
    Path(f"{out}.key.json").write_text(
        json.dumps(replacer.key_tables(), indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    flagged = sum(c["flagged"] for r in changes for c in r["changes"])
    print(f"{len(texts)} notes, {sum(len(r['changes']) for r in changes)} replacements, {flagged} flagged -> {out}.*")


if __name__ == "__main__":
    main()
