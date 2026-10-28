"""Check the replacement engine against the synthetic ground truth.

    python -m deid.replace.check --split dev --out results/dev/replace-dev.json

The engine is given the true spans, so this measures replacement, not detection.
Only start/end/type reach the engine; the true entity ids and ISO dates are used
here, afterwards, to judge the output.
"""

import argparse
import json
import re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from deid.baselines.common import read_notes
from deid.eval.run import split_of

from . import dates
from .engine import WORD, Replacer, name_words
from .surrogates import number


def shape(text):
    """Character-class pattern: 9 digit, A upper, a lower, anything else as is."""
    return re.sub(r"[a-z]", "a", re.sub(r"[A-Z]", "A", re.sub(r"\d", "9", text)))


def run_checks(notes, seed=0):
    replacer = Replacer(seed).fit(
        [{"text": n["text"], "spans": n["spans"]} for n in notes])
    outputs = {}
    for n in notes:
        text, changes = replacer.apply(
            {"text": n["text"], "spans": n["spans"], "patient_key": n["patient_id"], "note_id": n["note_id"]})
        outputs[n["note_id"]] = (text, changes)

    report = {"notes": len(notes), "seed": seed}
    report["spans"] = sum(len(c) for _, c in outputs.values())
    report["flagged"] = sum(ch["flagged"] for _, c in outputs.values() for ch in c)

    # 1. Original identifiers still present in the output of the same note.
    leaks = defaultdict(list)
    for n in notes:
        out = outputs[n["note_id"]][0]
        for s in n["spans"]:
            if s["type"] == "NAME":
                pieces = [w for w in name_words(s["text"]) if len(w) >= 3]
            elif s["type"] in ("ID", "PHONE", "EMAIL", "ADDRESS"):
                pieces = [s["text"]]
            else:
                continue
            for piece in pieces:
                if re.search(rf"(?<![A-Za-z0-9]){re.escape(piece)}(?![A-Za-z0-9])", out):
                    leaks[s["type"]].append((n["note_id"], piece))
    report["leaked_strings_by_type"] = {t: len(v) for t, v in sorted(leaks.items())}
    report["leak_examples"] = {t: sorted(set(p for _, p in v))[:10] for t, v in sorted(leaks.items())}

    # 2. Dates: one shift per patient, so intervals are unchanged.
    deltas, bad_dates, checked, yearless_checked, yearless_bad = defaultdict(set), 0, 0, 0, 0
    for n in notes:
        for s, c in zip(n["spans"], outputs[n["note_id"]][1]):
            if s["type"] != "DATE" or c["flagged"]:
                continue
            true = date.fromisoformat(s["norm"])
            moved = dates.parse_date(c["replacement"])
            if moved.has_year:
                checked += 1
                deltas[n["patient_id"]].add((dates.to_date(moved, None) - true).days)
            else:
                yearless_checked += 1
                expected = true + timedelta(days=replacer.date_offset(n["patient_id"]))
                yearless_bad += (moved.month, moved.day) != (expected.month, expected.day)
    bad_dates = sum(1 for d in deltas.values() if len(d) != 1)
    report["dates"] = {
        "full_dates_checked": checked, "patients": len(deltas),
        "patients_with_inconsistent_shift": bad_dates,
        "shift_matches_offset": all(
            d == {replacer.date_offset(p)} for p, d in deltas.items()),
        "yearless_checked": yearless_checked, "yearless_mismatches": yearless_bad,
        "shift_range_days": [min(replacer.offsets.values()), max(replacer.offsets.values())],
    }

    # 3. Names: one real token -> one surrogate token; distinct tokens stay distinct.
    token_map = defaultdict(set)
    entity_forms = defaultdict(lambda: defaultdict(set))
    for n in notes:
        for s, c in zip(n["spans"], outputs[n["note_id"]][1]):
            if s["type"] != "NAME":
                continue
            real = [w.lower() for w in name_words(s["text"])]  # initials map by letter, not injectively
            fake = [w.lower() for w in name_words(c["replacement"])]
            if len(real) != len(fake):
                continue
            for r, f in zip(real, fake):
                if len(r) < 2:
                    continue
                token_map[r].add(f)
                entity_forms[s["entity"]][r].add(f)
    reverse = defaultdict(set)
    for r, fs in token_map.items():
        for f in fs:
            reverse[f].add(r)
    real_tokens = set(token_map)
    report["names"] = {
        "real_tokens": len(token_map),
        "tokens_with_several_surrogates": sum(len(v) > 1 for v in token_map.values()),
        "surrogates_shared_by_several_tokens": sum(len(v) > 1 for v in reverse.values()),
        "surrogates_equal_to_a_real_token": len(set(reverse) & real_tokens),
        "people": len(entity_forms),
        "people_with_inconsistent_tokens": sum(
            any(len(f) > 1 for f in forms.values()) for forms in entity_forms.values()),
    }

    # 4. Shapes survive and the text outside identifiers is untouched.
    shape_changes, outside_changed = 0, 0
    for n in notes:
        text, changes = outputs[n["note_id"]]
        for s, c in zip(n["spans"], changes):
            if s["type"] in ("PHONE", "ID", "EMAIL") and not c["flagged"]:
                if s["type"] == "ID" and re.fullmatch(r"\d{3}-\d{2}-\d{4}", s["text"]):
                    ok = re.fullmatch(r"9\d{2}-\d{2}-\d{4}", c["replacement"])
                else:
                    ok = shape(c["replacement"]) == shape(s["text"]) if s["type"] != "EMAIL" \
                        else re.fullmatch(r"[a-z0-9.]+@example\.(com|org)", c["replacement"])
                shape_changes += not ok
        keep = lambda t, spans: "".join(
            t[a:b] for a, b in zip([0] + [x[1] for x in spans], [x[0] for x in spans] + [len(t)]))
        old = keep(n["text"], [(s["start"], s["end"]) for s in n["spans"]])
        new = keep(text, [(c["new_start"], c["new_end"]) for c in changes])
        outside_changed += old != new
    report["shapes_not_preserved"] = shape_changes
    report["notes_with_changed_text_outside_spans"] = outside_changed
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--notes", default="data/generated/notes.jsonl")
    parser.add_argument("--split", choices=("dev", "test", "all"), default="dev")
    parser.add_argument("--allow-test", action="store_true")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", default="results/dev/replace-dev.json")
    args = parser.parse_args(argv)
    if args.split != "dev" and not args.allow_test:
        parser.error("develop on dev; pass --allow-test for the final reporting run")
    notes = [n for n in read_notes(args.notes) if args.split == "all" or split_of(n["patient_id"]) == args.split]
    report = run_checks(notes, args.seed)
    report["split"] = args.split
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
