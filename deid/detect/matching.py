"""Turn the model's identifier strings into character-offset spans.

Every occurrence of a listed string is marked, because an identifier that is
removed in one place and left in another is still a leak. Strings that cannot be
found in the note are reported back, never guessed at.
"""

import re

from deid.eval import TYPES

WORD_EDGE = "A-Za-z0-9"


def _pattern(string):
    """Exact match, tolerant only of runs of whitespace, not glued to a longer word."""
    body = r"\s+".join(re.escape(part) for part in string.split())
    return re.compile(rf"(?<![{WORD_EDGE}]){body}(?![{WORD_EDGE}])")


def find_spans(text, items):
    """items: [{"text", "type", "confidence"?}, ...] -> (spans, unmatched_strings).

    A string listed twice keeps the first type. Where matches overlap, the longer
    one wins, so "Kim, Susan" beats "Kim" at the same place.
    """
    candidates, unmatched, seen = [], [], set()
    for item in items:
        string = item["text"].strip()
        if not string or string in seen:
            continue
        seen.add(string)
        found = [m for m in _pattern(string).finditer(text)]
        if not found:
            unmatched.append(string)
            continue
        for m in found:
            candidates.append({
                "start": m.start(), "end": m.end(), "type": item["type"],
                "confidence": item.get("confidence"),
            })
    candidates.sort(key=lambda s: (-(s["end"] - s["start"]), s["start"]))
    spans = []
    for c in candidates:
        if not any(c["start"] < s["end"] and s["start"] < c["end"] for s in spans):
            spans.append(c)
    spans.sort(key=lambda s: (s["start"], s["end"]))
    return spans, unmatched


def clean_items(raw_items):
    """Keep well-formed items; return (items, number_dropped)."""
    items, dropped = [], 0
    for item in raw_items:
        ok = isinstance(item, dict) and isinstance(item.get("text"), str)
        kind = str(item.get("type", "")).upper() if isinstance(item, dict) else ""
        if not ok or kind not in TYPES:
            dropped += 1
            continue
        confidence = item.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            confidence = None
        items.append({"text": item["text"], "type": kind, "confidence": confidence})
    return items, dropped
