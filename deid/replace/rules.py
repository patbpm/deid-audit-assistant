"""Safe Harbor rules that need no model: ages of 90 or more, ZIP codes, web addresses, IP addresses.

    spans = find_rule_spans(text, existing_spans)

Each span is {"start", "end", "type", "confidence": 1.0, "source": "safe-harbor rules"} with a type
from RULE_TYPES. Spans overlapping one that is already known (a model's span, an address that
already holds its ZIP) are left out, so a rule never fights the detector. The patterns are narrow
on purpose: an age counts only with a unit or a cue ("94-year-old", "age 94"), a ZIP only after a
state abbreviation or the word ZIP, an IP only with four dotted numbers of 0-255.

The HIPAA Safe Harbor method (45 CFR 164.514(b)(2)) names these categories. The wording here follows
secondary summaries; check the regulation before relying on it. RESTRICTED_ZIP3 is the list of
three-digit ZIP prefixes the HHS guidance gives for areas of 20,000 people or fewer; verify it
against the current guidance.
"""

import re

SOURCE = "safe-harbor rules"
RULE_TYPES = ("AGE", "ZIP", "URL", "IP")

RESTRICTED_ZIP3 = {"036", "059", "063", "102", "203", "556", "692", "790", "821", "823", "830", "831",
                   "878", "879", "884", "890", "893"}

AGE = r"(?:9\d|1[0-4]\d)"
UNIT = r"(?:[- ]?(?:(?:years?|yrs?)[- ]?old|y\.?\s?o\.?|y/o))"
AGE_PATTERNS = [
    re.compile(rf"(?<![\w.:/-])({AGE})(?={UNIT}(?![\w]))", re.I),            # 94-year-old, 94 yo, 94 y/o, 94 yrs
    re.compile(rf"\b(?:age[ds]?|aged)\s*[:=]?\s*({AGE})\b(?!\s*(?:%|mg|mcg|kg|lbs?|mmhg|bpm|/))", re.I),
]
# Idaho (ID) is left out: "ID 12345" is far more often an identifier label than a state and ZIP.
STATES = ("AL AK AZ AR CA CO CT DE DC FL GA HI IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY "
          "NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY").split()
ZIP_CUE = re.compile(r"(?:\b(?:" + "|".join(STATES) + r")\b,?\s+|\b(?i:ZIP(?:\s+code)?)\s*[:#]?\s*)"
                     r"(\d{5}(?:-\d{4})?)(?![\d-])")
URL = re.compile(r"\b(?:https?://|www\.)[^\s<>\"')\]]+", re.I)
IP = re.compile(r"(?<![\d.])((?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3})(?![\d.])")


def _overlaps(start, end, spans):
    return any(start < s["end"] and s["start"] < end for s in spans)


def zip_replacement(original):
    """First three digits and 00, or 00000 for the restricted prefixes. A ZIP+4 loses its last four."""
    prefix = original[:3]
    return "00000" if prefix in RESTRICTED_ZIP3 else prefix + "00"


def find_rule_spans(text, existing=()):
    """Non-overlapping rule spans for `text`, none overlapping `existing`. Sorted by start."""
    taken = [{"start": int(s["start"]), "end": int(s["end"])} for s in existing]
    found = []

    def add(kind, start, end):
        if start < end and not _overlaps(start, end, taken):
            span = {"start": start, "end": end, "type": kind, "confidence": 1.0, "source": SOURCE}
            found.append(span)
            taken.append(span)

    for m in URL.finditer(text):
        add("URL", m.start(), m.end() - len(m.group(0)) + len(m.group(0).rstrip(".,;:")))
    for m in IP.finditer(text):
        add("IP", m.start(1), m.end(1))
    for m in ZIP_CUE.finditer(text):
        add("ZIP", m.start(1), m.end(1))
    for pattern in AGE_PATTERNS:
        for m in pattern.finditer(text):
            add("AGE", m.start(1), m.end(1))
    return sorted(found, key=lambda s: s["start"])
