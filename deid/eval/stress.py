"""Stress-test the name check with a perfect scripted detector. No model is called.

    python -m deid.eval.stress --notes data/generated/adversarial-b/notes.jsonl --answer ordinary_word --out runs/stress.jsonl

The scripted detector lists exactly the true identifiers (and, in the common-word and eponym
families, every capitalized word of a true name too, as the real model did), flagging names in those
families as "also_a_word". The name check then answers `--answer` for every doubtful occurrence,
whatever it says. This measures how much the pipeline loses if the check is wrong in a fixed way:
`ordinary_word` is the worst case (every doubtful occurrence is released), `name` and `unsure` the
safe ones. It tests the design and the test set, not any model.
"""

import argparse
import json
import re
from pathlib import Path

from deid.agent.pipeline import detect_one
from deid.detect.client import Completion
from deid.detect.detector import Cache
from deid.eval.run import read_jsonl

WORD_FAMILIES = ("common_word_names", "eponym_names")


class PerfectDetector:
    model, params = "stress", {"max_tokens": 1}

    def __init__(self, notes, answer):
        self.by_text = {n["text"]: n for n in notes}
        self.answer = answer

    def complete(self, messages):
        system = messages[0]["content"]
        usage = {"prompt_tokens": 1, "completion_tokens": 1}
        if "find personal identifiers" in system:
            text = messages[1]["content"].split("<<<\n", 1)[1].rsplit("\n>>>", 1)[0]
            note, items = self.by_text[text], {}
            for s in note["spans"]:
                item = {"text": s["text"], "type": s["type"], "confidence": 0.95}
                if s["type"] == "NAME" and note["family"] in WORD_FAMILIES:
                    item["also_a_word"] = True
                items[s["text"]] = item
            if note["family"] in WORD_FAMILIES:
                for s in note["spans"]:
                    for part in re.split(r"[ ,]+", s["text"]):
                        if len(part) > 2 and part[0].isupper():
                            items.setdefault(part, {"text": part, "type": "NAME", "confidence": 0.9, "also_a_word": True})
            return Completion(json.dumps({"identifiers": list(items.values())}), usage, 0.0, "stop")
        if "help remove personal names" in system:
            ids = [int(i) for i in re.findall(r"^(\d+)\. type=", messages[1]["content"], re.M)]
            return Completion(json.dumps({"verdicts": [{"id": i, "decision": self.answer, "why": "stress"} for i in ids]}),
                              usage, 0.0, "stop")
        return Completion(json.dumps({"verdicts": []}), usage, 0.0, "stop")


def stress(notes, answer):
    client, records = PerfectDetector(notes, answer), []
    for note in notes:
        detected, _ = detect_one(note, client, Cache(None), Cache(None, "vf1"), 0.8, True)
        records.append({"note_id": note["note_id"],
                        "spans": [{k: s[k] for k in ("start", "end", "type")} for s in detected.spans]})
    return records


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--notes", required=True)
    parser.add_argument("--answer", choices=("name", "ordinary_word", "unsure"), required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    records = stress(read_jsonl(args.notes), args.answer)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in records), encoding="utf-8", newline="\n")
    print(f"{len(records)} notes, name check answering {args.answer!r} for every doubtful occurrence -> {args.out}")


if __name__ == "__main__":
    main()
