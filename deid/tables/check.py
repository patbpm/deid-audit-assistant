"""Check the table mode against the synthetic tables' ground truth.

    python -m deid.tables.check --out results/dev/tables.json

Generates the synthetic tables (deid.synth.tables), cleans each header style
(clean, messy, headerless) with default settings and no model, and reports:

  typing       how many columns got their true type, how many were left unplaced
               (withheld), and the dangerous error: an identifier column treated as
               safe or kept as is (must be 0)
  leaks        original identifiers (names, IDs, phones, emails, addresses) that
               can still be found anywhere in the cleaned tables, free text included
  consistency  row links kept: each cleaned encounter's patient id and MRN still
               match the cleaned patient row; distinct originals stay distinct
  dates        one shift per patient across both tables; stays and ages unchanged
  utility      safe columns identical; ages 90 and over shown as 90+
  small_groups rows that share their age, ZIP, diagnosis and similar columns with
               fewer than 5 others (deid.tables.risk); a screen, not a pass/fail

String-level, on invented data with a known structure: it shows the table path
works on this generator, not how it does on real tables.
"""

import argparse
import json
import re
import tempfile
from collections import defaultdict
from datetime import date
from pathlib import Path

from deid.ingest.fidelity import present
from deid.synth import tables as synth

from .risk import analyse, tables_from_outputs
from .run import deidentify_tables, read_table

LEAK_TYPES = ("NAME", "ID", "KEY", "PHONE", "EMAIL", "STREET", "TOWN", "ZIP")
PRESENT_KIND = {"NAME": "NAME", "PHONE": "PHONE", "EMAIL": "EMAIL"}


def days(iso):
    y, m, d = (int(x) for x in iso.split("-"))
    return date(y, m, d).toordinal()


def evaluate_style(style, patients, seed, typer=None, freetext=None):
    """typer: a model-assisted column typer (deid.tables.run.column_typer); freetext: a function
    taking a one-item list (the deidentifier) and returning a free-text cleaner. Both are live
    model paths; by default neither is used."""
    with tempfile.TemporaryDirectory() as tmp:
        patient_rows, encounter_rows, cells = synth.make_tables(seed, patients)
        truth = synth.write_style(tmp, style, patient_rows, encounter_rows)
        tables = {t: read_table(Path(tmp) / meta["file"], "auto") for t, meta in truth.items()}
    outputs, changes, report, td = deidentify_tables(tables, seed=seed, typer=typer)
    if freetext:
        box = [td]
        outputs, changes, report, td = deidentify_tables(tables, seed=seed, plans=report["plans"],
                                                         clean_text=freetext(box))
    result = {"style": style}

    # --- typing
    right = wrong = unplaced = danger = 0
    wrong_examples = []
    for t, meta in truth.items():
        for c in report["plans"][t]["columns"]:
            true = meta["columns"][meta["order"][c["index"]]]
            if c["type"] == true:
                right += 1
            elif c["type"] == "UNKNOWN":
                unplaced += 1
            else:
                wrong += 1
                wrong_examples.append(f"{t}.{c['column']}: {c['type']} (true {true})")
            if true in LEAK_TYPES + ("FREETEXT", "AGE") and c["action"] == "keep":
                danger += 1
    result["typing"] = {"columns": right + wrong + unplaced, "right": right, "wrong_type": wrong, "unplaced": unplaced,
                        "identifier_columns_kept_as_is": danger, "wrong_examples": wrong_examples}

    # --- leaks: any original identifier still readable in any cleaned cell
    blobs = {t: "\n".join(" | ".join(r) for r in rows) for t, (_, rows) in outputs.items()}
    everything = "\n".join(blobs.values())
    checked, leaked, by_type = 0, 0, defaultdict(lambda: [0, 0])
    for cell in cells:
        if cell["type"] not in LEAK_TYPES:
            continue
        if cell["type"] in ("NAME", "PHONE", "EMAIL"):  # tolerant of spacing and punctuation
            found = present(PRESENT_KIND[cell["type"]], cell["value"], everything, any_token=True)
        else:  # the exact original value as a whole word or number
            found = bool(re.search(r"(?<![A-Za-z0-9])" + re.escape(cell["value"]) + r"(?![A-Za-z0-9])", everything))
        checked += 1
        by_type[cell["type"]][0] += 1
        by_type[cell["type"]][1] += found
        leaked += found
    result["leaks"] = {"identifier_cells_checked": checked, "still_present_somewhere": leaked,
                       "by_type": {k: {"checked": v[0], "still_present": v[1]} for k, v in sorted(by_type.items())}}

    # --- consistency of links
    p_head, p_rows = outputs["patients"]
    e_head, e_rows = outputs["encounters"]
    pi = {c["column"]: c["index"] for c in report["plans"]["patients"]["columns"]}
    ei = {c["column"]: c["index"] for c in report["plans"]["encounters"]["columns"]}
    out_pi = {c["column"]: i for i, c in enumerate([c for c in report["plans"]["patients"]["columns"] if c["action"] != "withhold"])}
    out_ei = {c["column"]: i for i, c in enumerate([c for c in report["plans"]["encounters"]["columns"] if c["action"] != "withhold"])}
    pk = report["plans"]["patients"]["key_column"]
    ek = report["plans"]["encounters"]["key_column"]
    pm = next((c["column"] for c in report["plans"]["patients"]["columns"] if c["index"] == 1), None)
    em = next((c["column"] for c in report["plans"]["encounters"]["columns"] if c["index"] == 2), None)
    pn_col = next((c["column"] for c in report["plans"]["patients"]["columns"] if c["index"] == 2), None)
    broken = 0
    mrn_of = {r[out_pi[pk]]: r[out_pi[pm]] for r in p_rows} if pk in out_pi and pm in out_pi else {}
    for r in e_rows:
        if ek not in out_ei or r[out_ei[ek]] not in mrn_of or (em in out_ei and mrn_of[r[out_ei[ek]]] != r[out_ei[em]]):
            broken += 1
    orig_values = {}
    for c in cells:
        if c["type"] in ("KEY", "ID") and c["table"] == "patients":
            orig_values.setdefault(c["column"], []).append(c["value"])
    out_values = {col: [r[out_pi[col]] for r in p_rows] for col in orig_values if col in out_pi}
    collisions = sum(len(set(v)) != len(set(orig_values[col])) for col, v in out_values.items())
    result["consistency"] = {"encounter_rows": len(e_rows), "rows_whose_links_broke": broken,
                             "id_columns_where_distinct_originals_collided": collisions}

    # --- dates: one shift per patient, and relationships kept
    orig_p = {r["patient_id"]: r for r in patient_rows}
    shifts = defaultdict(set)
    stay_changed = age_changed = 0
    dob_col = next((c["column"] for c in report["plans"]["patients"]["columns"] if c["index"] == 3), None)
    for i, r in enumerate(e_rows):
        orig = encounter_rows[i]
        a_col = next(c["column"] for c in report["plans"]["encounters"]["columns"] if c["index"] == 3)
        d_col = next(c["column"] for c in report["plans"]["encounters"]["columns"] if c["index"] == 4)
        if a_col not in out_ei or d_col not in out_ei:
            continue
        try:
            a2, d2 = days(r[out_ei[a_col]]), days(r[out_ei[d_col]])
        except ValueError:
            continue
        a1, d1 = days(orig["admit_date"]), days(orig["discharge_date"])
        shifts[orig["patient_id"]].add(a2 - a1)
        shifts[orig["patient_id"]].add(d2 - d1)
        stay_changed += (d2 - a2) != (d1 - a1)
        pr = next((pr for pr, o in zip(p_rows, patient_rows) if o["patient_id"] == orig["patient_id"]), None)
        if pr is not None and dob_col in out_pi:
            try:
                age_changed += (a2 - days(pr[out_pi[dob_col]])) != (a1 - days(orig_p[orig["patient_id"]]["dob"]))
            except ValueError:
                pass
    dob_shift_bad = 0
    for pr, o in zip(p_rows, patient_rows):
        if dob_col in out_pi and o["patient_id"] in shifts:
            try:
                dob_shift_bad += {days(pr[out_pi[dob_col]]) - days(o["dob"])} != shifts[o["patient_id"]]
            except ValueError:
                dob_shift_bad += 1
    result["dates"] = {"patients_with_encounters": len(shifts),
                       "patients_with_more_than_one_shift": sum(len(s) > 1 for s in shifts.values()),
                       "stays_changed": stay_changed, "ages_at_admission_changed": age_changed,
                       "birth_dates_shifted_differently_from_their_encounters": dob_shift_bad}

    # --- utility
    changed_safe = 0
    for t, meta in truth.items():
        plan = report["plans"][t]
        out_idx = {c["column"]: i for i, c in enumerate([c for c in plan["columns"] if c["action"] != "withhold"])}
        source = patient_rows if t == "patients" else encounter_rows
        rows = p_rows if t == "patients" else e_rows
        for c in plan["columns"]:
            true = meta["columns"][meta["order"][c["index"]]]
            if true == "SAFE" and c["column"] in out_idx:
                clean_name = synth.PATIENT_COLUMNS[c["index"]][0] if t == "patients" else synth.ENCOUNTER_COLUMNS[c["index"]][0]
                changed_safe += sum(rows[i][out_idx[c["column"]]] != source[i][clean_name] for i in range(len(rows)))
    age_ok = age_bad = 0
    age_col = next((c["column"] for c in report["plans"]["patients"]["columns"] if c["index"] == 11), None)
    if age_col in out_pi:
        for r, o in zip(p_rows, patient_rows):
            expected = "90+" if int(o["age"]) >= 90 else o["age"]
            age_ok += r[out_pi[age_col]] == expected
            age_bad += r[out_pi[age_col]] != expected
    comment_col = next((c for c in report["plans"]["encounters"]["columns"] if c["type"] == "FREETEXT"), None)
    if comment_col is not None and comment_col["column"] in out_ei:
        texts = [r[out_ei[comment_col["column"]]] for r in e_rows]
        inside = [c for c in cells if c.get("inside_text")]
        still, by_kind = 0, defaultdict(lambda: [0, 0])
        for c in inside:
            text = texts[c["row"]]
            kind = PRESENT_KIND.get(c["type"]) or "ID"
            found = present(kind, c["value"], text, any_token=True) if kind != "ID" else \
                bool(re.search(r"(?<![A-Za-z0-9])" + re.escape(c["value"]) + r"(?![A-Za-z0-9])", text))
            still += found
            by_kind[c["type"]][0] += 1
            by_kind[c["type"]][1] += found
        masked = sum(t == "[FREE TEXT NOT CLEANED]" for t in texts)
        consistent = total = 0
        for c in inside:  # the patient's own name in a comment should become the same surname as in the patient table
            if c["type"] != "NAME" or " " not in c["value"] or c["column"] != "comment":
                continue
            enc = encounter_rows[c["row"]]
            if c["value"] != next((f"{p['full_name'].split(', ')[1].split()[0]} {p['full_name'].split(',')[0]}"
                                   for p in patient_rows if p["patient_id"] == enc["patient_id"]), None):
                continue
            idx = next(i for i, p in enumerate(patient_rows) if p["patient_id"] == enc["patient_id"])
            surname = p_rows[idx][out_pi[pn_col]].split(",")[0] if pn_col in out_pi else None
            total += 1
            consistent += bool(surname) and surname in texts[c["row"]]
        result["free_text"] = {
            "comment_cells": len(texts), "distinct_comments": len(set(r["comment"] for r in encounter_rows)),
            "masked_not_cleaned": masked, "identifiers_inside_text": len(inside), "still_present": still,
            "by_type": {k: {"inside": v[0], "still_present": v[1]} for k, v in sorted(by_kind.items())},
            "own_name_comments": total, "own_name_surname_matches_patient_table": consistent}
    small = analyse(tables_from_outputs(outputs, report["plans"]))
    result["small_groups"] = [
        {"view": v["view"], "quasi_identifiers": v["quasi_identifiers"], "rows": v["rows_total"],
         "rows_below_k": v.get("rows_below_k"), "rows_unique": v.get("rows_unique"),
         "rows_below_k_after_generalizing": (v.get("after_generalizing") or {}).get("rows_below_k")}
        for v in small["views"]]
    result["utility"] = {"safe_cells_changed": changed_safe, "ages_correct": age_ok, "ages_wrong": age_bad,
                         "columns_withheld": {t: s["columns_withheld"] for t, s in report["tables"].items()},
                         "cells_flagged": sum(s["cells_flagged"] for s in report["tables"].values())}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=synth.DEFAULT_SEED)
    parser.add_argument("--patients", type=int, default=synth.DEFAULT_PATIENTS)
    parser.add_argument("--out", default="results/dev/tables.json")
    parser.add_argument("--styles", nargs="+", choices=synth.STYLES, default=list(synth.STYLES))
    parser.add_argument("--live-free-text", action="store_true",
                        help="clean the comment column with the hosted detector (synthetic data; billed)")
    parser.add_argument("--live-typing", action="store_true",
                        help="let the hosted model type columns the rules cannot place, confirmed by the rules (billed)")
    parser.add_argument("--max-total-tokens", type=int, default=250_000)
    parser.add_argument("--cache-dir", default="runs")
    args = parser.parse_args(argv)
    typer = freetext = budget = None
    if args.live_typing or args.live_free_text:
        from types import SimpleNamespace

        from deid.detect.client import Budget, ChatClient, LargerLimitRetry

        from .run import column_typer, freetext_cleaner
        budget = Budget(args.max_total_tokens)
        if args.live_typing:
            typer = column_typer(LargerLimitRetry(ChatClient.from_env("meta", 4096), 16384), args.cache_dir, budget)
        if args.live_free_text:
            ns = SimpleNamespace(max_total_tokens=args.max_total_tokens, cache_dir=args.cache_dir)
            cleaners = []

            def freetext(box):
                cleaners.append(freetext_cleaner(ns, box))
                return cleaners[-1]
    results = {"seed": args.seed, "patients": args.patients, "live": {"typing": args.live_typing,
                                                                     "free_text": args.live_free_text},
               "styles": {s: evaluate_style(s, args.patients, args.seed, typer, freetext) for s in args.styles}}
    if budget is not None:
        used = budget.total + sum(c.budget.total for c in locals().get("cleaners", []))
        results["tokens"] = {"typing": budget.total,
                             "free_text": sum(c.budget.total for c in locals().get("cleaners", [])), "total": used}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
