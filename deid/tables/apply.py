"""Replace the identifiers in table cells, column by column, following a plan.

One TableDeidentifier handles every table of a run, so a patient id, MRN, name or
date shift is the same wherever it appears. Dates shift by one offset per key
value (the patient), so intervals within and across a patient's rows are kept.
Cells in columns the plan could not place are withheld (or kept or masked, by
choice); free text is cleaned only if a cleaning function is supplied, and is
otherwise masked. Nothing here calls a model.
"""

import re

from deid.replace.engine import DEFAULT_YEAR, Replacer, name_words  # noqa: F401
from deid.replace.surrogates import number

STREET_ONLY = re.compile(
    r"(?P<num>\d+)\s+(?P<street>[A-Za-z][A-Za-z .'\-]*?)\s+"
    r"(?P<type>St|Ave|Dr|Rd|Ln|Blvd|Ct|Way|Street|Avenue|Drive|Road|Lane|Boulevard|Court)\.?"
    r"(?:,?\s+(?P<unit>(?:Apt|Unit|Suite|Ste)\.?\s*#?\s*\w+|#\s*\w+))?")
FREETEXT_MASK = "[FREE TEXT NOT CLEANED]"
WITHHELD_MASK = "[WITHHELD]"


class TableDeidentifier:
    def __init__(self, seed=0, unknown="withhold", clean_text=None):
        """unknown: what to do with columns of unknown type: "withhold" (drop the column),
        "mask" (keep the column, replace its values) or "keep". clean_text(value, key)
        -> (text, flagged) cleans a free-text cell."""
        if unknown not in ("withhold", "mask", "keep"):
            raise ValueError("unknown must be withhold, mask or keep")
        self.replacer = Replacer(seed)
        self.unknown, self.clean_text = unknown, clean_text

    def fit(self, name_values):
        """Learn which name words are first names and which are surnames, from every name cell."""
        values = [v for v in name_values if v.strip()]
        self.replacer.fit([{"text": v, "spans": [{"start": 0, "end": len(v), "type": "NAME"}]} for v in values])

    # --- one cell --------------------------------------------------------------------
    def cell(self, kind, value, key):
        """-> (replacement, rule, flagged)"""
        s = self.replacer.surrogates
        if kind in ("KEY", "ID"):
            return s.identifier(value), "id-format-preserving", False
        if kind in ("NAME", "DATE", "PHONE", "EMAIL"):
            return self.replacer.replace_value(kind, value, key, DEFAULT_YEAR)
        if kind == "TOWN":
            return s.town_name(value), "town-registry", False
        if kind == "ZIP":
            return s.digits(value, "zip"), "zip-digits", False
        if kind == "STREET":
            m = STREET_ONLY.fullmatch(value)
            if not m:
                return "[ADDRESS]", "fallback-tag", True
            street = f"{s.digits(m['num'], 'num')} {s.street_name(m['street'])} {m['type']}"
            if m["unit"]:
                street += ", " + re.sub(r"\w+$", lambda u: s.digits(u.group(0), "unit"), m["unit"])
            return street, "street-structured", False
        if kind == "AGE":
            if not value.strip().isdigit():
                return "[AGE]", "fallback-tag", True
            return ("90+", "age-90-plus", False) if int(value) >= 90 else (value, "age-kept", False)
        if kind == "FREETEXT":
            if self.clean_text:
                text, flagged = self.clean_text(value, key)
                return text, "freetext-cleaned", flagged
            return FREETEXT_MASK, "freetext-withheld", True
        raise ValueError(f"no rule for {kind}")

    # --- one table ---------------------------------------------------------------------------
    def process(self, plan, rows):
        """-> (header or None, output rows, changes, summary). rows: lists of strings."""
        columns, key_name = plan["columns"], plan.get("key_column")
        key_index = next((c["index"] for c in columns if c["column"] == key_name), None)
        out_cols = [c for c in columns if not (c["action"] == "withhold" and self.unknown == "withhold")]
        changes, out_rows, per_column = [], [], {c["column"]: {"changed": 0, "flagged": 0, "empty": 0} for c in columns}
        for r, row in enumerate(rows):
            key = row[key_index] if key_index is not None and row[key_index].strip() else f"{plan['table']}:row{r}"
            new = []
            for c in out_cols:
                value = row[c["index"]] if c["index"] < len(row) else ""
                stats = per_column[c["column"]]
                if not value.strip():
                    stats["empty"] += 1
                    new.append(value)
                    continue
                if c["action"] == "keep" or (c["action"] == "withhold" and self.unknown == "keep"):
                    new.append(value)
                    continue
                if c["action"] == "withhold":  # unknown == "mask"
                    out, rule, flagged = WITHHELD_MASK, "unknown-column-masked", True
                else:
                    out, rule, flagged = self.cell(c["type"], value.strip(), key)
                stats["changed"] += out != value
                stats["flagged"] += flagged
                new.append(out)
                changes.append({"table": plan["table"], "row": r, "column": c["column"], "type": c["type"],
                                "rule": rule, "flagged": flagged, "original": value, "replacement": out})
            out_rows.append(new)
        header = [c["column"] for c in out_cols] if plan["has_header"] else None
        summary = {"rows": len(rows), "columns_in": len(columns), "columns_out": len(out_cols),
                   "columns_withheld": [c["column"] for c in columns if c not in out_cols],
                   "per_column": per_column, "cells_changed": sum(v["changed"] for v in per_column.values()),
                   "cells_flagged": sum(v["flagged"] for v in per_column.values())}
        return header, out_rows, changes, summary


def key_offset(td, value):
    """The date shift (days) for one key value; exposed for checks."""
    return td.replacer.date_offset(value)


__all__ = ["TableDeidentifier", "key_offset", "number"]
