"""Review-burden curve: how much recall does each reviewed span buy?

    python -m deid.eval.burden --pred runs/meta-dev.jsonl --split dev --name meta-dev

Policy being measured. Candidate spans with confidence at or above --hi (default
0.8) are redacted without review; spans with no confidence count as above it.
Candidates below --hi are not redacted unless a person looks at them. The
reviewer is assumed to be perfect (redacts a candidate exactly when it overlaps a
true identifier), so every curve is an upper bound on what a real reviewer
achieves. Widening the review band one candidate at a time, most confident
first, gives recall as a function of reviewed spans:

  ranked   candidates reviewed in order of decreasing confidence
  random   the same candidates in random order (mean of --shuffles orders)
  oracle   true candidates first: the best any ranking could do

The gap between "ranked" and "random" is what the confidence scores are worth.
Identifiers that no candidate overlaps stay missed whatever the burden; they are
reported as the ceiling and can only be caught by reading the note.
Type labels are ignored. Use dev notes while developing.
"""

import argparse
import json
import random
from pathlib import Path

from .run import load_predictions, read_jsonl, split_of

OUT_DIR = Path("results/dev")
FRACTIONS = (0.5, 0.9, 1.0)


def overlaps(a, b):
    return a["start"] < b["end"] and b["start"] < a["end"]


def build(notes, predictions, hi):
    """-> (gold count, gold indices covered by auto-redacted spans,
    band candidates [{"conf", "gold": set of gold indices, "key"}])."""
    gold_total, covered, band = 0, set(), []
    for n in notes:
        gold = [(gold_total + i, s) for i, s in enumerate(n["spans"])]
        gold_total += len(gold)
        for p in predictions.get(n["note_id"], []):
            hit = {i for i, g in gold if overlaps(p, g)}
            conf = p.get("confidence")
            if conf is None or conf >= hi:
                covered |= hit
            else:
                band.append({"conf": conf, "gold": hit, "key": (n["note_id"], p["start"], p["end"])})
    return gold_total, covered, band


def recall_curve(order, covered, gold_total):
    """Recall after reviewing the first k of `order`, for k = 0..len(order)."""
    seen, points = set(covered), []
    points.append(len(seen) / gold_total if gold_total else None)
    for c in order:
        seen |= c["gold"]
        points.append(len(seen) / gold_total if gold_total else None)
    return points


def reached(curve, start, end, fraction):
    """Fewest reviewed spans at which `fraction` of the way from start to end is reached."""
    if end is None or start is None or end <= start:
        return None
    target = start + fraction * (end - start) - 1e-12
    return next((k for k, r in enumerate(curve) if r >= target), None)


def analyse(notes, predictions, hi=0.8, shuffles=200, seed=0):
    gold_total, covered, band = build(notes, predictions, hi)
    ranked = sorted(band, key=lambda c: (-c["conf"], c["key"]))
    # oracle: greedily take the candidate that adds the most new true identifiers, then the rest
    seen, greedy, rest = set(covered), [], list(band)
    while True:
        best = max(rest, key=lambda c: (len(c["gold"] - seen), c["conf"]), default=None)
        if best is None or not (best["gold"] - seen):
            break
        greedy.append(best)
        rest.remove(best)
        seen |= best["gold"]
    oracle = greedy + sorted(rest, key=lambda c: (-c["conf"], c["key"]))
    rng = random.Random(seed)
    totals = [0.0] * (len(band) + 1)
    for _ in range(shuffles if band else 0):
        order = band[:]
        rng.shuffle(order)
        for k, r in enumerate(recall_curve(order, covered, gold_total)):
            totals[k] += r or 0.0
    curves = {"ranked": recall_curve(ranked, covered, gold_total),
              "oracle": recall_curve(oracle, covered, gold_total),
              "random": [t / shuffles for t in totals] if band else recall_curve([], covered, gold_total)}
    start, end = curves["ranked"][0], curves["oracle"][-1]
    true_in_band = sum(bool(c["gold"]) for c in band)
    return {
        "hi": hi, "notes": len(notes), "gold": gold_total, "shuffles": shuffles,
        "recall_without_review": start,
        "recall_ceiling": end,
        "unreachable_by_review": None if not gold_total else 1 - len(set().union(covered, *(c["gold"] for c in band))) / gold_total,
        "band_candidates": len(band), "band_candidates_that_are_true": true_in_band,
        "spans_to_reach": {name: {f"{int(f * 100)}%": reached(curves[name], start, end, f) for f in FRACTIONS}
                           for name in curves},
        "curves": curves,
    }


def svg(result, title):
    w, h, m = 560, 320, 48
    ks = max(1, result["band_candidates"])
    lo = min(c[0] for c in result["curves"].values() if c[0] is not None)
    hi_r = max(max(c) for c in result["curves"].values())
    span = max(hi_r - lo, 1e-9)

    def xy(k, r):
        return m + (w - 2 * m) * k / ks, h - m - (h - 2 * m) * (r - lo) / span

    colors = {"oracle": "#2a9d8f", "ranked": "#1f5fbf", "random": "#8a8f98"}
    lines = []
    for n, name in enumerate(("oracle", "ranked", "random")):
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in (xy(k, r) for k, r in enumerate(result["curves"][name])))
        lines.append(f'<polyline fill="none" stroke="{colors[name]}" stroke-width="2" points="{pts}"/>'
                     f'<line x1="{w - 150}" y1="{h - m - 56 + 16 * n}" x2="{w - 124}" y2="{h - m - 56 + 16 * n}" stroke="{colors[name]}" stroke-width="3"/>'
                     f'<text x="{w - 118}" y="{h - m - 52 + 16 * n}" font-size="11">{name}</text>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w + 40}" height="{h}" viewBox="0 0 {w + 40} {h}" font-family="sans-serif">'
            f'<rect width="100%" height="100%" fill="white"/>'
            f'<text x="{m}" y="20" font-size="13" font-weight="bold">{title}</text>'
            f'<line x1="{m}" y1="{h - m}" x2="{w - m}" y2="{h - m}" stroke="#444"/><line x1="{m}" y1="{m}" x2="{m}" y2="{h - m}" stroke="#444"/>'
            f'<text x="{(w) / 2 - 60}" y="{h - 10}" font-size="11">spans a person reviews (0 to {result["band_candidates"]})</text>'
            f'<text x="6" y="{m - 8}" font-size="11">recall {100 * lo:.1f}% to {100 * hi_r:.1f}%</text>'
            + "".join(lines) + "</svg>")


def pct(v):
    return "n/a" if v is None else f"{100 * v:.1f}"


def markdown(result, name):
    r = result
    lines = [f"**{name}**: {r['notes']} notes, {r['gold']} true identifiers, review band = candidates with confidence below {r['hi']}.",
             f"Recall with no review {pct(r['recall_without_review'])}%; with a perfect reviewer on every band candidate "
             f"{pct(r['recall_ceiling'])}%; never reachable by reviewing candidates {pct(r['unreachable_by_review'])}% "
             f"(only reading the note finds those). Band: {r['band_candidates']} candidates, "
             f"{r['band_candidates_that_are_true']} of them true identifiers."]
    if r["band_candidates"]:
        lines += ["", "Spans reviewed to reach a share of the gain (fewer is better):", "",
                  "| Order | " + " | ".join(f"{k} of gain" for k in r["spans_to_reach"]["ranked"]) + " |",
                  "|---|" + "---|" * len(FRACTIONS)]
        for order in ("ranked", "random", "oracle"):
            lines.append(f"| {order} | " + " | ".join("n/a" if v is None else str(v)
                                                       for v in r["spans_to_reach"][order].values()) + " |")
    else:
        lines.append("No candidate falls below the threshold, so there is nothing to review and no curve.")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pred", required=True, help="detector predictions JSONL with a confidence per span")
    parser.add_argument("--name", required=True)
    parser.add_argument("--gold", default="data/generated/notes.jsonl")
    parser.add_argument("--split", choices=("dev", "test", "all"), default="dev")
    parser.add_argument("--allow-test", action="store_true")
    parser.add_argument("--hi", type=float, default=0.8, help="confidence at or above which spans are redacted unreviewed")
    parser.add_argument("--shuffles", type=int, default=200)
    parser.add_argument("--only-predicted", action="store_true", help="score only notes the system was run on")
    parser.add_argument("--out", default=str(OUT_DIR))
    args = parser.parse_args(argv)
    if args.split != "dev" and not args.allow_test:
        parser.error("develop on dev; pass --allow-test for the final reporting run")
    gold = read_jsonl(args.gold)
    predictions = load_predictions(args.pred, {n["note_id"] for n in gold})
    notes = [n for n in gold if args.split == "all" or split_of(n["patient_id"]) == args.split]
    if args.only_predicted:
        notes = [n for n in notes if n["note_id"] in predictions]
    result = analyse(notes, predictions, args.hi, args.shuffles)
    result.update({"name": args.name, "split": args.split, "only_predicted": args.only_predicted,
                   "pred_file": str(args.pred)})
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"burden-{args.name}.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                                                  encoding="utf-8", newline="\n")
    (out / f"burden-{args.name}.svg").write_text(svg(result, f"Review burden: {args.name}"),
                                                 encoding="utf-8", newline="\n")
    print(markdown(result, args.name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
