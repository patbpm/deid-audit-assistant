"""An offline detector: patterns and name cues, no AI model, no network.

OfflineModel has the same complete() method as the hosted chat client, so the rest
of the pipeline runs unchanged. It answers only the detection prompt. It is much
weaker than a model: it finds identifiers that have a recognizable shape (emails,
phones, dates, labeled numbers, street addresses) and names that follow a cue
("Dr. Wu", "Patient: Kim Reyes", "Kim Reyes, MD"), then every other place those
names appear. A name with no cue is missed. Uncertain finds get a low confidence so
they go to a person. The patterns were not written against the project's test set.
"""

import json
import re
from dataclasses import dataclass

from deid.detect.client import Completion

MODEL = "offline-rules-1"
MONTH = (r"(?:January|February|March|April|May|June|July|August|September|October|November|December"
         r"|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)\.?")
WORD = r"[A-Z][a-z]+(?:['\-][A-Z]?[a-z]+)*"
STREET_WORDS = (r"(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Boulevard|Blvd|Court|Ct|Way|Place|Pl|"
                r"Terrace|Ter|Circle|Cir|Highway|Hwy)")
LABELS = (r"(?:MRN|MR#|Medical Record(?: Number| No\.?)?|Acct|Account(?: Number| No\.?)?|Accession(?: Number| No\.?)?|"
          r"Member ID|Policy(?: Number| No\.?)?|Insurance ID|Patient ID|Pt ID|SSN|ID)")
RELATIONS = (r"patient|name|pt|mother|father|mom|dad|wife|husband|spouse|partner|son|daughter|brother|sister|"
             r"guardian|referred by|seen by|provider|physician|attending|surgeon|nurse|contact|emergency contact|"
             r"signed by|dictated by|pcp|primary care")

# (type, pattern, group, confidence). group 0 = the whole match.
PATTERNS = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), 0, 0.97),
    ("PHONE", re.compile(r"(?<![\d-])(?:\+?1[ .-]?)?(?:\(\d{3}\)\s?|\d{3}[ .-])\d{3}[ .-]\d{4}(?!\d)"), 0, 0.95),
    ("ID", re.compile(r"(?<![\d-])\d{3}-\d{2}-\d{4}(?![\d-])"), 0, 0.95),
    ("ID", re.compile(rf"\b{LABELS}(?:\s*[#:]\s*|\s+)([A-Z0-9][A-Z0-9\-]{{3,}}\d[A-Z0-9\-]*)", re.I), 1, 0.92),
    ("ID", re.compile(r"\b[A-Z]{2,5}-?\d{6,}\b"), 0, 0.85),
    ("ID", re.compile(r"\b[A-Z]{2,4}-\d{2}-\d{5,}\b"), 0, 0.85),
    ("ID", re.compile(r"(?<![\w./:-])\d{7,10}(?![\w./:-])"), 0, 0.6),
    ("DATE", re.compile(r"\b\d{4}-\d{1,2}-\d{1,2}\b"), 0, 0.95),
    ("DATE", re.compile(r"\b\d{1,2}[/.-]\d{1,2}[/.-](?:\d{4}|\d{2})\b"), 0, 0.95),
    ("DATE", re.compile(rf"\b{MONTH} \d{{1,2}}(?:st|nd|rd|th)?, \d{{4}}\b"), 0, 0.97),
    ("DATE", re.compile(rf"\b\d{{1,2}}(?:st|nd|rd|th)? (?:of )?{MONTH},? \d{{4}}\b"), 0, 0.97),
    ("DATE", re.compile(rf"\b\d{{1,2}}-{MONTH}-\d{{2,4}}\b"), 0, 0.95),
    ("DATE", re.compile(rf"\b{MONTH} \d{{4}}\b"), 0, 0.8),
    ("DATE", re.compile(rf"\b{MONTH} \d{{1,2}}(?:st|nd|rd|th)?\b(?!,? \d{{4}})"), 0, 0.6),
    ("DATE", re.compile(r"(?<![\d/.:-])\d{1,2}/\d{1,2}(?![\d/.:-])"), 0, 0.5),
    ("ADDRESS", re.compile(
        rf"\b\d{{1,5}} (?:[NSEW]\.? )?{WORD}(?: {WORD}){{0,2}} {STREET_WORDS}\b\.?"
        rf"(?:,? (?:Apt|Unit|Suite|Ste|Apartment)\.? #?\w+)?"
        rf"(?:,? {WORD}(?: {WORD})?,? [A-Z]{{2}}\b(?: \d{{5}}(?:-\d{{4}})?)?)?"), 0, 0.93),
    ("ADDRESS", re.compile(rf"\b{WORD}(?: {WORD})?, [A-Z]{{2}} \d{{5}}(?:-\d{{4}})?\b"), 0, 0.85),
    ("ADDRESS", re.compile(r"\bP\.?O\.? Box \d+\b", re.I), 0, 0.9),
]
NAME_BODY = rf"{WORD}(?:(?:,? | )(?:{WORD}|[A-Z]\.?(?![A-Za-z\-]))){{0,2}}"
NAME_CUES = [
    re.compile(rf"\b(?:Dr|Mr|Mrs|Ms|Miss|Prof)\.? ({NAME_BODY})"),
    re.compile(rf"(?i:\b(?:{RELATIONS}))\s*[:\-]\s*({NAME_BODY})"),
    re.compile(rf"({WORD}(?: [A-Z]\.?)? {WORD}),? (?:MD|M\.D\.|DO|RN|NP|PA|PA-C|PhD|DDS|PharmD)\b"),
]
NOT_NAMES = {"patient", "the", "and", "unknown", "none", "dr", "mr", "mrs", "ms", "miss", "prof", "january", "february",
             "march", "april", "may", "june", "july", "august", "september", "october", "november", "december",
             "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "male", "female",
             "history", "plan", "exam", "date", "name", "age", "sex", "visit", "note", "report", "clinic", "hospital"}


@dataclass
class Found:
    text: str
    type: str
    confidence: float


def name_parts(name):
    words = [w.strip(".") for w in re.split(r"[\s,]+", name) if w]
    return [w for w in words if len(w) >= 2 and w.lower() not in NOT_NAMES]


def find_names(text):
    full, parts = {}, {}
    for cue in NAME_CUES:
        for m in cue.finditer(text):
            name = m.group(1).strip(" ,")
            words = name_parts(name)
            if not words:
                continue
            full[name] = 0.9
            for word in words:
                if len(word) >= 3:   # a short word on its own is too likely to be something else
                    parts.setdefault(word, 0.75)
    return full, parts


def find_all(text):
    """Identifier strings with a type and confidence. A string found in two ways keeps the more confident."""
    best = {}

    def add(string, kind, confidence):
        string = string.strip()
        if string and (string not in best or best[string].confidence < confidence):
            best[string] = Found(string, kind, confidence)

    for kind, pattern, group, confidence in PATTERNS:
        for m in pattern.finditer(text):
            add(m.group(group), kind, confidence)
    full, parts = find_names(text)
    for name, confidence in full.items():
        add(name, "NAME", confidence)
    for word, confidence in parts.items():
        add(word, "NAME", confidence)
    return sorted(best.values(), key=lambda f: (f.type, f.text))


class OfflineModel:
    """Looks like a chat client; answers the detection prompt from patterns."""
    model, params = MODEL, {}

    def complete(self, messages):
        if "find personal identifiers" not in messages[0]["content"]:
            raise ValueError("the offline detector only answers the detection prompt")
        content = messages[1]["content"]
        text = content.split("<<<\n", 1)[1].rsplit("\n>>>", 1)[0] if "<<<" in content else content
        found = [{"text": f.text, "type": f.type, "confidence": f.confidence} for f in find_all(text)]
        return Completion(json.dumps({"identifiers": found}), {}, 0.0, "stop")
