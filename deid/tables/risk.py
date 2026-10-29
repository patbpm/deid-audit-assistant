"""Find small groups of rows that could single someone out, and report them for review.

    python -m deid.tables.risk --in runs/tables-x/patients.csv runs/tables-x/encounters.csv \
        --plan runs/tables-x/plan.json --k 5

Names, ids, phones and emails are gone after cleaning, but a combination of
ordinary columns can still point at one person: a rare age, ZIP code and
diagnosis together. This check takes the CLEANED tables and groups the rows by
their quasi-identifier columns (age, ZIP, town, state, and any low-cardinality
safe column such as sex or diagnosis code). A row whose group has fewer than k
rows is reported. Direct identifiers and dates are not quasi-identifiers here:
they were replaced or shifted. Linked tables are also joined on the patient key
and checked together, because a diagnosis in one table plus an age and ZIP code
in another is the usual route.

What the numbers mean: group sizes are counted inside this table, not in the
population. A group of one in a 60-row sample may be common in real life, and a
group of ten may be rare in a small town; the check is a screen that finds where
to look, and says nothing about the real chance of re-identification. It runs on
cleaned data only.
"""

import argparse
import csv
import json
import re
from collections import Counter
from itertools import combinations
from pathlib import Path

DEFAULT_K = 5
MAX_SUBSET = 3
QI_TYPES = ("AGE", "ZIP", "TOWN", "STATE")


def band_age(value):
    v = value.strip()
    if v.isdigit():
        low = int(v) // 10 * 10
        return f"{low}-{low + 9}"
    return v  # "90+" and anything else stays as it is


def zip3(value):
    digits = re.sub(r"\D", "", value)
    return digits[:3] + "**" if len(digits) >= 3 else value


GENERALIZE = {"AGE": band_age, "ZIP": zip3}


def choose_qi(types, records, override=None):
    """Quasi-identifier columns of one view: the override, or the typed ones plus
    low-cardinality safe columns (sex, a diagnosis code, a length of stay...)."""
    columns = list(records[0]) if records else []
    if override:
        names = {c.split(".", 1)[-1]: c for c in columns} | {c: c for c in columns}
        return [names[c] for c in override if c in names]
    chosen = []
    for col in columns:
        values = {r.get(col, "").strip() for r in records} - {""}
        kind = types.get(col)
        if kind in QI_TYPES or (kind == "SAFE" and 1 < len(values) <= max(30, len(records) // 5)):
            chosen.append(col)
    return chosen


def tuples_of(records, columns, generalize=None):
    def cell(record, col):
        value = record.get(col, "").strip()
        fn = (generalize or {}).get(col)
        return fn(value) if fn and value else value
    return [tuple(cell(r, c) for c in columns) for r in records]


def small_rows(records, columns, k, generalize=None):
    """[(row index, group size)] for rows whose group is smaller than k."""
    tuples = tuples_of(records, columns, generalize)
    sizes = Counter(t for t in tuples if any(t))
    return [(i, sizes[t]) for i, t in enumerate(tuples) if any(t) and sizes[t] < k]


def analyse_view(name, records, columns, types, k, key=None):
    """One table, or a join of tables: group sizes over the quasi-identifier columns."""
    base = {"view": name, "quasi_identifiers": columns, "rows_total": len(records), "k": k}
    if not columns or not records:
        return base | {"note": "no quasi-identifier columns found"}
    tuples = tuples_of(records, columns)
    sizes = Counter(t for t in tuples if any(t))
    small = small_rows(records, columns, k)
    subsets = []
    for r in range(1, min(MAX_SUBSET, len(columns)) + 1):
        for cols in combinations(columns, r):
            counts = Counter(tuples_of(records, cols))
            subsets.append({"columns": list(cols), "smallest_group": min(counts.values()),
                            "rows_in_groups_below_k": sum(n for n in counts.values() if n < k)})
    subsets.sort(key=lambda s: (-s["rows_in_groups_below_k"], len(s["columns"])))
    gen = {c: GENERALIZE[types[c]] for c in columns if types.get(c) in GENERALIZE}
    after = small_rows(records, columns, k, gen) if gen else None
    rare = {}
    for c in columns:
        counts = Counter(r.get(c, "").strip() for r in records if r.get(c, "").strip())
        below = {v: n for v, n in counts.items() if n < k}
        if below:
            rare[c] = {"values_below_k": len(below), "rows": sum(below.values()),
                       "examples": dict(sorted(below.items(), key=lambda kv: (kv[1], kv[0]))[:5])}
    return base | {
        "smallest_group": min(sizes.values()) if sizes else None,
        "rows_unique": sum(1 for t in tuples if any(t) and sizes[t] == 1),
        "rows_below_k": len(small), "share_below_k": round(len(small) / len(records), 3),
        "riskiest_column_sets": subsets[:5], "rare_values_by_column": rare,
        "after_generalizing": None if after is None else {
            "generalized": {c: "ZIP to its first 3 digits" if types[c] == "ZIP" else "age to 10-year bands" for c in gen},
            "rows_below_k": len(after), "share_below_k": round(len(after) / len(records), 3)},
        "flagged_rows": [{"row": i, "group_size": n, "key": records[i].get(key) if key else None,
                          "quasi_identifiers": {c: records[i].get(c, "") for c in columns}} for i, n in small],
    }


def join_views(tables):
    """Join each table whose key repeats to the table whose key is unique. -> [(name, records, types, key)]"""
    unique = next((n for n, t in tables.items() if t["key"] in t["header"] and (
        lambda vals: vals and len(set(vals)) == len(vals))([r[t["header"].index(t["key"])] for r in t["rows"]
                                                           if r[t["header"].index(t["key"])]])), None)
    if unique is None:
        return []
    dim = tables[unique]
    dim_col = dim["header"].index(dim["key"])
    by_key = {r[dim_col]: dict(zip(dim["header"], r)) for r in dim["rows"]}
    views = []
    for name, t in tables.items():
        if name == unique or t["key"] not in t["header"]:
            continue
        col = t["header"].index(t["key"])
        records = []
        for r in t["rows"]:
            base = by_key.get(r[col])
            if base is not None:
                records.append({f"{unique}.{c}": v for c, v in base.items()} | {f"{name}.{c}": v for c, v in zip(t["header"], r)})
        types = {f"{unique}.{c}": k for c, k in dim["types"].items()} | {f"{name}.{c}": k for c, k in t["types"].items()}
        views.append((f"{name} joined to {unique}", records, types, f"{name}.{t['key']}"))
    return views


def analyse(tables, k=DEFAULT_K, override=None):
    """tables: {name: {"header": [...], "rows": [[...]], "types": {column: TYPE}, "key": column or None}}."""
    views = []
    for name, t in tables.items():
        records = [dict(zip(t["header"], r)) for r in t["rows"]]
        views.append(analyse_view(name, records, choose_qi(t["types"], records, override), t["types"], k, t["key"]))
    for name, records, types, key in join_views(tables):
        views.append(analyse_view(name, records, choose_qi(types, records, override), types, k, key))
    return {"k": k, "views": views}


def tables_from_outputs(outputs, plans):
    """Build the input of analyse from deidentify_tables output and its plans."""
    result = {}
    for name, (header, rows) in outputs.items():
        plan = plans[name]
        kept = [c for c in plan["columns"] if c["action"] != "withhold"]
        names = header or [c["column"] for c in kept]
        result[name] = {"header": names, "rows": rows, "types": {c["column"]: c["type"] for c in kept},
                        "key": plan.get("key_column")}
    return result


def write_report(report, out_dir):
    """risk.json (no row detail) and risk-rows.csv (one line per flagged row, cleaned values only)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    slim = {"k": report["k"], "views": [{k: v for k, v in view.items() if k != "flagged_rows"} for view in report["views"]]}
    (out / "risk.json").write_text(json.dumps(slim, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    with open(out / "risk-rows.csv", "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["view", "row", "key", "group_size", "quasi_identifiers"])
        for view in report["views"]:
            for r in view.get("flagged_rows", []):
                writer.writerow([view["view"], r["row"], r["key"], r["group_size"], json.dumps(r["quasi_identifiers"])])


def summary_line(report):
    parts = [f"{v['view']}: {v['rows_below_k']} of {v['rows_total']} rows in groups under {report['k']}"
             for v in report["views"] if "rows_below_k" in v]
    return "; ".join(parts) if parts else "no quasi-identifier columns found"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--in", dest="inputs", nargs="+", required=True, metavar="CSV", help="CLEANED tables, with headers")
    parser.add_argument("--plan", required=True, help="the plan.json used to clean them (column types and the key)")
    parser.add_argument("--k", type=int, default=DEFAULT_K, help="smallest group size considered safe")
    parser.add_argument("--qi", nargs="+", help="name the quasi-identifier columns instead of guessing them")
    parser.add_argument("--out-dir", help="where to write risk.json and risk-rows.csv (default: beside the first input)")
    args = parser.parse_args(argv)
    plans = json.loads(Path(args.plan).read_text(encoding="utf-8"))["plans"]
    tables = {}
    for path in args.inputs:
        name = Path(path).stem
        with open(path, encoding="utf-8-sig", newline="") as handle:
            rows = [r for r in csv.reader(handle) if r]
        header, body = rows[0], rows[1:]
        plan = plans.get(name, {"columns": [], "key_column": None})
        tables[name] = {"header": header, "rows": body, "key": plan.get("key_column"),
                        "types": {c["column"]: c["type"] for c in plan["columns"] if c["column"] in header}}
    report = analyse(tables, args.k, args.qi)
    write_report(report, args.out_dir or Path(args.inputs[0]).parent)
    print(summary_line(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
