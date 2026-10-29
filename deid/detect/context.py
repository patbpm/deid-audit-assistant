"""Closed-list rules about where a listed string is, and what it is not.

Two jobs, both applied to the model's output before offsets are recovered:

- A DATE that is only a year ("2019") or a relative expression ("last Tuesday",
  "tomorrow", "3 days ago") is not an identifier under the dataset's rules, and
  HIPAA's Safe Harbor list also leaves a bare year alone. These are set aside and
  recorded, never silently dropped.
- An occurrence of a listed NAME that is directly followed by the noun of an
  eponym ("Wilson disease", "Foley catheter") is the name of a condition or a
  device, not a person, unless a title or a label such as "Dr." or "Patient:"
  comes right before it.

The lists are short on purpose and were written from the kinds of text seen so
far, so they are a floor, not a claim to cover every phrasing. Anything they miss
falls back on the prompt and the occurrence check (deid.agent.nameuse).
"""

import re

WEEKDAY = r"(?:Mon|Tues?|Wed(?:nes)?|Thu(?:rs?)?|Fri|Sat(?:ur)?|Sun)(?:day)?"
UNIT = r"(?:day|week|month|year|hour|minute)s?"
SPAN = r"(?:day|week|month|year)"
NUMBER = r"(?:\d{1,3}|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|several|few|couple of)"

RELATIVE = re.compile(
    r"^(?:"
    r"today|tomorrow|yesterday|tonight|"
    r"(?:this|last|next|every|early|late)\s+(?:morning|afternoon|evening|night|weekend|" + SPAN + r"|" + WEEKDAY + r")|"
    r"(?:on\s+)?(?:last|next|this|coming|past)\s+" + WEEKDAY + r"|"
    r"(?:the\s+)?" + SPAN + r"\s+(?:before|after)(?:\s+(?:that|last|yesterday))?|"
    r"(?:the\s+)?(?:previous|following|next|last)\s+" + SPAN + r"|"
    + NUMBER + r"\s+" + UNIT + r"\s+(?:ago|later|earlier|from now|before|after)|"
    r"in\s+" + NUMBER + r"\s+" + UNIT + r"|"
    r"(?:earlier|later)\s+(?:today|this\s+(?:week|month|year))"
    r")$", re.IGNORECASE)
YEAR_ONLY = re.compile(r"^(?:in\s+|since\s+|during\s+|of\s+)?(?:19|20)\d{2}$", re.IGNORECASE)
YEAR_RANGE = re.compile(r"^(?:19|20)\d{2}\s*[-–]\s*(?:19|20)?\d{2}$")


def set_aside_reason(string, kind):
    """Why a listed string is not an identifier for its type, or None if it may be."""
    if kind != "DATE":
        return None
    text = " ".join(string.split()).strip(" .,;:")
    if YEAR_ONLY.match(text) or YEAR_RANGE.match(text):
        return "a year on its own is not treated as an identifier"
    if RELATIVE.match(text):
        return "a relative date (no calendar day) is not treated as an identifier"
    return None


# A title or label right before a name. Case-insensitive: "patient:" and "PATIENT:" both count.
CUE_BEFORE = re.compile(
    r"\b(?:dr|mr|mrs|ms|miss|mx|prof|rev|sr|nurse|rn|np|pa|md|do|pt|patient|name|"
    r"mother|father|mom|dad|daughter|son|wife|husband|spouse|partner|sister|brother|"
    r"aunt|uncle|grandmother|grandfather|guardian|contact|clinician|physician|provider|surgeon)"
    r"\b\.?[ \t]*:?[ \t]*$", re.IGNORECASE)
LAST_FIRST_AFTER = re.compile(r"^,[ \t]+[A-Z][a-z]")

EPONYM_NOUNS = (
    "disease", "diseases", "syndrome", "syndromes", "catheter", "catheters", "palsy", "lymphoma",
    "phenomenon", "encephalopathy", "sign", "signs", "test", "score", "scale", "cyst", "cysts",
    "maneuver", "manoeuvre", "reflex", "triad", "criteria", "classification", "tumor", "tumour",
    "fracture", "ulcer", "node", "nodes", "gland", "duct", "ligament", "tendon", "valve", "flap",
    "pouch", "murmur")
EPONYM_AFTER = re.compile(r"^(?:['’]s)?[ \t]+(?:" + "|".join(EPONYM_NOUNS) + r")\b", re.IGNORECASE)


def has_cue_before(text, start):
    return bool(CUE_BEFORE.search(text[max(0, start - 40):start]))


def is_eponym_use(text, start, end):
    """True if this occurrence names a condition or device (followed by its noun) and no title or label
    says it is a person."""
    if has_cue_before(text, start) or LAST_FIRST_AFTER.match(text[end:end + 12]):
        return False
    return bool(EPONYM_AFTER.match(text[end:end + 24]))
