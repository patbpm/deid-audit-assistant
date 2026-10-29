"""Assess one cleaned note for re-identification risk.

    view = masked_view(original_text, changes)     # changes from Replacer.apply
    result = assess_note(client, view, cache)

Clues are located in the masked view and mapped back to character offsets in the
original note, so a leftover identifier can be sent back to the replacement step.
The risk level is a signal for a human reviewer, never a guarantee of safety.
"""

import json
import re
from dataclasses import dataclass, field

from deid.detect.client import estimate_tokens
from deid.detect.detector import FENCE, Cache, ParseError
from deid.eval import TYPES

from deid.detect.context import set_aside_reason
from .prompt import CATEGORIES, PROMPT_VERSION, RISK_LEVELS, build_messages

TAG = re.compile(r"\[(?:NAME|DATE|ID|PHONE|EMAIL|ADDRESS)\]")


@dataclass
class MaskedView:
    text: str
    pieces: list  # (masked_start, masked_end, original_start, original_end, is_tag)

    def to_original(self, start, end):
        """Original range for a masked range, or None if it lies inside one tag.
        A range that touches a tag is widened to cover the whole tag."""
        touched = [p for p in self.pieces if p[0] < end and start < p[1]]
        if not touched or all(p[4] for p in touched) and len(touched) == 1:
            return None
        lo, hi = [], []
        for m0, m1, o0, o1, is_tag in touched:
            if is_tag:
                lo.append(o0)
                hi.append(o1)
            else:
                lo.append(o0 + max(start, m0) - m0)
                hi.append(o0 + min(end, m1) - m0)
        return min(lo), max(hi)


def masked_view(text, changes):
    """The original note with every changed span shown as its type tag."""
    out, pieces, cursor, pos = [], [], 0, 0

    def add(piece, o0, o1, is_tag):
        nonlocal pos
        out.append(piece)
        pieces.append((pos, pos + len(piece), o0, o1, is_tag))
        pos += len(piece)

    for c in sorted(changes, key=lambda c: c["start"]):
        if c["start"] > cursor:
            add(text[cursor:c["start"]], cursor, c["start"], False)
        add(f"[{c['type']}]", c["start"], c["end"], True)
        cursor = c["end"]
    if cursor < len(text):
        add(text[cursor:], cursor, len(text), False)
    return MaskedView("".join(out), pieces)


def parse_assessment(content):
    """The model's reply -> (risk, raw clue list). Raises ParseError."""
    text = FENCE.sub("", content.strip())
    for candidate in (text, text[text.find("{"): text.rfind("}") + 1]):
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict) and isinstance(data.get("clues"), list):
            risk = str(data.get("risk", "")).strip().lower()
            return (risk if risk in RISK_LEVELS else None), data["clues"]
    raise ParseError("no JSON assessment in reply")


def locate(text, phrase):
    """Every (start, end) where phrase occurs, whitespace-tolerant."""
    words = phrase.split()
    if not words:
        return []
    pattern = r"\s+".join(re.escape(w) for w in words)
    return [(m.start(), m.end()) for m in re.finditer(pattern, text)]


def clean_clues(raw, view):
    """Validate the model's clues and attach original-text ranges.
    Returns (clues, dropped_count)."""
    clues, dropped = [], 0
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not item["text"].strip():
            dropped += 1
            continue
        phrase = item["text"].strip()
        category = str(item.get("category", "")).strip().upper()
        category = category if category in CATEGORIES else "OTHER"
        kind = str(item.get("type", "")).strip().upper()
        kind = kind if kind in TYPES else ""
        if TAG.fullmatch(phrase):
            dropped += 1  # a tag is not a leftover
            continue
        why = str(item.get("why", ""))[:300]
        reason = set_aside_reason(phrase, kind) if category == "LEFTOVER" and kind else None
        if reason:  # the detector leaves these in place on purpose; the same convention applies here
            category, kind, why = "OTHER", "", f"reported as a leftover, but {reason}. {why}".strip()
        ranges = []
        for a, b in locate(view.text, phrase):
            mapped = view.to_original(a, b)
            if mapped:
                ranges.append(mapped)
        clues.append({"text": phrase, "category": category, "type": kind, "why": why, "ranges": ranges})
    return clues, dropped


def final_risk(model_risk, clues):
    """The model's level, raised to high whenever a located leftover identifier
    of a known type was reported (a direct identifier is always high risk)."""
    level = model_risk or ("low" if not clues else "medium")
    if any(c["category"] == "LEFTOVER" and c["type"] and c["ranges"] for c in clues):
        return "high"
    return level


@dataclass
class Assessment:
    risk_model: str | None
    risk: str
    clues: list = field(default_factory=list)
    dropped_clues: int = 0
    parse_error: bool = False
    truncated: bool = False
    cached: bool = False
    usage: dict = field(default_factory=dict)
    latency_s: float = 0.0


def assess_note(client, view, cache=None):
    messages = build_messages(view.text)
    cache = cache or Cache(None, PROMPT_VERSION)
    key = cache.key(client, view.text)
    completion = cache.get(key)
    cached = completion is not None
    if not cached:
        completion = client.complete(messages)
        cache.put(key, completion)
    usage = {} if cached else dict(completion.usage)
    if not cached and "prompt_tokens" not in usage:
        usage["prompt_tokens"] = estimate_tokens(" ".join(m["content"] for m in messages))
    truncated = completion.finish_reason == "length"
    try:
        risk_model, raw = parse_assessment(completion.content)
    except ParseError:
        # An unreadable reply is not evidence of safety: report it as unknown risk.
        return Assessment(None, "unknown", parse_error=True, truncated=truncated,
                          cached=cached, usage=usage, latency_s=completion.latency_s)
    clues, dropped = clean_clues(raw, view)
    return Assessment(risk_model, final_risk(risk_model, clues), clues, dropped, False,
                      truncated, cached, usage, completion.latency_s)
