"""Apply replacements to notes given detected spans.

    replacer = Replacer(seed)
    replacer.fit(notes)                      # notes: {"text", "spans", "patient_key"?}
    new_text, changes = replacer.apply(note)

Only start, end and type of each span are used. Anything the engine cannot
rewrite safely (a date it cannot parse, an address in an unknown shape) is
replaced with a tag such as [DATE] and flagged for review, never left in place
and never guessed at.
"""

import re
from collections import Counter

from . import dates
from .surrogates import CREDENTIALS, TITLES, Surrogates, number

SHIFT_MIN_DAYS, SHIFT_MAX_DAYS = 30, 365
DEFAULT_YEAR = 2024  # reference year for year-less dates when a note has no other dated text

WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*")  # letters with inner apostrophes (O'Brien)
US_STATES = (
    "Alabama Alaska Arizona Arkansas California Colorado Connecticut Delaware Florida Georgia Hawaii Idaho "
    "Illinois Indiana Iowa Kansas Kentucky Louisiana Maine Maryland Massachusetts Michigan Minnesota "
    "Mississippi Missouri Montana Nebraska Nevada Ohio Oklahoma Oregon Pennsylvania Tennessee Texas Utah "
    "Vermont Virginia Washington Wisconsin Wyoming").split() + ["New Hampshire", "New Jersey", "New Mexico",
    "New York", "North Carolina", "North Dakota", "Rhode Island", "South Carolina", "South Dakota",
    "West Virginia", "District of Columbia"]
STATE = r"(?:[A-Z]{2}|" + "|".join(sorted(US_STATES, key=len, reverse=True)) + r")"
ZIP = r"(?:\s+(?P<zip>\d{5}(?:-\d{4})?))?"
UNIT = r"(?:Apt|Unit|Suite|Ste)\.?\s*#?\s*\w+"
STREET = re.compile(
    rf"(?:(?P<unit1>{UNIT}),\s*)?"
    r"(?P<num>\d+)\s+(?P<street>[A-Za-z][A-Za-z .'\-]*?)\s+"
    r"(?P<type>St|Ave|Dr|Rd|Ln|Blvd|Ct|Way|Street|Avenue|Drive|Road|Lane|Boulevard|Court)\.?"
    rf"(?:,?\s+(?P<unit>{UNIT}|#\s*\w+))?"
    rf",\s*(?P<town>[A-Za-z][A-Za-z .'\-]*?),?\s+(?P<state>{STATE}){ZIP}")
PO_BOX = re.compile(
    r"(?P<po>P\.?\s?O\.?\s+Box)\s+(?P<num>\d+),\s*(?P<town>[A-Za-z][A-Za-z .'\-]*?),?\s+"
    rf"(?P<state>{STATE}){ZIP}")
TOWN_STATE = re.compile(rf"(?P<town>[A-Za-z][A-Za-z .'\-]*?),\s*(?P<state>{STATE})")
TOWN_ONLY = re.compile(r"[A-Za-z][A-Za-z .'\-]*")
TAGS = {"NAME": "[NAME]", "DATE": "[DATE]", "ID": "[ID]", "PHONE": "[PHONE]",
        "EMAIL": "[EMAIL]", "ADDRESS": "[ADDRESS]"}


def clean_spans(text, spans):
    """Keep start/end/type only; drop empties and overlaps (the longer span wins)."""
    items = []
    for s in spans:
        start, end = int(s["start"]), int(s["end"])
        if 0 <= start < end <= len(text) and s["type"] in TAGS:
            items.append({"start": start, "end": end, "type": s["type"]})
    items.sort(key=lambda s: (-(s["end"] - s["start"]), s["start"]))
    kept = []
    for s in items:
        if not any(s["start"] < k["end"] and k["start"] < s["end"] for k in kept):
            kept.append(s)
    return sorted(kept, key=lambda s: s["start"])


def name_words(text):
    """Words of a name span that are not titles or credentials."""
    return [m.group(0) for m in WORD.finditer(text)
            if m.group(0).lower().rstrip(".") not in TITLES | CREDENTIALS]


class Replacer:
    def __init__(self, seed=0):
        self.seed = seed
        self.kinds = {}  # lowercase name token -> "first" | "last" | "either"
        self.surrogates = Surrogates(seed)
        self.offsets = {}  # patient key -> days

    # --- fitting: decide which name tokens are first names and which are surnames
    def fit(self, notes):
        evidence = {}
        real_tokens = set()
        for note in notes:
            for s in clean_spans(note["text"], note["spans"]):
                if s["type"] != "NAME":
                    continue
                text = note["text"][s["start"]:s["end"]]
                words = name_words(text)
                real_tokens.update(w.lower() for w in words if len(w) > 1)
                self._collect_evidence(text, words, evidence)
        for token, kinds in evidence.items():
            self.kinds[token] = "last" if "last" in kinds else "first"
        for token in real_tokens:
            self.kinds.setdefault(token, "either")
        self.surrogates = Surrogates(self.seed, real_tokens)
        return self

    @staticmethod
    def _collect_evidence(text, words, evidence):
        if len([w for w in words if len(w) > 1]) < 2:
            return
        if "," in text:  # "Last, First M"
            head, _, tail = text.partition(",")
            last = [w for w in name_words(head) if len(w) > 1]
            first = [w for w in name_words(tail) if len(w) > 1][:1]
        else:  # "First [M] Last"
            multi = [w for w in words if len(w) > 1]
            first, last = multi[:1], multi[-1:]
        for w in first:
            evidence.setdefault(w.lower(), set()).add("first")
        for w in last:
            evidence.setdefault(w.lower(), set()).add("last")

    def extend(self, notes):
        """Learn from more notes without changing anything already decided: a name token keeps the kind and
        the stand-in it already has, new tokens get theirs. For a feed where notes arrive over time (fit()
        needs the whole batch up front). Returns the real name tokens that are already someone else's
        stand-in; they cannot be taken back, so a person should know."""
        evidence, real_tokens = {}, set()
        for note in notes:
            for s in clean_spans(note["text"], note["spans"]):
                if s["type"] != "NAME":
                    continue
                text = note["text"][s["start"]:s["end"]]
                words = name_words(text)
                real_tokens.update(w.lower() for w in words if len(w) > 1)
                self._collect_evidence(text, words, evidence)
        for token, kinds in evidence.items():
            self.kinds.setdefault(token, "last" if "last" in kinds else "first")
        for token in real_tokens:
            self.kinds.setdefault(token, "either")
        return sorted(self.surrogates.forbid(real_tokens))

    def state(self):
        """Everything needed to carry on later with the same stand-ins. Sensitive: never share it."""
        return {"seed": self.seed, "kinds": dict(self.kinds), "offsets": dict(self.offsets),
                "surrogates": self.surrogates.state()}

    @classmethod
    def from_state(cls, state):
        replacer = cls(state["seed"])
        replacer.kinds = dict(state["kinds"])
        replacer.offsets = {k: int(v) for k, v in state["offsets"].items()}
        replacer.surrogates.load(state["surrogates"])
        return replacer

    # --- dates ------------------------------------------------------------------
    def date_offset(self, patient_key):
        if patient_key not in self.offsets:
            span = SHIFT_MAX_DAYS - SHIFT_MIN_DAYS + 1
            h = number(self.seed, "shift", patient_key)
            days = SHIFT_MIN_DAYS + h % span
            self.offsets[patient_key] = days if (h >> 40) % 2 else -days
        return self.offsets[patient_key]

    # --- applying -----------------------------------------------------------------
    def apply(self, note):
        text = note["text"]
        spans = clean_spans(text, note["spans"])
        key = note.get("patient_key") or note.get("note_id") or "unkeyed"
        ref_year = self._reference_year(text, spans)
        changes, out, cursor, delta = [], [], 0, 0
        for s in spans:
            original = text[s["start"]:s["end"]]
            body = original.strip()
            lead = original[:len(original) - len(original.lstrip())]
            trail = original[len(original.rstrip()):]
            replacement, rule, flagged = self._replace(s["type"], body, key, ref_year)
            replacement = lead + replacement + trail
            out.append(text[cursor:s["start"]])
            out.append(replacement)
            new_start = s["start"] + delta
            changes.append({
                "start": s["start"], "end": s["end"], "new_start": new_start,
                "new_end": new_start + len(replacement), "type": s["type"],
                "original": original, "replacement": replacement, "rule": rule, "flagged": flagged,
            })
            delta += len(replacement) - (s["end"] - s["start"])
            cursor = s["end"]
        out.append(text[cursor:])
        new_text = "".join(out)
        for c in changes:  # offsets must point at exactly what was written
            assert new_text[c["new_start"]:c["new_end"]] == c["replacement"]
        return new_text, changes

    def _reference_year(self, text, spans):
        years = Counter()
        for s in spans:
            if s["type"] == "DATE":
                try:
                    p = dates.parse_date(text[s["start"]:s["end"]])
                except dates.DateError:
                    continue
                if p.has_year:
                    years[p.year] += 1
        return years.most_common(1)[0][0] if years else DEFAULT_YEAR

    def _replace(self, kind, body, key, ref_year):
        try:
            return getattr(self, "_" + kind.lower())(body, key, ref_year)
        except (dates.DateError, ValueError):
            return TAGS[kind], "fallback-tag", True

    def _date(self, body, key, ref_year):
        parsed = dates.parse_date(body)
        moved = dates.shift(parsed, self.date_offset(key), ref_year)
        rule = "date-shift" + ("" if parsed.has_year else "-no-year") \
            + ("-assumed-month-first" if parsed.assumed_month_first else "")             + ("-assumed-day-first" if parsed.assumed_day_first else "")
        return dates.render(moved), rule, False

    def _name(self, body, key, ref_year):
        if not name_words(body):
            return TAGS["NAME"], "fallback-tag", True

        def swap(m):
            word = m.group(0)
            if word.lower().rstrip(".") in TITLES | CREDENTIALS:
                return word
            if len(word) == 1:
                return self.surrogates.initial(word)
            return self.surrogates.name_token(word, self.kinds.get(word.lower(), "either"))

        return WORD.sub(swap, body), "name-token", False

    def _id(self, body, key, ref_year):
        return self.surrogates.identifier(body), "id-format-preserving", False

    def _phone(self, body, key, ref_year):
        return self.surrogates.phone(body), "phone-fictional", False

    def _email(self, body, key, ref_year):
        return self.surrogates.email(body), "email-example-domain", False

    def _address(self, body, key, ref_year):
        s = self.surrogates
        m = PO_BOX.fullmatch(body)
        if m:
            tail = f"{s.town_name(m['town'])}, {m['state']}"
            if m["zip"]:
                tail += " " + s.digits(m["zip"], "zip")
            return f"{m['po']} {s.digits(m['num'], 'pobox')}, {tail}", "address-po-box", False
        m = STREET.fullmatch(body)
        if m:
            parts = [s.digits(m["num"], "num"), s.street_name(m["street"]), m["type"]]
            street = " ".join(parts) + ("." if body[m.end("type"):m.end("type") + 1] == "." else "")
            if m["unit"]:
                street += ", " + re.sub(r"\w+$", lambda u: s.digits(u.group(0), "unit"), m["unit"])
            if m["unit1"]:
                street = re.sub(r"\w+$", lambda u: s.digits(u.group(0), "unit"), m["unit1"]) + ", " + street
            tail = f"{s.town_name(m['town'])}, {m['state']}"
            if m["zip"]:
                tail += " " + s.digits(m["zip"], "zip")
            return f"{street}, {tail}", "address-structured", False
        m = TOWN_STATE.fullmatch(body)
        if m:
            return f"{s.town_name(m['town'])}, {m['state']}", "address-town", False
        if TOWN_ONLY.fullmatch(body):
            return s.town_name(body), "address-town", False
        return TAGS["ADDRESS"], "fallback-tag", True

    def replace_value(self, kind, value, key, ref_year=DEFAULT_YEAR):
        """Replace one standalone value of a NAME, DATE, PHONE, EMAIL, ID or ADDRESS
        type (a table cell, not a span in a note). -> (replacement, rule, flagged)."""
        return self._replace(kind, value.strip(), key, ref_year)

    # --- audit -----------------------------------------------------------------------
    def key_tables(self):
        """Everything needed to reverse the mapping. Sensitive: never share it."""
        s = self.surrogates
        return {
            "seed": self.seed, "date_offsets_days": dict(self.offsets),
            "first": s.first.table, "last": s.last.table, "either": s.either.table,
            "street": s.street.table, "town": s.town.table, "ids": dict(s.ids),
        }
