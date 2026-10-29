"""Turn the model's identifier strings into character-offset spans.

Every occurrence of a listed string is marked, because an identifier that is
removed in one place and left in another is still a leak. Strings that cannot be
found in the note are reported back, never guessed at.

Three exceptions, each recorded in `ignored` rather than dropped quietly:
a year on its own or a relative date is not an identifier; a listed name that is
directly followed by an eponym noun ("Wilson disease") is a condition, not the
person; and an occurrence of a name the model says is also an ordinary word
("Short of breath"), with no title or label before it, is not decided here but
marked `doubt="name_use"` for a second look (deid.agent.nameuse).
"""

import re

from deid.eval import TYPES

from .context import has_cue_before, is_eponym_use, set_aside_reason, LAST_FIRST_AFTER

WORD_EDGE = "A-Za-z0-9"


def _pattern(string):
    """Exact match, tolerant only of runs of whitespace, not glued to a longer word."""
    body = r"\s+".join(re.escape(part) for part in string.split())
    return re.compile(rf"(?<![{WORD_EDGE}]){body}(?![{WORD_EDGE}])")


def find_spans(text, items, ignored=None):
    """items: [{"text", "type", "confidence"?, "also_a_word"?}, ...] -> (spans, unmatched_strings).

    A string listed twice keeps the first type. Where matches overlap, the longer
    one wins, so "Kim, Susan" beats "Kim" at the same place. `ignored`, if given, is
    a list that receives {"text", "type", "start", "end", "reason", "source"} for
    every listed string or occurrence that was set aside (start/end are None when a
    whole string was set aside).
    """
    candidates, unmatched, seen = [], [], set()
    for item in items:
        string = item["text"].strip()
        if not string or string in seen:
            continue
        seen.add(string)
        reason = set_aside_reason(string, item["type"])
        if reason:
            if ignored is not None:
                ignored.append({"text": string, "type": item["type"], "start": None, "end": None,
                                "reason": reason, "source": "rule"})
            continue
        found = [m for m in _pattern(string).finditer(text)]
        if not found:
            unmatched.append(string)
            continue
        for m in found:
            span = {"start": m.start(), "end": m.end(), "type": item["type"],
                    "confidence": item.get("confidence")}
            if item["type"] == "NAME":
                if is_eponym_use(text, m.start(), m.end()):
                    if ignored is not None:
                        ignored.append({"text": m.group(0), "type": "NAME", "start": m.start(), "end": m.end(),
                                        "reason": "followed by a word that makes it the name of a condition or device, "
                                                  "not a person", "source": "rule"})
                    continue
                if (item.get("also_a_word") and len(string.split()) == 1 and not has_cue_before(text, m.start())
                        and not LAST_FIRST_AFTER.match(text[m.end():m.end() + 12])):
                    span["doubt"] = "name_use"
            candidates.append(span)
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
        entry = {"text": item["text"], "type": kind, "confidence": confidence}
        if item.get("also_a_word") is True and kind == "NAME":
            entry["also_a_word"] = True
        items.append(entry)
    return items, dropped
