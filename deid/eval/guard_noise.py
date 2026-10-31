"""How many review notices would the guard (deid.agent.guard) add to runs already made? No model is called.

    python -m deid.eval.guard_noise

Reads each saved run's detector output (git-ignored runs/) and the notes, applies the guard, and counts
notices by kind. A guard that fires on ordinary notes would add review work for nothing; this is the check
that it does not. Writes results/guard/noise.json.
"""

import json
from collections import Counter
from pathlib import Path

from deid.agent.guard import guard_notices
from deid.eval.run import load_predictions, read_jsonl, split_of

SETS = {
    "dev (200 notes)": ("data/generated/notes.jsonl", "dev", "runs/agent-meta-dev-v2.detector.jsonl"),
    "held-out test (400 notes)": ("data/generated/notes.jsonl", "test", "runs/agent-meta-test.detector.jsonl"),
    "adversarial set B (200 notes)": ("data/generated/adversarial-b/notes.jsonl", None, "runs/agent-meta-advb-rtfix.detector.jsonl"),
    "adversarial set A (180 notes)": ("data/generated/adversarial/notes.jsonl", None, "runs/agent-meta-adv.detector.jsonl"),
}


def kind_of(notice):
    if "instructions to an AI" in notice:
        return "instruction-like text"
    if "no identifiers" in notice:
        return "nothing found"
    return "pattern rules disagree"


def main():
    out = {}
    for name, (notes_path, split, pred_path) in SETS.items():
        notes = read_jsonl(notes_path)
        if split:
            notes = [n for n in notes if split_of(n["patient_id"]) == split]
        preds = load_predictions(pred_path, {n["note_id"] for n in notes})
        counts, strings = Counter(), Counter()
        for n in notes:
            for notice in guard_notices(n["text"], preds.get(n["note_id"], [])):
                counts[kind_of(notice)] += 1
                if kind_of(notice) == "pattern rules disagree":
                    strings[notice.split("found ")[1].split(", which")[0]] += 1
        out[name] = {"notes": len(notes), "notices": dict(counts), "pattern_strings": dict(strings)}
        print(f"{name}: {dict(counts) or 'no notices'}" + (f"  strings: {dict(strings)}" if strings else ""))
    Path("results/guard").mkdir(parents=True, exist_ok=True)
    Path("results/guard/noise.json").write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
