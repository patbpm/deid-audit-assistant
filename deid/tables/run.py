"""De-identify CSV tables.

    python -m deid.tables.run --in patients.csv encounters.csv --plan-only --out-dir runs/tables-x
    python -m deid.tables.run --in patients.csv encounters.csv --out-dir runs/tables-x [--plan runs/tables-x/plan.json]

Step 1 (--plan-only) writes plan.json: for every column its type, how that was
decided, and what will be done to it. Read it, correct any column by editing its
"type" (and pass the file back with --plan), then run without --plan-only. All
tables of one run share their mappings, so a patient id, MRN, name or date shift
is the same in every file. Columns the rules cannot place are dropped
(--unknown withhold, the default), masked or kept. Free-text columns are masked
unless --freetext-live sends each cell through the note detector (a hosted model:
synthetic data only; capped by --max-total-tokens).

Writes, in --out-dir: <table>.csv (cleaned), <table>.changes.jsonl and key.json
(contain the original values: never share), plan.json and report.json (no values).
No model is called unless --freetext-live is given.
"""

import argparse
import csv
import json
import re
from pathlib import Path

from .apply import TableDeidentifier
from .columns import CHECKS, ACTIONS, build_plan


def looks_like_header(row):
    """A first row is a header when no cell looks like data: a number, a short code such
    as E1 or P0001, a date, an email, or an id."""
    def datalike(c):
        c = c.strip()
        return (not c or len(c) > 30 or re.fullmatch(r"[\d\s.,:+\-/()]+", c) or re.fullmatch(r"[A-Za-z]{0,4}\d+", c)
                or any(CHECKS[k](c) for k in ("EMAIL", "DATE", "KEY")))
    return bool(row) and not any(datalike(c) for c in row)


def read_table(path, header="auto"):
    """-> (header or None, rows). header: "auto", "yes" or "no"."""
    with open(path, encoding="utf-8-sig", newline="") as handle:
        rows = [r for r in csv.reader(handle) if r]
    if not rows:
        return None, []
    has = {"yes": True, "no": False}.get(header, looks_like_header(rows[0]))
    return (rows[0], rows[1:]) if has else (None, rows)


def write_table(path, header, rows):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        if header:
            writer.writerow(header)
        writer.writerows(rows)


def deidentify_tables(tables, seed=0, unknown="withhold", plans=None, clean_text=None, overrides=None):
    """tables: {name: (header or None, rows)}. -> (outputs {name: (header, rows)}, changes, report, deidentifier)."""
    plans = plans or {}
    built = {name: plans.get(name) or build_plan(name, header, rows, (overrides or {}).get(name))
             for name, (header, rows) in tables.items()}
    td = TableDeidentifier(seed, unknown, clean_text)
    names = []
    for name, plan in built.items():
        for c in plan["columns"]:
            if c["type"] == "NAME":
                names += [r[c["index"]] for r in tables[name][1] if c["index"] < len(r)]
    td.fit(names)
    outputs, changes, report = {}, [], {"plans": built, "tables": {}}
    for name, plan in built.items():
        header, rows = tables[name]
        out_header, out_rows, ch, summary = td.process(plan, rows)
        outputs[name] = (out_header, out_rows)
        changes += ch
        report["tables"][name] = summary
    return outputs, changes, report, td


def freetext_cleaner(args, td_box):
    """A cleaning function that sends each free-text cell through the note detector."""
    from deid.detect.client import Budget, ChatClient, LargerLimitRetry
    from deid.detect.detector import Cache, detect_note
    client = LargerLimitRetry(ChatClient.from_env("meta", 4096), 16384)
    budget, cache = Budget(args.max_total_tokens), Cache(Path(args.cache_dir) / "cache")

    def clean(value, key):
        if budget.exceeded:
            return "[FREE TEXT NOT CLEANED]", True
        found = detect_note(client, value, cache)
        budget.add(found.usage)
        if found.parse_error or found.truncated:
            return "[FREE TEXT NOT CLEANED]", True
        text, changes = td_box[0].replacer.apply({"text": value, "spans": found.spans, "patient_key": key})
        return text, any(c["flagged"] for c in changes)

    clean.budget = budget
    return clean


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--in", dest="inputs", nargs="+", required=True, metavar="CSV")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--plan", help="a plan.json from an earlier --plan-only run, possibly edited")
    parser.add_argument("--plan-only", action="store_true", help="write plan.json and stop")
    parser.add_argument("--header", choices=("auto", "yes", "no"), default="auto")
    parser.add_argument("--unknown", choices=("withhold", "mask", "keep"), default="withhold")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--freetext-live", action="store_true", help="clean free-text cells with the hosted detector")
    parser.add_argument("--max-total-tokens", type=int, default=100_000)
    parser.add_argument("--cache-dir", default="runs")
    args = parser.parse_args(argv)

    tables = {Path(p).stem: read_table(p, args.header) for p in args.inputs}
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    plans = None
    if args.plan:
        saved = json.loads(Path(args.plan).read_text(encoding="utf-8"))["plans"]
        plans = {}
        for name, plan in saved.items():
            for c in plan["columns"]:
                if c["type"] not in ACTIONS:
                    parser.error(f"{name}.{c['column']}: unknown type {c['type']!r}")
                c["action"] = ACTIONS[c["type"]]
            plans[name] = plan
    box = [None]
    clean = freetext_cleaner(args, box) if args.freetext_live and not args.plan_only else None
    outputs, changes, report, td = deidentify_tables(tables, args.seed, args.unknown, plans, clean)
    if clean:
        box[0] = td
        outputs, changes, report, td = deidentify_tables(tables, args.seed, args.unknown, report["plans"], clean)
    (out / "plan.json").write_text(json.dumps({"plans": report["plans"]}, indent=2) + "\n", encoding="utf-8", newline="\n")
    unplaced = [(n, c["column"]) for n, p in report["plans"].items() for c in p["columns"] if c["type"] == "UNKNOWN"]
    if args.plan_only:
        print(f"plan written to {out / 'plan.json'}; columns with no type: {unplaced or 'none'}")
        return 0
    for name, (header, rows) in outputs.items():
        write_table(out / f"{name}.csv", header, rows)
    with open(out / "changes.jsonl", "w", encoding="utf-8", newline="\n") as handle:
        for c in changes:
            handle.write(json.dumps(c, sort_keys=True) + "\n")
    (out / "key.json").write_text(json.dumps(td.replacer.key_tables(), indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    report["unknown_policy"] = args.unknown
    (out / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    flagged = sum(c["flagged"] for c in changes)
    print(f"{len(outputs)} tables -> {out}; {len(changes)} cells replaced, {flagged} flagged; "
          f"columns not placed ({args.unknown}): {unplaced or 'none'}")
    print("changes.jsonl and key.json contain original values: do not share them with the cleaned tables.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
