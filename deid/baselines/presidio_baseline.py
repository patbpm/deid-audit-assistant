"""Microsoft Presidio baseline with default settings.

    python -m deid.baselines.presidio_baseline --out runs/presidio.jsonl

Uses AnalyzerEngine() as shipped: spaCy en_core_web_lg, default recognizers,
default score threshold (0, so every candidate is kept), language "en". No
tuning. Presidio entity types are mapped onto this project's six types; entity
types with no counterpart (URL, IP_ADDRESS, NRP, IBAN_CODE, CRYPTO) are
dropped and counted in the printed summary.
"""

import argparse
from collections import Counter

from .common import read_notes, write_predictions

ENTITY_TO_TYPE = {
    "PERSON": "NAME",
    "DATE_TIME": "DATE",
    "PHONE_NUMBER": "PHONE",
    "EMAIL_ADDRESS": "EMAIL",
    "LOCATION": "ADDRESS",
    "US_SSN": "ID",
    "US_ITIN": "ID",
    "US_PASSPORT": "ID",
    "US_DRIVER_LICENSE": "ID",
    "US_BANK_NUMBER": "ID",
    "MEDICAL_LICENSE": "ID",
    "CREDIT_CARD": "ID",
}


def detect(analyzer, text, dropped):
    spans = []
    for result in analyzer.analyze(text=text, language="en"):
        label = ENTITY_TO_TYPE.get(result.entity_type)
        if label is None:
            dropped[result.entity_type] += 1
            continue
        spans.append({"start": result.start, "end": result.end, "type": label})
    return sorted(spans, key=lambda s: (s["start"], s["end"], s["type"]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--notes", default="data/generated/notes.jsonl")
    parser.add_argument("--out", default="runs/presidio.jsonl")
    args = parser.parse_args(argv)

    from presidio_analyzer import AnalyzerEngine  # heavy import, kept out of module load

    analyzer = AnalyzerEngine()
    dropped = Counter()
    notes = read_notes(args.notes)
    write_predictions({n["note_id"]: detect(analyzer, n["text"], dropped) for n in notes}, args.out)
    print(f"wrote predictions for {len(notes)} notes to {args.out}")
    print(f"dropped (no matching project type): {dict(dropped)}")


if __name__ == "__main__":
    main()
