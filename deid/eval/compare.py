"""Compare two or more systems on the same notes: accuracy, tokens, latency, cost.

    python -m deid.eval.compare --split dev \
        --system meta=runs/meta-dev.jsonl:runs/meta-dev.log.json \
        --system open=runs/open-dev.jsonl:runs/open-dev.log.json \
        --price meta=PRICE_IN,PRICE_OUT --price open=PRICE_IN,PRICE_OUT --name meta-vs-open

Each --system is NAME=PREDICTIONS[:LOG], where LOG is the .log.json written by
deid.detect.run. Only notes that every system predicted are scored, so the
systems face identical text. Type labels are ignored (a hit is any overlap).
The first system is the reference: for every other system the table gives the
paired difference in recall (other minus reference) with a bootstrap interval
over notes, which is the number to look at before saying one is better.

Prices are USD per million tokens and are never assumed: without --price a
system's cost shows as n/a. Tokens served from the response cache are not
counted, so a rerun looks cheaper than the first call did.
"""

import argparse
import hashlib
import json
import random
import statistics
from pathlib import Path

from .metrics import COUNT_KEYS, score_note
from .run import AGNOSTIC_TYPE, load_predictions, read_jsonl, split_of

OUT_DIR = Path("results/compare")


def agnostic(spans):
    return [{**s, "type": AGNOSTIC_TYPE} for s in spans]


def per_note_counts(notes, predictions):
    return [score_note(agnostic(n["spans"]), agnostic(predictions[n["note_id"]]), (AGNOSTIC_TYPE,))[AGNOSTIC_TYPE]
            for n in notes]


def rates(counts):
    total = {k: sum(c[k] for c in counts) for k in COUNT_KEYS}
    recall = total["gold_hit"] / total["gold"] if total["gold"] else None
    precision = total["pred_hit"] / total["pred"] if total["pred"] else None
    leak = 1 - total["gold_chars_covered"] / total["gold_chars"] if total["gold_chars"] else None
    return {"gold": total["gold"], "pred": total["pred"], "recall": recall, "precision": precision,
            "leaked_char_rate": leak, "false_positives": total["pred"] - total["pred_hit"]}


def interval(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    return [values[int(0.025 * (len(values) - 1))], values[int(0.975 * (len(values) - 1))]]


def bootstrap(counts_by_system, resamples, seed=0):
    """Intervals for each system's recall and precision, and for each non-reference
    system's recall difference from the first, all from the same resampled notes."""
    rng = random.Random(seed)
    n = len(next(iter(counts_by_system.values())))
    names = list(counts_by_system)
    samples = {name: {"recall": [], "precision": []} for name in names}
    diffs = {name: [] for name in names[1:]}
    for _ in range(resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        r = {name: rates([counts_by_system[name][i] for i in idx]) for name in names}
        for name in names:
            samples[name]["recall"].append(r[name]["recall"])
            samples[name]["precision"].append(r[name]["precision"])
        for name in names[1:]:
            if r[name]["recall"] is not None and r[names[0]]["recall"] is not None:
                diffs[name].append(r[name]["recall"] - r[names[0]]["recall"])
    return ({name: {k: interval(v) for k, v in s.items()} for name, s in samples.items()},
            {name: interval(v) for name, v in diffs.items()})


def run_stats(log_path, note_ids, price):
    """Tokens, latency and cost from a detector log, for the notes being compared."""
    if not log_path:
        return {"log": None}
    log = json.loads(Path(log_path).read_text(encoding="utf-8"))
    notes = [n for n in log["notes"] if n["note_id"] in note_ids]
    live = [n for n in notes if not n["cached"]]
    tokens_in = sum(n["usage"].get("prompt_tokens", 0) for n in live)
    tokens_out = sum(n["usage"].get("completion_tokens", 0) for n in live)
    latencies = sorted(n["latency_s"] for n in notes)
    out = {
        "log": str(log_path), "model": log["summary"].get("model"), "provider": log["summary"].get("provider"),
        "notes_in_log": len(notes), "notes_from_cache": len(notes) - len(live),
        "tokens_in": tokens_in, "tokens_out": tokens_out,
        "tokens_per_live_note": (tokens_in + tokens_out) / len(live) if live else None,
        "latency_s_median": statistics.median(latencies) if latencies else None,
        "latency_s_p90": latencies[int(0.9 * (len(latencies) - 1))] if latencies else None,
        "parse_errors": sum(n["parse_error"] for n in notes), "truncated": sum(n["truncated"] for n in notes),
        "unmatched_strings": sum(len(n["unmatched"]) for n in notes),
        "price_usd_per_million": list(price) if price else None, "cost_usd": None, "cost_usd_per_1000_notes": None,
    }
    if price and live:
        out["cost_usd"] = (tokens_in * price[0] + tokens_out * price[1]) / 1e6
        out["cost_usd_per_1000_notes"] = out["cost_usd"] / len(live) * 1000
    return out


def compare(gold_path, systems, split, name, price=None, resamples=1000, out_dir=OUT_DIR):
    """systems: ordered list of (name, predictions path, log path or None)."""
    price = price or {}
    gold = read_jsonl(gold_path)
    gold_ids = {n["note_id"] for n in gold}
    preds = {s: load_predictions(p, gold_ids) for s, p, _ in systems}
    common = set.intersection(*(set(p) for p in preds.values()))
    notes = [n for n in gold if n["note_id"] in common and (split == "all" or split_of(n["patient_id"]) == split)]
    if not notes:
        raise ValueError("no notes were predicted by every system")
    counts = {s: per_note_counts(notes, preds[s]) for s, _, _ in systems}
    intervals, diffs = bootstrap(counts, resamples)
    ids = {n["note_id"] for n in notes}
    result = {
        "name": name, "split": split, "type_agnostic": True, "notes_compared": len(notes),
        "reference": systems[0][0], "bootstrap_resamples": resamples,
        "gold_file_sha256": hashlib.sha256(Path(gold_path).read_bytes()).hexdigest(),
        "systems": {}, "recall_difference_vs_reference_ci95": diffs,
    }
    for s, pred_path, log_path in systems:
        result["systems"][s] = {
            **rates(counts[s]), "recall_ci95": intervals[s]["recall"], "precision_ci95": intervals[s]["precision"],
            "pred_file_sha256": hashlib.sha256(Path(pred_path).read_bytes()).hexdigest(),
            **run_stats(log_path, ids, price.get(s)),
        }
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{name}.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                                          encoding="utf-8", newline="\n")
    return result


def pct(value):
    return "n/a" if value is None else f"{100 * value:.1f}"


def span(ci):
    return "" if not ci else f" ({pct(ci[0])}-{pct(ci[1])})"


def num(value, digits=1, unit=""):
    return "n/a" if value is None else f"{value:.{digits}f}{unit}"


def markdown(result):
    ref = result["reference"]
    lines = [
        f"**{result['name']}** on `{result['split']}`: {result['notes_compared']} notes predicted by every system, "
        "type labels ignored. Intervals are 95% bootstrap over notes. Cost is n/a unless a price was supplied.", "",
        "| System | Recall % | Precision % | Leaked chars % | False positives | Recall vs " + ref + " (pp, paired) |",
        "|---|---|---|---|---|---|",
    ]
    for s, m in result["systems"].items():
        diff = result["recall_difference_vs_reference_ci95"].get(s)
        diff_text = "reference" if s == ref else (
            "n/a" if not diff else f"{100 * (m['recall'] - result['systems'][ref]['recall']):+.1f} "
                                    f"({100 * diff[0]:+.1f} to {100 * diff[1]:+.1f})")
        lines.append(f"| {s} | {pct(m['recall'])}{span(m['recall_ci95'])} | {pct(m['precision'])}{span(m['precision_ci95'])} "
                     f"| {pct(m['leaked_char_rate'])} | {m['false_positives']} | {diff_text} |")
    lines += ["", "| System | Model | Tokens per live note | Median latency s | p90 latency s | Cost per 1,000 notes | Cached | Parse errors | Unmatched strings |",
              "|---|---|---|---|---|---|---|---|---|"]
    for s, m in result["systems"].items():
        if m.get("log") is None:
            lines.append(f"| {s} | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |")
            continue
        cost = "n/a" if m["cost_usd_per_1000_notes"] is None else f"${m['cost_usd_per_1000_notes']:.2f}"
        lines.append(f"| {s} | {m['model']} | {num(m['tokens_per_live_note'], 0)} | {num(m['latency_s_median'])} "
                     f"| {num(m['latency_s_p90'])} | {cost} | {m['notes_from_cache']} | {m['parse_errors']} | {m['unmatched_strings']} |")
    return "\n".join(lines)


def parse_pair(text):
    name, _, path = text.partition("=")
    if not name or not path:
        raise argparse.ArgumentTypeError("use NAME=PATH")
    return name, path


def parse_price(text):
    name, _, rest = text.partition("=")
    try:
        price_in, price_out = (float(x) for x in rest.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError("use NAME=PRICE_IN,PRICE_OUT (USD per million tokens)") from None
    return name, (price_in, price_out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--system", action="append", type=parse_pair, required=True,
                        help="NAME=PREDICTIONS; the first one is the reference")
    parser.add_argument("--log", action="append", type=parse_pair, default=[],
                        help="NAME=LOG, the .log.json written by deid.detect.run for that system")
    parser.add_argument("--price", action="append", type=parse_price, default=[])
    parser.add_argument("--gold", default="data/generated/notes.jsonl")
    parser.add_argument("--split", choices=("dev", "test", "all"), default="dev")
    parser.add_argument("--allow-test", action="store_true")
    parser.add_argument("--name", required=True)
    parser.add_argument("--out", default=str(OUT_DIR))
    parser.add_argument("--bootstrap", type=int, default=1000)
    args = parser.parse_args(argv)
    if len(args.system) < 2:
        parser.error("give at least two --system entries")
    if args.split != "dev" and not args.allow_test:
        parser.error("develop on dev; pass --allow-test for the final reporting run")
    logs = dict(args.log)
    systems = [(name, path, logs.get(name)) for name, path in args.system]
    result = compare(args.gold, systems, args.split, args.name, dict(args.price), args.bootstrap, args.out)
    print(markdown(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
