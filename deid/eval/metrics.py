"""Span-level scoring. Recall comes first: a missed identifier is the failure
that matters, so every table leads with it.

Three views per identifier type:
  exact    prediction matches a gold span's offsets and type (one-to-one)
  overlap  prediction overlaps a gold span of the same type by at least 1 char
  leak     share of gold characters NOT covered by any prediction of that type
           (how much of the identifier would survive redaction)

Counts are kept per note so confidence intervals can be bootstrapped by
resampling notes.
"""

import random
from collections import defaultdict

from . import TYPES

COUNT_KEYS = (
    "gold", "pred",
    "exact_tp",
    "gold_hit", "pred_hit",  # overlap view: gold with a hit, predictions that hit
    "gold_chars", "gold_chars_covered",
)


def _overlaps(a, b):
    return a["start"] < b["end"] and b["start"] < a["end"]


def _covered_chars(gold, preds):
    covered = 0
    for position in range(gold["start"], gold["end"]):
        if any(p["start"] <= position < p["end"] for p in preds):
            covered += 1
    return covered


def score_note(gold_spans, pred_spans, types=TYPES):
    """Return {type: {count_key: int}} for one note."""
    counts = {t: dict.fromkeys(COUNT_KEYS, 0) for t in types}
    for t in types:
        gold = [s for s in gold_spans if s["type"] == t]
        preds = [s for s in pred_spans if s["type"] == t]
        c = counts[t]
        c["gold"], c["pred"] = len(gold), len(preds)

        gold_keys = {(g["start"], g["end"]) for g in gold}
        c["exact_tp"] = len({(p["start"], p["end"]) for p in preds} & gold_keys)

        for g in gold:
            hits = [p for p in preds if _overlaps(g, p)]
            c["gold_hit"] += bool(hits)
            c["gold_chars"] += g["end"] - g["start"]
            c["gold_chars_covered"] += _covered_chars(g, hits)
        c["pred_hit"] = sum(any(_overlaps(g, p) for g in gold) for p in preds)
    return counts


def _ratio(num, den):
    return num / den if den else None


def _prf(tp_for_precision, tp_for_recall, pred, gold):
    precision = _ratio(tp_for_precision, pred)
    recall = _ratio(tp_for_recall, gold)
    f1 = None
    if precision is not None and recall is not None and precision + recall:
        f1 = 2 * precision * recall / (precision + recall)
    return {"precision": precision, "recall": recall, "f1": f1}


def summarize(totals):
    """Turn summed counts into rates (None when undefined)."""
    gold, pred = totals["gold"], totals["pred"]
    chars = totals["gold_chars"]
    return {
        "gold": gold,
        "pred": pred,
        "exact": _prf(totals["exact_tp"], totals["exact_tp"], pred, gold),
        "overlap": _prf(totals["pred_hit"], totals["gold_hit"], pred, gold),
        "leaked_char_rate": None if not chars else 1 - totals["gold_chars_covered"] / chars,
    }


def _columns(per_note, types):
    """{count_key: [value per note]} summed over the given types."""
    return {k: [sum(n[t][k] for t in types) for n in per_note] for k in COUNT_KEYS}


def evaluate(per_note, types=TYPES, bootstrap=1000, seed=0):
    """per_note: list of score_note results. Returns per-type + 'ALL' summaries
    with 95% bootstrap intervals (resampling notes) for overlap recall,
    overlap precision and the leaked-character rate."""
    groups = {t: (t,) for t in types}
    if len(types) > 1:
        groups["ALL"] = tuple(types)
    columns = {name: _columns(per_note, types) for name, types in groups.items()}
    result = {
        name: summarize({k: sum(v) for k, v in cols.items()}) for name, cols in columns.items()
    }

    rng = random.Random(seed)
    n = len(per_note)
    samples = {name: {"recall": [], "precision": [], "leak": []} for name in groups}
    for _ in range(bootstrap):
        idx = [rng.randrange(n) for _ in range(n)]
        for name, cols in columns.items():
            s = summarize({k: sum(map(v.__getitem__, idx)) for k, v in cols.items()})
            for metric, value in (
                ("recall", s["overlap"]["recall"]),
                ("precision", s["overlap"]["precision"]),
                ("leak", s["leaked_char_rate"]),
            ):
                if value is not None:
                    samples[name][metric].append(value)
    for name in groups:
        result[name]["ci95"] = {m: _interval(v) for m, v in samples[name].items()}
    return result


def _interval(values):
    values = sorted(values)
    if not values:
        return None
    return [values[int(0.025 * (len(values) - 1))], values[int(0.975 * (len(values) - 1))]]
