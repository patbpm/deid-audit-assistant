"""Decide what each column of a table holds, from its header and its values.

    plan = build_plan("patients.csv", header, rows)

The result is a plan a person can read and edit before anything is changed:
for every column a type, how it was decided, and the action that will follow.
A column the rules cannot place is UNKNOWN, and by default its values are
withheld rather than guessed at. Types: KEY (a patient identifier that links
rows, and groups dates), ID, NAME, DATE, PHONE, EMAIL, STREET, TOWN, STATE, ZIP,
AGE, FREETEXT, SAFE (kept as is), UNKNOWN.
"""

import re

from deid.replace import dates

ACTIONS = {"KEY": "replace", "ID": "replace", "NAME": "replace", "DATE": "replace", "PHONE": "replace",
           "EMAIL": "replace", "STREET": "replace", "TOWN": "replace", "ZIP": "replace", "STATE": "keep",
           "AGE": "age", "FREETEXT": "freetext", "SAFE": "keep", "UNKNOWN": "withhold"}
TYPES = tuple(ACTIONS)
MIN_SHARE = 0.8

HINTS = [  # (type, header words); the first rule whose words appear wins
    ("FREETEXT", {"comment", "comments", "note", "notes", "remarks", "narrative", "description", "summary", "history", "text"}),
    ("EMAIL", {"email", "mail"}),
    ("PHONE", {"phone", "tel", "telephone", "mobile", "cell", "fax"}),
    ("DATE", {"date", "dt", "dob", "birth", "birthdate", "birthday", "admit", "admitted", "admission", "disch",
              "discharge", "discharged", "died", "death"}),
    ("NAME", {"name", "nm", "surname", "lastname", "firstname", "fname", "lname", "attending", "physician",
              "doctor", "provider", "clinician", "nurse"}),
    ("ZIP", {"zip", "zipcode", "postal", "postcode"}),
    ("STREET", {"street", "addr", "address", "address1", "line1"}),
    ("TOWN", {"city", "town", "municipality"}),
    ("STATE", {"state", "province"}),
    ("AGE", {"age"}),
    ("SAFE", {"sex", "gender", "code", "dx", "icd", "diagnosis", "charges", "charge", "cost", "amount", "los",
              "stay", "status", "count"}),
    ("ID", {"id", "mrn", "ssn", "account", "acct", "insurance", "ins", "policy", "accession", "record", "enc",
            "encounter"}),
]
KEY_WORDS, KEY_ID_WORDS = {"patient", "pt", "subject", "person", "pat"}, {"id", "no", "number", "num"}
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
PHONE = re.compile(r"\+?[\d\s().\-]{7,22}")
SSN = re.compile(r"\d{3}-\d{2}-\d{4}")
ZIP = re.compile(r"\d{5}(?:-\d{4})?")
STATE = re.compile(r"[A-Z]{2}")
STREET = re.compile(r"\d+\s+[A-Za-z][\w .,#'\-]*")
NAME = re.compile(r"(?:(?:Dr|Mr|Mrs|Ms|Prof)\.?\s+)?[A-Za-z][A-Za-z.'\-]*(?:[ ,]+[A-Za-z][A-Za-z.'\-]*){0,3}")
IDLIKE = re.compile(r"(?=.*\d)[A-Za-z0-9][A-Za-z0-9\-_/]{3,}")        # for guessing from values alone
IDLIKE_SHORT = re.compile(r"(?=.*\d)[A-Za-z0-9][A-Za-z0-9\-_/]+")      # when the header already says it is an id


def header_words(header):
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", header or "")
    return re.findall(r"[a-z]+|\d+", spaced.lower())


def header_hint(header):
    words = set(header_words(header))
    compact = re.sub(r"[^a-z]", "", (header or "").lower())
    if (words & KEY_WORDS and words & KEY_ID_WORDS) or compact in {"patientid", "ptid", "pid", "subjectid", "patid"}:
        return "KEY"
    for kind, hint in HINTS:
        if words & hint or compact in hint:
            return kind
    return None


def share(values, test):
    return sum(bool(test(v)) for v in values) / len(values) if values else 0.0


def is_date(v):
    try:
        dates.parse_date(v)
        return True
    except dates.DateError:
        return False


def is_int(v, low=0, high=130):
    return v.strip().isdigit() and low <= int(v) <= high


CHECKS = {
    "EMAIL": lambda v: EMAIL.fullmatch(v), "DATE": is_date,
    "PHONE": lambda v: (PHONE.fullmatch(v) and not re.fullmatch(r"\d+\.\d+", v)    # 27701.51 is an amount, not a phone
                         and 7 <= len(re.sub(r"\D", "", v)) <= 15 and not is_date(v)
                        and (re.search(r"[\s().+\-]", v) or len(re.sub(r"\D", "", v)) >= 10)),
    "NAME": lambda v: NAME.fullmatch(v) and not any(c.isdigit() for c in v) and len(v) >= 3,
    "ZIP": lambda v: ZIP.fullmatch(v), "STATE": lambda v: STATE.fullmatch(v),
    "STREET": lambda v: STREET.fullmatch(v), "TOWN": lambda v: re.fullmatch(r"[A-Za-z][A-Za-z .'\-]+", v),
    "AGE": is_int, "KEY": lambda v: IDLIKE_SHORT.fullmatch(v), "ID": lambda v: IDLIKE_SHORT.fullmatch(v),
    "FREETEXT": lambda v: len(v) >= 25 and " " in v,
    "SAFE": lambda v: len(v) <= 40 and not EMAIL.fullmatch(v) and not SSN.fullmatch(v),
}


def value_type(values):
    """Best guess from the values alone, or None."""
    if share(values, lambda v: SSN.fullmatch(v)) >= MIN_SHARE:
        return "ID"  # before PHONE: nine digits with dashes would also look like a phone number
    for kind in ("EMAIL", "PHONE", "DATE"):
        if share(values, CHECKS[kind]) >= MIN_SHARE:
            return kind
    if share(values, CHECKS["STATE"]) >= 0.9 and len(set(values)) <= 55:
        return "STATE"
    if share(values, CHECKS["STREET"]) >= MIN_SHARE:
        return "STREET"
    avg = sum(map(len, values)) / len(values) if values else 0
    if avg >= 25 and share(values, CHECKS["FREETEXT"]) >= MIN_SHARE:
        return "FREETEXT"
    if share(values, CHECKS["NAME"]) >= MIN_SHARE and share(values, lambda v: "," in v or " " in v) >= MIN_SHARE:
        return "NAME"
    if share(values, lambda v: IDLIKE.fullmatch(v)) >= MIN_SHARE:
        return "ID"
    return None


def classify(header, values):
    """-> (type, confidence, reason, share of values that fit the type)."""
    hint = header_hint(header)
    if hint:
        fit = share(values, CHECKS[hint])
        if fit >= MIN_SHARE:
            return hint, "header and values", f"header suggests {hint}; {fit:.0%} of values fit", fit
        return "UNKNOWN", "conflict", f"header suggests {hint} but only {fit:.0%} of values fit", fit
    guess = value_type(values)
    if guess:
        return guess, "values only", f"no header hint; values look like {guess}", share(values, CHECKS[guess])
    return "UNKNOWN", "none", "no header hint and the values fit no known type", 0.0


def pick_key(columns, rows):
    """Name the column that links rows to a patient: a KEY, else the repeating ID column."""
    for c in columns:
        if c["type"] == "KEY":
            return c["column"], "header"
    ids = [c for c in columns if c["type"] == "ID"]
    for c in ids:
        values = [r[c["index"]] for r in rows if r[c["index"]]]
        if values and len(set(values)) < len(values):
            return c["column"], "guessed: the ID column whose values repeat"
    if ids:
        return ids[0]["column"], "guessed: the first ID column"
    return None, "none: dates move independently for each row"


def build_plan(name, header, rows, overrides=None):
    """header: list of names, or None for a headerless table; rows: lists of strings."""
    width = len(rows[0]) if rows else len(header or [])
    names = list(header) if header else [f"col{i + 1}" for i in range(width)]
    columns = []
    for i, col in enumerate(names):
        values = [r[i] for r in rows if i < len(r) and r[i].strip()]
        kind, how, reason, fit = classify(col if header else None, values)
        if overrides and col in overrides:
            kind, how, reason = overrides[col], "set by hand", "set in the plan file"
        columns.append({"index": i, "column": col, "type": kind, "action": ACTIONS[kind], "decided_by": how,
                        "reason": reason, "fit": round(fit, 3)})
    key, why = pick_key(columns, rows)
    return {"table": name, "has_header": bool(header), "key_column": key, "key_reason": why, "columns": columns}
