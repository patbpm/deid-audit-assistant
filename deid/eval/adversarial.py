"""Score a system on the adversarial set, family by family.

    python -m deid.eval.adversarial --pred runs/adv-regex.jsonl --name regex
    python -m deid.eval.adversarial --table            # compare every saved result

Type labels are ignored (a hit is any prediction overlapping a true span), so the
numbers say whether an identifier was covered, not whether it was labeled right.
Intervals come from resampling notes within each family; with 20 notes per family
they are wide. This set is a test set: do not tune on it (docs/ADVERSARIAL.md).
"""

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from .metrics import evaluate, score_note
from .run import AGNOSTIC_TYPE, load_predictions, read_jsonl

NOTES = "data/generated/adversarial/notes.jsonl"
OUT_DIR = Path("results/adversarial")


def agnostic(spans):
    return [{**s, "type": AGNOSTIC_TYPE} for s in spans]


def score_group(notes, predictions, bootstrap):
    per_note = [score_note(agnostic(n["spans"]), agnostic(predictions.get(n["note_id"], [])), (AGNOSTIC_TYPE,))
                for n in notes]
    m = evaluate(per_note, (AGNOSTIC_TYPE,), bootstrap=bootstrap)[AGNOSTIC_TYPE]
    total = {k: sum(p[AGNOSTIC_TYPE][k] for p in per_note) for k in ("gold", "pred", "pred_hit")}
    return {
        "notes": len(notes), "gold": m["gold"], "pred": m["pred"],
        "recall": m["overlap"]["recall"], "recall_ci95": m["ci95"]["recall"],
        "precision": m["overlap"]["precision"],
        "false_positives": total["pred"] - total["pred_hit"],
        "false_positives_per_note": (total["pred"] - total["pred_hit"]) / len(notes) if notes else None,
        "leaked_char_rate": m["leaked_char_rate"],
    }


def subtype_recall(notes, predictions):
    """Share of true spans of each subtype that some prediction overlaps (no intervals)."""
    hit, total = defaultdict(int), defaultdict(int)
    for n in notes:
        preds = predictions.get(n["note_id"], [])
        for s in n["spans"]:
            key = f"{n['family']}/{s['subtype']}"
            total[key] += 1
            hit[key] += any(p["start"] < s["end"] and s["start"] < p["end"] for p in preds)
    return {k: {"gold": total[k], "hit": hit[k]} for k in sorted(total)}


def run(notes_path, pred_path, name, out_dir=OUT_DIR, bootstrap=1000):
    notes = read_jsonl(notes_path)
    predictions = load_predictions(pred_path, {n["note_id"] for n in notes})
    families = sorted({n["family"] for n in notes})
    result = {
        "name": name, "type_agnostic": True, "bootstrap_resamples": bootstrap,
        "notes_sha256": hashlib.sha256(Path(notes_path).read_bytes()).hexdigest(),
        "pred_file_sha256": hashlib.sha256(Path(pred_path).read_bytes()).hexdigest(),
        "overall": score_group(notes, predictions, bootstrap),
        "families": {f: score_group([n for n in notes if n["family"] == f], predictions, bootstrap)
                     for f in families},
        "by_subtype": subtype_recall(notes, predictions),
    }
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{name}.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                                          encoding="utf-8", newline="\n")
    return result


def pct(value):
    return "n/a" if value is None else f"{100 * value:.1f}"


def table(results):
    """One row per family, one column per system: recall % (interval) and false positives per note."""
    names = [r["name"] for r in results]
    lines = ["| Family | Gold | " + " | ".join(f"{n}: recall % (95% CI) / FP per note" for n in names) + " |",
             "|---|---|" + "---|" * len(names)]
    rows = [("ALL", [r["overall"] for r in results])]
    rows += [(f, [r["families"][f] for r in results]) for f in sorted(results[0]["families"])]
    for label, groups in rows:
        cells = []
        for g in groups:
            ci = g["recall_ci95"]
            ci_text = "" if not ci else f" ({pct(ci[0])}-{pct(ci[1])})"
            cells.append(f"{pct(g['recall'])}{ci_text} / {g['false_positives_per_note']:.2f}")
        lines.append(f"| {label} | {groups[0]['gold']} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pred")
    parser.add_argument("--name")
    parser.add_argument("--notes", default=NOTES)
    parser.add_argument("--out", default=str(OUT_DIR))
    parser.add_argument("--bootstrap", type=int, default=1000)
    parser.add_argument("--table", action="store_true", help="print a comparison of all saved results")
    args = parser.parse_args(argv)
    if args.table:
        results = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(args.out).glob("*.json"))]
        print(table(results) if results else "no results saved yet")
        return 0
    if not (args.pred and args.name):
        parser.error("--pred and --name are required unless --table is used")
    result = run(args.notes, args.pred, args.name, args.out, args.bootstrap)
    print(table([result]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
