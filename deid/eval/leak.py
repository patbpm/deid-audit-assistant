"""Look for original identifiers left word for word in the cleaned notes of an agent run.

    python -m deid.eval.leak --audit runs/agent-meta-test.audit.json --notes data/generated/notes.jsonl \
        --out results/test/leak-agent-meta-test.json

The cleaned text is rebuilt from the audit's changes (offsets and replacements), and every labeled
identifier string is searched for in it. A hit is not always a leak: a short string can sit inside
other text ("8/1" inside "Pain 8/10"), and a stand-in can start with an original name ("King" inside
"Kingsley"). So every hit is listed with its context for a person to judge; nothing is decided here.
Name parts of four or more letters are searched too, as a second, looser list.
"""

import argparse
import json
from pathlib import Path

CONTEXT = 40
MIN_PART = 4


def cleaned_text(note):
    out = note["text"]
    for entry in sorted(note["entries"], key=lambda e: -e["start"]):
        out = out[:entry["start"]] + entry["replacement"] + out[entry["end"]:]
    return out


def around(text, needle):
    i = text.find(needle)
    return text[max(0, i - CONTEXT):i + len(needle) + CONTEXT]


def check(audit, gold_notes):
    """Return the counts and the listed hits. Raises if an audited note differs from the labeled note."""
    totals, full, parts = {}, [], []
    for note in audit["notes"]:
        labeled = gold_notes[note["note_id"]]
        if note["text"] != labeled["text"]:
            raise ValueError(f"{note['note_id']}: the audit's original text is not the labeled note's text")
        out = cleaned_text(note)
        for span in labeled["spans"]:
            totals[span["type"]] = totals.get(span["type"], 0) + 1
            if span["text"] in out:
                full.append({"note_id": note["note_id"], "type": span["type"], "original": span["text"],
                             "context": around(out, span["text"])})
            if span["type"] == "NAME":
                for part in sorted(set(span["text"].replace(",", " ").split())):
                    if len(part) >= MIN_PART and part in out:
                        parts.append({"note_id": note["note_id"], "name": span["text"], "part": part,
                                      "context": around(out, part)})
    return {"notes": len(audit["notes"]), "labeled_spans": sum(totals.values()), "labeled_by_type": totals,
            "full_string_hits": full, "name_part_hits": parts}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--audit", required=True)
    parser.add_argument("--notes", default="data/generated/notes.jsonl")
    parser.add_argument("--out", default=None, help="write the result as JSON (it holds original text: keep it under runs/ "
                                                    "unless the run is synthetic and you mean to publish it)")
    args = parser.parse_args(argv)
    audit = json.loads(Path(args.audit).read_text(encoding="utf-8"))
    gold = {}
    for line in Path(args.notes).read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            gold[record["note_id"]] = record
    result = check(audit, gold)
    print(f"{result['notes']} notes, {result['labeled_spans']} labeled identifiers: "
          f"{len(result['full_string_hits'])} found word for word in the cleaned text, "
          f"{len(result['name_part_hits'])} name parts of {MIN_PART}+ letters found")
    for hit in result["full_string_hits"] + result["name_part_hits"]:
        print("  ", hit["note_id"], repr(hit.get("original") or hit["part"]), "...", repr(hit["context"]))
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
