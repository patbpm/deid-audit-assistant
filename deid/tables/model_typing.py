"""Ask a model what the columns the rules could not place hold; let the rules veto it.

The model sees each unplaced column's header and a few distinct values and names
a type. Its answer is only accepted if the values pass the same check the rules
use for that type; for a type that is kept as is (SAFE, STATE) the check is
stricter, so a model that calls an identifier column "safe" cannot get it through:
the values must be plain numbers or a few short categories, with nothing that looks
like an email, phone, date, id or name. Anything the rules refuse stays UNKNOWN and
is withheld. This sends sample cell values to a hosted model: synthetic tables only.
"""

import json
import re
from collections import Counter

from deid.detect.detector import FENCE, Cache, ParseError

from .columns import ACTIONS, CHECKS, EMAIL, MIN_SHARE, SSN, TYPES, is_date

PROMPT_VERSION = "ct1"
SAMPLES = 8
SAMPLE_WIDTH = 40

SYSTEM = """You help de-identify tables of synthetic patient data. For each column below (a header and a few example values), say what the column holds. Types:
- KEY: an identifier that links rows to one patient or subject
- ID: another identifier: a record, account, insurance, social security or visit number
- NAME: a person's name
- DATE: a date
- PHONE: a phone or fax number
- EMAIL: an email address
- STREET: a street address line
- TOWN: a city or town
- ZIP: a postal code
- STATE: a state or region code
- AGE: an age in years
- FREETEXT: sentences or notes
- SAFE: a value that cannot identify anyone: a plain amount or count, a short code or category (sex, a diagnosis code, a length of stay)
- UNKNOWN: you cannot tell

When unsure between SAFE and an identifier type, choose the identifier type or UNKNOWN. You are not giving medical advice.

Reply with JSON only, in this form:
{"columns": [{"name": "<column name>", "type": "<one of the types>", "why": "<one short sentence>"}]}
Give one entry for every column."""


def samples_of(values):
    counts = Counter(v.strip() for v in values if v.strip())
    return [v[:SAMPLE_WIDTH] for v, _ in counts.most_common(SAMPLES)]


def build_messages(columns):
    """columns: [(name, [values])]. Only headers and a few distinct values are sent."""
    lines = [f"- name: {json.dumps(name)}; examples: {json.dumps(samples_of(values))}" for name, values in columns]
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "Columns:\n" + "\n".join(lines)}]


def parse_types(content):
    text = FENCE.sub("", content.strip())
    for candidate in (text, text[text.find("{"): text.rfind("}") + 1]):
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict) and isinstance(data.get("columns"), list):
            out = {}
            for item in data["columns"]:
                if isinstance(item, dict) and isinstance(item.get("name"), str):
                    kind = str(item.get("type", "")).strip().upper()
                    out[item["name"]] = (kind if kind in TYPES else "UNKNOWN", str(item.get("why", ""))[:200])
            return out
    raise ParseError("no JSON column types in reply")


def safe_ok(values):
    """The strict test for a column that would be kept as it is."""
    values = [v.strip() for v in values if v.strip()]
    if not values:
        return False
    if any(EMAIL.fullmatch(v) or SSN.fullmatch(v) or is_date(v) for v in values):
        return False
    numeric = all(re.fullmatch(r"-?\d+(\.\d+)?", v) and len(v) <= 12 for v in values)
    categories = len(set(values)) <= 20 and all(len(v) <= 20 for v in values) and \
        not any(CHECKS["NAME"](v) and " " in v for v in values) and not any(CHECKS["PHONE"](v) for v in values)
    short_ids = any(len(v) >= 6 and re.fullmatch(r"(?=.*\d)(?=.*[A-Za-z])[A-Za-z0-9\-_/]+", v) for v in values)
    return (numeric or categories) and not short_ids


def verify(kind, values):
    """Do the values fit the type the model chose, by the rules' own checks?"""
    values = [v for v in values if v.strip()]
    if kind in ("SAFE", "STATE"):
        return safe_ok(values) if kind == "SAFE" else (
            sum(bool(CHECKS["STATE"](v)) for v in values) / len(values) >= 0.9 and len(set(values)) <= 55)
    check = CHECKS.get(kind)
    return bool(check) and bool(values) and sum(bool(check(v)) for v in values) / len(values) >= MIN_SHARE


def suggest(client, table_rows_by_column, cache=None):
    """-> {column name: (type, why)} from one model call. Raises ParseError on an unreadable reply."""
    columns = list(table_rows_by_column.items())
    messages = build_messages(columns)
    cache = cache or Cache(None, PROMPT_VERSION)
    key = cache.key(client, messages[1]["content"])
    completion = cache.get(key)
    usage = {}
    if completion is None:
        completion = client.complete(messages)
        cache.put(key, completion)
        usage = dict(completion.usage)
    return parse_types(completion.content), usage


def apply_suggestions(plan, rows, suggestions):
    """Fill UNKNOWN columns of a plan from the model's suggestions where the rules agree.
    Returns the number of columns placed. The plan is changed in place."""
    placed = 0
    for c in plan["columns"]:
        if c["type"] != "UNKNOWN" or c["column"] not in suggestions:
            continue
        kind, why = suggestions[c["column"]]
        values = [r[c["index"]] for r in rows if c["index"] < len(r)]
        if kind == "UNKNOWN" or not verify(kind, values):
            c["reason"] += f"; the model suggested {kind} but the rules did not confirm it" if kind != "UNKNOWN" else "; the model could not tell"
            continue
        c.update({"type": kind, "action": ACTIONS[kind], "decided_by": "model, confirmed by the rules",
                  "reason": f"model: {why}"})
        placed += 1
    return placed


def unknown_columns(plan, rows):
    return {c["column"]: [r[c["index"]] for r in rows if c["index"] < len(r)]
            for c in plan["columns"] if c["type"] == "UNKNOWN"}
