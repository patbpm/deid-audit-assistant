"""Turn a written note into what a clinician might dictate, keeping track of the
identifiers. Used only to build synthetic test audio.

Identifiers are spoken the way people read them out: numbers and codes digit by
digit, dates as month, day and year, emails with "at" and "dot". The truth
record keeps both the written and the spoken form of each identifier.
"""

import re

from deid.replace import dates

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]


def spoken_form(kind, text):
    if kind in ("ID", "PHONE"):
        return " ".join(ch.upper() if ch.isalpha() else ch for ch in text if ch.isalnum())
    if kind == "EMAIL":
        local, _, domain = text.partition("@")
        say = lambda s: s.replace(".", " dot ").replace("_", " underscore ").replace("+", " plus ").replace("-", " dash ")
        return f"{say(local)} at {say(domain)}"
    if kind == "DATE":
        try:
            p = dates.parse_date(text)
        except dates.DateError:
            return text
        return f"{MONTHS[p.month - 1]} {p.day}" + (f", {p.year}" if p.has_year else "")
    if kind == "NAME":
        return text.replace("-", " ")
    return text


def dictate(text, spans):
    """-> (script, gold) where gold is [{"type", "written", "spoken"}] in note order."""
    parts, gold, cursor = [], [], 0
    for s in sorted(spans, key=lambda s: s["start"]):
        parts.append(text[cursor:s["start"]])
        written = text[s["start"]:s["end"]]
        spoken = spoken_form(s["type"], written)
        parts.append(spoken)
        gold.append({"type": s["type"], "written": written, "spoken": spoken})
        cursor = s["end"]
    parts.append(text[cursor:])
    script = re.sub(r"[ \t]*\n+[ \t]*", ". ", "".join(parts).strip())
    script = re.sub(r"([.:;,])\s*\.", r"\1", script)
    return re.sub(r"\s{2,}", " ", script), gold
