"""Rule-based checks on each replaced span. No model is involved.

A check never changes a replacement; it only decides whether a person should
look at it. "accept" means no rule objected, not that the span is right.
"""

import re

LOW_CONFIDENCE = 0.8


def format_problems(kind, original):
    digits = re.sub(r"\D", "", original)
    if kind == "PHONE" and not 7 <= len(digits) <= 15:
        return ["phone has an unusual number of digits"]
    if kind == "ID" and not any(ch.isdigit() for ch in original):
        return ["identifier contains no digits"]
    if kind == "EMAIL" and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", original.strip()):
        return ["does not look like an email address"]
    if kind == "DATE" and not any(ch.isdigit() for ch in original):
        return ["date contains no digits"]
    return []


def verify_span(change, confidence=None, low=LOW_CONFIDENCE):
    """-> {"decision": "accept" | "review", "reasons": [...]}"""
    reasons = []
    if confidence is not None and confidence < low:
        reasons.append(f"detector confidence {confidence:.2f} is below {low:.2f}")
    if change["flagged"]:
        reasons.append("could not be rewritten safely; replaced with a tag")
    if "assumed-month-first" in change["rule"]:
        reasons.append("date read month-first; the day/month order is a guess")
    if "assumed-day-first" in change["rule"]:
        reasons.append("dotted date read day-first; the day/month order is a guess")
    if "-no-year" in change["rule"]:
        reasons.append("date has no year; the year used for shifting is a guess")
    reasons += format_problems(change["type"], change["original"])
    return {"decision": "review" if reasons else "accept", "reasons": reasons}
