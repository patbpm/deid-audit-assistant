"""The work behind a job: notes (text, dictation, scans) and tables.

run_notes   read -> detect -> replace -> audit trail          (deid.agent.pipeline)
plan_tables read -> propose column types                      (deid.tables)
apply_tables the person's confirmed plan -> clean -> small-group check

These functions only read and write files in the job folder and report through
ctx; they hold no state. A note that cannot be cleaned is never written as cleaned
(it goes to the audit as NOT CLEANED), and a file that cannot be read is listed with
the reason instead of being skipped silently.
"""

import csv
import json
from pathlib import Path
from types import SimpleNamespace

from deid.agent.pipeline import detect_and_verify, review_and_clean
from deid.agent.verifier import PROMPT_VERSION as VERIFY_VERSION
from deid.audit.build import summarize
from deid.audit.report import render
from deid.audit.verify import LOW_CONFIDENCE
from deid.detect.client import ApiError, Budget
from deid.detect.detector import Cache
from deid.ingest import vision
from deid.ingest.audio import AudioCache, WavError, check_wav, transcribe_file
from deid.redteam.prompt import PROMPT_VERSION as REDTEAM_VERSION
from deid.tables import model_typing
from deid.tables.columns import ACTIONS, TYPES, build_plan
from deid.tables.risk import DEFAULT_K, analyse, summary_line, tables_from_outputs, write_report
from deid.tables.run import column_typer, deidentify_tables, freetext_cleaner, read_table, write_table

from . import kinds

MAX_ROUNDS = 2
PREVIEW_ROWS = 8
SAMPLE_VALUES = 3
TYPE_HELP = {
    "KEY": "row key: links this row to the same person in other tables",
    "ID": "an identifier (record, account, insurance number)", "NAME": "a person's name",
    "DATE": "a date (shifted, keeping the gaps between dates)", "PHONE": "a phone number",
    "EMAIL": "an email address", "STREET": "a street address", "TOWN": "a town or city",
    "ZIP": "a ZIP code", "STATE": "a state (kept)", "AGE": "an age (90 and over becomes 90+)",
    "FREETEXT": "free text with identifiers inside it", "SAFE": "not identifying: kept as it is",
    "UNKNOWN": "not placed: withheld unless you choose a type",
}


class JobError(RuntimeError):
    """A problem to show the person as it is written."""


def unique(base, used):
    name, n = base, 1
    while name in used:
        n += 1
        name = f"{base}-{n}"
    used.add(name)
    return name


# --- notes -----------------------------------------------------------------------------------
def load_notes(ctx, backend, files, options, budget, cache_root):
    """-> (notes, skipped). Each note: note_id, patient_id, text, plus where it came from."""
    notes, skipped, used = [], [], set()
    speech = chat = None
    seconds = 0.0

    def skip(f, why):
        skipped.append({"file": f["name"], "reason": why})

    for f in files:
        path = ctx.dir / "input" / f["stored"]
        stem = Path(f["name"]).stem
        try:
            if f["kind"] == "note":
                text = path.read_text(encoding="utf-8-sig")
                records = kinds.notes_from_jsonl(text)
                if records is None:
                    records = [{"text": text}]
                for i, record in enumerate(records, 1):
                    if not record["text"].strip():
                        skip(f, f"note {i} is empty")
                        continue
                    base = str(record.get("note_id") or (stem if len(records) == 1 else f"{stem}-{i}"))[:80]
                    note_id = unique(base, used)
                    patient = "patient-1" if options["same_patient"] else str(record.get("patient_id") or note_id)
                    notes.append({"note_id": note_id, "patient_id": patient, "text": record["text"], "source": f["name"]})
            elif f["kind"] == "audio":
                speech = speech or backend.speech()
                info = check_wav(path)
                if seconds + info.seconds > options["max_audio_seconds"]:
                    skip(f, f"the audio limit for this job ({options['max_audio_seconds']} s) would be passed")
                    continue
                heard = transcribe_file(speech, path, AudioCache(cache_root / "cache-audio"))
                seconds += 0 if heard.cached else heard.seconds
                note_id = unique(f"{stem}-audio", used)
                notes.append({"note_id": note_id, "patient_id": "patient-1" if options["same_patient"] else note_id,
                              "text": heard.text, "source": f["name"]})
            elif f["kind"] == "scan":
                chat = chat or backend.chat()
                scan = vision.read_scan(chat, path, Cache(cache_root / "cache-scan", vision.PROMPT_VERSION))
                budget.add(scan.usage)
                if scan.truncated:
                    skip(f, "reading the page was cut off at the output limit, so part of it is missing")
                    continue
                note_id = unique(f"{stem}-scan", used)
                notes.append({"note_id": note_id, "patient_id": "patient-1" if options["same_patient"] else note_id,
                              "text": scan.text, "source": f["name"]})
        except (WavError, vision.ImageError, ApiError, ValueError, OSError) as err:
            skip(f, str(err))
        ctx.tokens(budget)
    return notes, skipped


def run_notes(ctx, backend, files, options, seed, cache_root):
    budget = Budget(options["token_cap"])
    ctx.step("read", "running")
    notes, skipped = load_notes(ctx, backend, files, options, budget, cache_root)
    if not notes:
        raise JobError("No note could be read. " + "; ".join(f"{s['file']}: {s['reason']}" for s in skipped))
    ctx.step("read", "done", f"{len(notes)} note(s)" + (f", {len(skipped)} file(s) skipped" if skipped else ""))
    client = backend.chat()
    disk = backend.hosted
    detect_cache = Cache(cache_root / "cache") if disk else Cache(None)
    verify_cache = Cache(cache_root / "cache-verify", VERIFY_VERSION) if disk else Cache(None, VERIFY_VERSION)
    redteam_cache = Cache(cache_root / "cache-redteam", REDTEAM_VERSION) if disk else Cache(None, REDTEAM_VERSION)

    def progress(step):
        def report(stage, done, total, b):
            ctx.step(step, "running", f"{done} of {total} notes")
            ctx.tokens(b)
        return report

    ctx.step("detect", "running", f"0 of {len(notes)} notes")
    batch, stopped1 = detect_and_verify(notes, client, detect_cache, verify_cache, budget, LOW_CONFIDENCE,
                                        progress("detect"), verify=backend.verify)
    ctx.step("detect", "done", f"{len(batch)} of {len(notes)} notes"
             + ("" if backend.verify else "; no verifier with this engine"))
    ctx.step("replace", "running", f"0 of {len(batch)} notes")
    outcomes, stopped2, replacer = review_and_clean(batch, client, redteam_cache, budget, seed, LOW_CONFIDENCE,
                                                    MAX_ROUNDS, progress("replace"), redteam=backend.redteam)
    ctx.step("replace", "done", f"{len(outcomes)} of {len(batch)} notes"
             + ("" if backend.redteam else "; no re-identification review with this engine"))
    stopped = stopped1 or stopped2
    done_ids = {o.note_id for o in outcomes}
    for n in notes:
        if n["note_id"] not in done_ids:
            skipped.append({"file": n["source"], "reason": f"{n['note_id']} was not processed: the token cap was reached"})
    ctx.step("audit", "running")
    audits = [o.audit for o in outcomes]
    summary = summarize(audits)
    out = ctx.dir
    write_json(out / "notes.audit.json", {"summary": summary, "notes": audits})
    (out / "notes.audit.html").write_text(render(audits, summary), encoding="utf-8", newline="\n")
    write_json(out / "notes.key.json", replacer.key_tables())
    ctx.step("audit", "done", f"{summary['changes']} replacements, {summary['review_items']} items to review")
    ctx.tokens(budget)
    ctx.result({
        "kind": "notes", "engine": backend.label, "notes": len(outcomes), "replacements": summary["changes"],
        "by_type": summary["by_type"], "review_items": summary["review_items"],
        "notes_with_review_items": summary["notes_with_review_items"],
        "not_cleaned": summary["notes_not_cleaned"], "risk_levels": summary["risk_levels"],
        "skipped": skipped, "stopped_early": stopped, "assessed": backend.redteam,
        "audit": "notes.audit.json"})


# --- tables ------------------------------------------------------------------------------------
def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def read_tables(ctx, files, header):
    tables, skipped, used = {}, [], set()
    for f in files:
        try:
            head, rows = read_table(ctx.dir / "input" / f["stored"], header)
        except (UnicodeDecodeError, csv.Error, OSError) as err:
            skipped.append({"file": f["name"], "reason": f"could not be read as CSV ({err})"})
            continue
        if not rows:
            skipped.append({"file": f["name"], "reason": "has no data rows"})
            continue
        tables[unique(Path(f["name"]).stem, used)] = (head, rows)
    return tables, skipped


def sample_of(rows, index):
    seen = []
    for r in rows:
        v = r[index].strip() if index < len(r) else ""
        if v and v not in seen:
            seen.append(v)
        if len(seen) == SAMPLE_VALUES:
            break
    return [v[:30] for v in seen]


def plan_view(plans, tables):
    return {name: {"has_header": p["has_header"], "key_column": p["key_column"], "key_reason": p["key_reason"],
                   "rows": len(tables[name][1]),
                   "columns": [{"index": c["index"], "column": c["column"], "type": c["type"],
                                "decided_by": c["decided_by"], "reason": c["reason"],
                                "sample": sample_of(tables[name][1], c["index"])} for c in p["columns"]]}
            for name, p in plans.items()}


def plan_tables(ctx, backend, files, options, cache_root):
    ctx.step("read", "running")
    tables, skipped = read_tables(ctx, files, options["header"])
    if not tables:
        raise JobError("No table could be read. " + "; ".join(f"{s['file']}: {s['reason']}" for s in skipped))
    ctx.step("read", "done", f"{len(tables)} table(s)" + (f", {len(skipped)} file(s) skipped" if skipped else ""))
    ctx.step("plan", "running")
    plans = {name: build_plan(name, head, rows) for name, (head, rows) in tables.items()}
    placed = 0
    if options["model_typing"]:
        budget = Budget(options["token_cap"])
        typer = column_typer(backend.chat(), cache_root, budget)
        placed = sum(typer(name, plans[name], tables[name][1]) for name in plans)
        ctx.tokens(budget)
    unplaced = sum(c["type"] == "UNKNOWN" for p in plans.values() for c in p["columns"])
    write_json(ctx.dir / "plan.json", {"plans": plans, "skipped": skipped, "model_placed": placed})
    ctx.step("plan", "done", f"{sum(len(p['columns']) for p in plans.values())} columns; {unplaced} not placed"
             + (f"; the model placed {placed}" if options["model_typing"] else ""))
    ctx.step("confirm", "running", "check the plan below, change any column, then clean")
    return plan_view(plans, tables)


def load_plans(directory):
    return json.loads((Path(directory) / "plan.json").read_text(encoding="utf-8"))["plans"]


def check_edits(directory, edits):
    """Raise ValueError unless the edits name real tables and columns and real types."""
    plans = load_plans(directory)
    for name, edit in edits.items():
        if name not in plans or not isinstance(edit, dict):
            raise ValueError(f"unknown table {name!r}")
        columns = {c["column"] for c in plans[name]["columns"]}
        for column, kind in (edit.get("types") or {}).items():
            if column not in columns:
                raise ValueError(f"{name}: unknown column {column!r}")
            if kind not in ACTIONS:
                raise ValueError(f"{name}.{column}: unknown type {kind!r}")
        key = edit.get("key_column")
        if key is not None and key not in columns:
            raise ValueError(f"{name}: the key column {key!r} is not a column of this table")


def apply_edits(plans, edits):
    for name, edit in edits.items():
        plan = plans[name]
        for c in plan["columns"]:
            kind = (edit.get("types") or {}).get(c["column"])
            if kind and kind != c["type"]:
                c.update(type=kind, action=ACTIONS[kind], decided_by="set by hand", reason="changed by you on the plan page")
        if "key_column" in edit:
            plan["key_column"], plan["key_reason"] = edit["key_column"], "chosen by you"
    return plans


def preview_of(header, rows, plan):
    kept = [c["column"] for c in plan["columns"] if c["action"] != "withhold"] if header is None else header
    return {"header": kept, "rows": rows[:PREVIEW_ROWS]}


def apply_tables(ctx, backend, files, options, seed, edits, cache_root):
    ctx.step("confirm", "done", "plan confirmed" + (" with your changes" if any(edits.values()) else ""))
    ctx.step("clean", "running")
    tables, _ = read_tables(ctx, files, options["header"])
    plans = apply_edits(load_plans(ctx.dir), edits)
    write_json(ctx.dir / "plan.json", {"plans": plans})
    outputs, changes, report, td = deidentify_tables(tables, seed, options["unknown"], plans)
    freetext = None
    if options["freetext"] == "detector" and any(c["type"] == "FREETEXT" for p in plans.values() for c in p["columns"]):
        box = [td]
        args = SimpleNamespace(max_total_tokens=options["token_cap"], cache_dir=str(cache_root))
        cleaner = freetext_cleaner(args, box, backend.chat())
        outputs, changes, report, td = deidentify_tables(tables, seed, options["unknown"], plans, cleaner)
        ctx.tokens(cleaner.budget)
        freetext = {"mode": backend.label, "cells": sum(c["rule"] == "freetext-cleaned" for c in changes),
                    "flagged": sum(c["rule"] == "freetext-cleaned" and c["flagged"] for c in changes)}
    out = ctx.dir / "tables-out"
    out.mkdir(exist_ok=True)
    for name, (header, rows) in outputs.items():
        write_table(out / f"{name}.csv", header, rows)
    with open(out / "changes.jsonl", "w", encoding="utf-8", newline="\n") as handle:
        for c in changes:
            handle.write(json.dumps(c, sort_keys=True) + "\n")
    write_json(out / "key.json", td.replacer.key_tables())
    write_json(out / "plan.json", {"plans": report["plans"]})
    report["unknown_policy"] = options["unknown"]
    write_json(out / "report.json", report)
    flagged = sum(c["flagged"] for c in changes)
    ctx.step("clean", "done", f"{len(changes)} cells replaced, {flagged} flagged")
    ctx.step("risk", "running")
    risk = analyse(tables_from_outputs(outputs, report["plans"]), DEFAULT_K)
    write_report(risk, out)
    slim = {"k": risk["k"], "views": [{k: v for k, v in view.items() if k != "flagged_rows"} for view in risk["views"]]}
    ctx.step("risk", "done", summary_line(risk))
    ctx.result({
        "kind": "tables", "engine": backend.label, "freetext": freetext, "cells_replaced": len(changes),
        "cells_flagged": flagged, "risk": slim, "risk_summary": summary_line(risk),
        "tables": {name: {"rows": s["rows"], "columns_in": s["columns_in"], "columns_out": s["columns_out"],
                          "withheld": s["columns_withheld"], "cells_changed": s["cells_changed"],
                          "cells_flagged": s["cells_flagged"],
                          "preview": preview_of(outputs[name][0], outputs[name][1], report["plans"][name])}
                   for name, s in report["tables"].items()}})
