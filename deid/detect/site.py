"""A site profile: teach the detector the local names and codes of one clinic.

    {"name": "Hartwell Regional (invented)",
     "facilities": ["Hartwell Regional Hospital", "HRH", "Birch Pavilion", "MICU-3"],
     "id_patterns": [{"label": "research ID", "regex": "HRH-\\\\d{5}", "example": "HRH-12345"}],
     "notes": "Buildings and units here are named after trees. List any such name."}

What it does, in two parts that need no extra model:

  rules   every listed facility name (a place inside the organization: hospital, clinic, building,
          ward, unit) and every match of an id_patterns regex becomes a span, source "site profile";
          the model's own spans win where they overlap. Facilities are replaced by "Facility N" (the
          same stand-in for the same name), codes by a same-shaped code.
  prompt  the detection prompt gets a short "local rules" section naming the same things, so the
          model also lists variants the file does not (the notes line can say how to recognize them).

ProfiledClient wraps a chat client: it adds that section to the detection prompt only, and puts the
profile's digest in its request parameters, so saved replies for different profiles never mix.

Why: a 2026 study of LLM de-identification found that naming the institution's own PHI categories in
the prompt recovered most of what generic prompts and a purpose-built tool missed (hospital
abbreviations, building names, internal codes): https://arxiv.org/abs/2608.17051 . This implements that
idea; docs/SITE.md reports what it did on an invented site.

The profile is the person's own local file. Regular expressions in it run on note text with Python's re,
which has no time limit: do not paste a pattern you do not understand.
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

SOURCE = "site profile"
MAX_FACILITIES, MAX_PATTERNS, MAX_NAME, MAX_REGEX, MAX_NOTES = 300, 20, 80, 200, 600
DETECTION_MARK = "find personal identifiers"


class ProfileError(ValueError):
    """The profile file is not usable; the message says what to fix."""


@dataclass
class Profile:
    name: str = ""
    facilities: list = field(default_factory=list)
    id_patterns: list = field(default_factory=list)  # [{"label", "regex", "example"?}]
    notes: str = ""

    def empty(self):
        return not (self.facilities or self.id_patterns or self.notes)

    def to_dict(self):
        return {"name": self.name, "facilities": list(self.facilities),
                "id_patterns": [dict(p) for p in self.id_patterns], "notes": self.notes}

    def digest(self):
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True).encode()).hexdigest()[:12]

    def prompt_addition(self):
        lines = ["Local rules for this site (they add to the types above):"]
        if self.facilities:
            lines.append("- These are names of places inside this organization. List each one you find as ADDRESS, copied "
                         "exactly as written: " + "; ".join(self.facilities) + ".")
            lines.append("- Also list as ADDRESS any other hospital, clinic, building, ward or unit name of this organization, "
                         "even when it is not in that list.")
        for pattern in self.id_patterns:
            example = f" (for example {pattern['example']})" if pattern.get("example") else ""
            lines.append(f"- {pattern['label']}{example} is an ID: list it as ID.")
        if self.notes:
            lines.append("- " + self.notes.strip())
        return "\n".join(lines)

    def rule_spans(self, text, existing=()):
        """Spans for listed facility names (type FACILITY) and id_patterns matches (type ID) that overlap
        none of `existing` or each other. Sorted by start."""
        taken = [{"start": int(s["start"]), "end": int(s["end"])} for s in existing]
        found = []

        def add(kind, start, end):
            if start < end and not any(start < s["end"] and s["start"] < end for s in taken):
                span = {"start": start, "end": end, "type": kind, "confidence": 1.0, "source": SOURCE}
                found.append(span)
                taken.append(span)

        names = sorted(self.facilities, key=len, reverse=True)
        if names:
            pattern = re.compile(r"(?<![\w-])(?:" + "|".join(re.escape(n) for n in names) + r")(?![\w-])", re.I)
            for m in pattern.finditer(text):
                add("FACILITY", m.start(), m.end())
        for p in self.id_patterns:
            for m in re.finditer(p["regex"], text):
                add("ID", m.start(), m.end())
        return sorted(found, key=lambda s: s["start"])


def _text(value, what, limit):
    if not isinstance(value, str) or not value.strip():
        raise ProfileError(f"{what} must be a non-empty string")
    if len(value) > limit:
        raise ProfileError(f"{what} is longer than {limit} characters")
    return value.strip()


def parse(data):
    """A Profile from a decoded JSON object, or ProfileError."""
    if not isinstance(data, dict):
        raise ProfileError("a site profile is a JSON object")
    unknown = set(data) - {"name", "facilities", "id_patterns", "notes"}
    if unknown:
        raise ProfileError("unknown field(s): " + ", ".join(sorted(unknown)))
    facilities = data.get("facilities", [])
    if not isinstance(facilities, list) or len(facilities) > MAX_FACILITIES:
        raise ProfileError(f"facilities must be a list of at most {MAX_FACILITIES} names")
    names, seen = [], set()
    for f in facilities:
        name = _text(f, "a facility name", MAX_NAME)
        if name.lower() not in seen:
            seen.add(name.lower())
            names.append(name)
    patterns = data.get("id_patterns", [])
    if not isinstance(patterns, list) or len(patterns) > MAX_PATTERNS:
        raise ProfileError(f"id_patterns must be a list of at most {MAX_PATTERNS} items")
    clean = []
    for p in patterns:
        if not isinstance(p, dict) or set(p) - {"label", "regex", "example"}:
            raise ProfileError('each id pattern is {"label", "regex", "example"?}')
        label, regex = _text(p.get("label"), "a pattern label", MAX_NAME), _text(p.get("regex"), "a pattern", MAX_REGEX)
        try:
            compiled = re.compile(regex)
        except re.error as err:
            raise ProfileError(f"pattern {regex!r} is not a valid regular expression: {err}") from None
        if compiled.match(""):
            raise ProfileError(f"pattern {regex!r} matches the empty string")
        entry = {"label": label, "regex": regex}
        if p.get("example") is not None:
            entry["example"] = _text(p["example"], "a pattern example", MAX_NAME)
        clean.append(entry)
    notes = data.get("notes", "")
    if notes:
        notes = _text(notes, "notes", MAX_NOTES)
    name = _text(data["name"], "name", MAX_NAME) if data.get("name") else ""
    return Profile(name, names, clean, notes or "")


def load(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as err:
        raise ProfileError(f"could not read {path}: {err}") from None
    return parse(data)


def from_names(lines, notes=""):
    """A Profile from the names a person typed, one per line (the app's text box)."""
    names = [ln.strip() for ln in (lines.splitlines() if isinstance(lines, str) else lines) if ln.strip()]
    return parse({"facilities": names, "notes": notes.strip()}) if names or notes.strip() else Profile()


class ProfiledClient:
    """Wraps a chat client: the detection prompt gets the profile's local rules; every other call is unchanged."""

    def __init__(self, inner, profile):
        self.inner, self.profile = inner, profile
        self._addition = profile.prompt_addition()

    model = property(lambda self: self.inner.model)
    params = property(lambda self: {**self.inner.params, "site": self.profile.digest()})

    def __getattr__(self, name):  # max_output_tokens and the like
        return getattr(self.inner, name)

    def complete(self, messages, **kwargs):
        if messages and DETECTION_MARK in messages[0]["content"]:
            messages = [{**messages[0], "content": messages[0]["content"] + "\n\n" + self._addition}, *messages[1:]]
        return self.inner.complete(messages, **kwargs)


def wrap(client, profile):
    return client if profile is None or profile.empty() else ProfiledClient(client, profile)
