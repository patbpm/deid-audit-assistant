"""Score a predictions file against the synthetic ground truth.

    python -m deid.eval.run --pred runs/regex.jsonl --name regex [--split test]

Predictions are JSONL, one object per note: {"note_id": ..., "spans": [{"start",
"end", "type"}, ...]} with types from deid.eval.TYPES. Results are written to
results/<name>-<split>.json and a markdown table is printed.
"""

import argparse
import hashlib
import json
from pathlib import Path

from . import TYPES
from .metrics import evaluate, score_note

AGNOSTIC_TYPE = "PHI"  # stand-in type when scoring without regard to identifier type
DEV_MAX_PATIENT = 50  # patients P0001-P0050 are for development; P0051+ is the test set


def split_of(patient_id):
    return "dev" if int(patient_id.lstrip("P")) <= DEV_MAX_PATIENT else "test"


def read_jsonl(path):
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def load_predictions(path, gold_ids):
    by_note = {}
    for record in read_jsonl(path):
        if record["note_id"] not in gold_ids:
            raise ValueError(f"prediction for unknown note: {record['note_id']}")
        for span in record["spans"]:
            if span["type"] not in (*TYPES, AGNOSTIC_TYPE):
                raise ValueError(f"unknown span type {span['type']!r} in {record['note_id']}")
        by_note[record["note_id"]] = record["spans"]
    return by_note


def run(gold_path, pred_path, name, split, out_dir, bootstrap=1000, agnostic=False):
    all_gold = read_jsonl(gold_path)
    predictions = load_predictions(pred_path, {n["note_id"] for n in all_gold})
    gold = all_gold if split == "all" else [n for n in all_gold if split_of(n["patient_id"]) == split]
    types = TYPES
    if agnostic:
        # Score "did the system cover this identifier", ignoring which type it chose.
        types = (AGNOSTIC_TYPE,)
        gold = [{**n, "spans": [{**s, "type": AGNOSTIC_TYPE} for s in n["spans"]]} for n in gold]
        predictions = {k: [{**s, "type": AGNOSTIC_TYPE} for s in v] for k, v in predictions.items()}
    per_note = [score_note(n["spans"], predictions.get(n["note_id"], []), types) for n in gold]
    missing = sum(1 for n in gold if n["note_id"] not in predictions)
    result = {
        "name": name,
        "split": split,
        "type_agnostic": agnostic,
        "notes": len(gold),
        "notes_without_predictions": missing,
        "gold_file_sha256": hashlib.sha256(Path(gold_path).read_bytes()).hexdigest(),
        "pred_file_sha256": hashlib.sha256(Path(pred_path).read_bytes()).hexdigest(),
        "bootstrap_resamples": bootstrap,
        "metrics": evaluate(per_note, types, bootstrap=bootstrap),
    }
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / f"{name}-{split}{'-agnostic' if agnostic else ''}.json", "w", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return result


def _pct(value):
    return "n/a" if value is None else f"{100 * value:.1f}"


def _ci(interval):
    return "" if not interval else f" [{_pct(interval[0])}-{_pct(interval[1])}]"


def markdown(result):
    lines = [
        f"**{result['name']}** on `{result['split']}`"
        + (" (type-agnostic: type labels ignored)" if result["type_agnostic"] else "")
        + f" ({result['notes']} notes, "
        f"{result['notes_without_predictions']} without predictions). "
        "Overlap recall/precision count a hit when a span of the same type overlaps; "
        "exact needs identical offsets. Leaked = share of gold characters left uncovered.",
        "",
        "| Type | Gold | Recall % (overlap, 95% CI) | Precision % (overlap, 95% CI) | Exact R % | Exact P % | Leaked chars % |",
        "|---|---|---|---|---|---|---|",
    ]
    for t, m in result["metrics"].items():
        ci = m["ci95"]
        lines.append(
            f"| {t} | {m['gold']} | {_pct(m['overlap']['recall'])}{_ci(ci['recall'])} "
            f"| {_pct(m['overlap']['precision'])}{_ci(ci['precision'])} "
            f"| {_pct(m['exact']['recall'])} | {_pct(m['exact']['precision'])} "
            f"| {_pct(m['leaked_char_rate'])} |"
        )
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pred", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--gold", default="data/generated/notes.jsonl")
    parser.add_argument("--split", choices=("dev", "test", "all"), default="test")
    parser.add_argument("--out", default="results")
    parser.add_argument("--bootstrap", type=int, default=1000)
    parser.add_argument("--agnostic", action="store_true", help="ignore type labels")
    args = parser.parse_args(argv)
    print(markdown(run(args.gold, args.pred, args.name, args.split, args.out, args.bootstrap, args.agnostic)))


if __name__ == "__main__":
    main()
