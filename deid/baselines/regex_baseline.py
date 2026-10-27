"""A simple pattern-matching baseline (no model, no names).

    python -m deid.baselines.regex_baseline --out runs/regex.jsonl

CAUTION: these patterns were written knowing the generator's fixed formats
(555-01xx phones, 7-digit MRNs, ACCT/RAD prefixes). Scores therefore show how
easy the synthetic formats are, not how a general regex tool performs on real
notes. Names and year-less dates are deliberately not attempted.
"""

import argparse
import re

from .common import read_notes, write_predictions

MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
MON = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
STREET = r"(?:St|Ave|Dr|Rd|Ln|Blvd|Ct|Way)"

PATTERNS = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]*\w")),
    ("PHONE", re.compile(r"(?:\+1 )?(?:\(\d{3}\) |\d{3}[-.])\d{3}[-.]\d{4}")),
    ("ID", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("ID", re.compile(r"(?<=MRN: )\d{7}\b")),
    ("ID", re.compile(r"\bACCT\d{10}\b")),
    ("ID", re.compile(r"\bRAD-\d{2}-\d{6}\b")),
    ("ID", re.compile(r"\b[A-Z]{3}\d{9}\b")),
    ("DATE", re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")),
    ("DATE", re.compile(r"\b\d{4}-\d{2}-\d{2}\b")),
    ("DATE", re.compile(rf"\b{MONTH} \d{{1,2}}, \d{{4}}\b")),
    ("DATE", re.compile(rf"\b\d{{1,2}} {MON} \d{{4}}\b")),
    (
        "ADDRESS",
        re.compile(
            rf"\b\d{{1,5}} [A-Z][a-z]+ {STREET}\b(?:, (?:Apt|Unit|Suite) \w+)?, [A-Z][A-Za-z ]+, [A-Z]{{2}} \d{{5}}"
        ),
    ),
]


def detect(text):
    spans = []
    for label, pattern in PATTERNS:
        for match in pattern.finditer(text):
            spans.append({"start": match.start(), "end": match.end(), "type": label})
    return sorted(spans, key=lambda s: (s["start"], s["end"]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--notes", default="data/generated/notes.jsonl")
    parser.add_argument("--out", default="runs/regex.jsonl")
    args = parser.parse_args(argv)
    notes = read_notes(args.notes)
    write_predictions({n["note_id"]: detect(n["text"]) for n in notes}, args.out)
    print(f"wrote predictions for {len(notes)} notes to {args.out}")


if __name__ == "__main__":
    main()
