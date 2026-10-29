"""Synthetic patient and encounter tables with ground-truth column types.

    python -m deid.synth.tables [--seed N] [--patients N] [--out DIR]

Writes, for each header style (clean, messy, headerless), a patients table and an
encounters table that share patient ids and MRNs, plus truth.json with every
column's true type and every identifier cell. Separate from the note dataset and
not frozen: it is a development set for the table mode (docs/TABLES.md). Phones
use 555-01xx, SSNs start with 9, emails use example.com and example.org. A few
patients are aged 90 or over, to exercise age aggregation.
"""

import argparse
import csv
import json
import random
from datetime import timedelta
from pathlib import Path

from . import formats, people, pools

DEFAULT_SEED = 20261030
DEFAULT_PATIENTS = 60
STYLES = ("clean", "messy", "unseen", "headerless")

# (clean header, messy header, "unseen" header, type). The unseen headers were written after the
# column rules and are worded differently on purpose; the rules were not adjusted to them.
PATIENT_COLUMNS = [
    ("patient_id", "PT_ID", "Subject", "KEY"), ("mrn", "MRN#", "Chart No", "ID"),
    ("full_name", "Pt Name", "Member", "NAME"), ("dob", "DOB", "Born", "DATE"), ("ssn", "SSN", "SocSec", "ID"),
    ("phone", "Tel", "Contact", "PHONE"), ("email", "e-mail", "Mail", "EMAIL"),
    ("street", "Addr", "Home Street", "STREET"), ("town", "City", "Locality", "TOWN"),
    ("state", "St", "Region", "STATE"), ("zip", "Zip", "PostalCode", "ZIP"), ("age", "Age", "Years", "AGE"),
    ("sex", "Sex", "Gender", "SAFE"), ("insurance_id", "Ins ID", "Coverage ID", "ID"),
]
ENCOUNTER_COLUMNS = [
    ("encounter_id", "Enc#", "Visit Ref", "ID"), ("patient_id", "PT_ID", "Subject", "KEY"),
    ("mrn", "MRN#", "Chart No", "ID"), ("admit_date", "Admitted", "Arrival", "DATE"),
    ("discharge_date", "Disch", "Departure", "DATE"), ("length_of_stay", "LOS", "Days Inpatient", "SAFE"),
    ("attending", "Provider", "Treating MD", "NAME"), ("diagnosis_code", "Dx Code", "ICD", "SAFE"),
    ("charges", "Charges", "Billed", "SAFE"), ("comment", "Remarks", "Free Text", "FREETEXT"),
]
DIAGNOSES = ["I50.9", "J18.9", "L03.115", "E10.10", "K35.80", "N39.0", "I63.9", "J44.1"]
COMMENTS = [
    "Called {kin} at {kin_phone} about the discharge plan.",
    "Patient {name} asked for records to be sent to {email}.",
    "Daughter {kin} will pick up the patient; reachable at {kin_phone}.",
    "Follow-up with the patient's family doctor arranged; no concerns.",
    "Insurance {ins} verified by phone.",
]


def make_tables(seed=DEFAULT_SEED, patients=DEFAULT_PATIENTS):
    """-> (patient rows, encounter rows, identifier cells). Rows are dicts keyed by clean header."""
    rng = random.Random(seed)
    providers = people.make_providers(rng)
    patient_rows, encounter_rows, cells = [], [], []
    old = set(rng.sample(range(patients), max(3, patients // 20)))
    for i in range(patients):
        p = people.make_patient(rng, i + 1, providers)
        dob, age = p.dob, p.age
        if i in old:
            age = rng.randint(90, 99)
            dob = p.admit - timedelta(days=age * 365 + rng.randint(0, 364))
        middle = f" {p.person.middle}" if p.person.middle else ""
        name = f"{p.person.last}, {p.person.first}{middle}"
        a = p.address
        street = f"{a.number} {a.street} {a.street_type}" + (f", {a.unit}" if a.unit else "")
        row = {"patient_id": p.pid, "mrn": p.mrn, "full_name": name, "dob": formats.fmt_date(dob, "iso"),
               "ssn": p.ssn, "phone": formats.fmt_phone(p.phone_cell, "dash"), "email": p.email, "street": street,
               "town": a.town, "state": a.state, "zip": a.zip_code, "age": str(age), "sex": p.person.sex,
               "insurance_id": p.insurance_id}
        patient_rows.append(row)
        for col, kind in (("patient_id", "KEY"), ("mrn", "ID"), ("full_name", "NAME"), ("dob", "DATE"), ("ssn", "ID"),
                          ("phone", "PHONE"), ("email", "EMAIL"), ("street", "STREET"), ("town", "TOWN"),
                          ("zip", "ZIP"), ("insurance_id", "ID")):
            cells.append({"table": "patients", "row": i, "column": col, "type": kind, "value": row[col]})
        for k in range(rng.randint(1, 3)):
            admit = p.admit + timedelta(days=400 * k)
            stay = rng.randint(2, 9)
            kin = f"{p.kin.first} {p.kin.last}"
            kin_phone = formats.fmt_phone(p.kin_phone, "paren")
            comment = rng.choice(COMMENTS).format(kin=kin, kin_phone=kin_phone, name=f"{p.person.first} {p.person.last}",
                                                  email=p.email, ins=p.insurance_id)
            attending = f"Dr. {p.attending.person.last}"
            enc = {"encounter_id": f"E{len(encounter_rows) + 1:06d}", "patient_id": p.pid, "mrn": p.mrn,
                   "admit_date": formats.fmt_date(admit, "iso"),
                   "discharge_date": formats.fmt_date(admit + timedelta(days=stay), "iso"),
                   "length_of_stay": str(stay), "attending": attending, "diagnosis_code": rng.choice(DIAGNOSES),
                   "charges": f"{rng.uniform(1500, 42000):.2f}", "comment": comment}
            encounter_rows.append(enc)
            r = len(encounter_rows) - 1
            for col, kind in (("encounter_id", "ID"), ("patient_id", "KEY"), ("mrn", "ID"), ("admit_date", "DATE"),
                              ("discharge_date", "DATE"), ("attending", "NAME")):
                cells.append({"table": "encounters", "row": r, "column": col, "type": kind, "value": enc[col]})
            for kind, value in (("NAME", kin), ("PHONE", kin_phone), ("EMAIL", p.email), ("ID", p.insurance_id),
                                ("NAME", f"{p.person.first} {p.person.last}")):
                if value in comment:
                    cells.append({"table": "encounters", "row": r, "column": "comment", "type": kind,
                                  "value": value, "inside_text": True})
    return patient_rows, encounter_rows, cells


def render(rows, spec, style):
    """-> (header or None, list of value lists, {output column index/name: true type})."""
    if style == "headerless":
        header = None
        names = [f"col{i + 1}" for i in range(len(spec))]
    else:
        pick = {"clean": 0, "messy": 1, "unseen": 2}[style]
        header = [names_[pick] for *names_, _ in [(c, m, u, k) for c, m, u, k in spec]]
        names = header
    values = [[row[clean] for clean, _, _, _ in spec] for row in rows]
    return header, values, {name: spec_[3] for name, spec_ in zip(names, spec)}


def write_style(out, style, patient_rows, encounter_rows):
    truth = {}
    for table, rows, spec in (("patients", patient_rows, PATIENT_COLUMNS), ("encounters", encounter_rows, ENCOUNTER_COLUMNS)):
        header, values, types = render(rows, spec, style)
        path = Path(out) / style / f"{table}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            if header:
                writer.writerow(header)
            writer.writerows(values)
        truth[table] = {"file": f"{style}/{table}.csv", "has_header": header is not None, "columns": types,
                        "order": list(types)}
    return truth


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--patients", type=int, default=DEFAULT_PATIENTS)
    parser.add_argument("--out", default="data/generated/tables")
    args = parser.parse_args(argv)
    patient_rows, encounter_rows, cells = make_tables(args.seed, args.patients)
    truth = {"seed": args.seed, "patients": args.patients, "styles": {}, "identifier_cells": cells}
    for style in STYLES:
        truth["styles"][style] = write_style(args.out, style, patient_rows, encounter_rows)
    Path(args.out).mkdir(parents=True, exist_ok=True)
    (Path(args.out) / "truth.json").write_text(json.dumps(truth, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(patient_rows)} patients, {len(encounter_rows)} encounters, {len(cells)} identifier cells -> {args.out}")


if __name__ == "__main__":
    main()
