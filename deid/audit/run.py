"""Build the audit report for a detector's output on the dev split.

    python -m deid.audit.run --pred runs/meta-dev-first5.jsonl --detector muse-spark-1.3 \
        --log runs/meta-dev-first5.log.json --other regex=runs/regex.jsonl --out runs/audit-first5

Writes <out>.json (the evidence trace) and <out>.html (the review page). Both
contain original identifiers, so they stay in the git-ignored runs/ folder and
are not for sharing. Only notes present in --pred are included. No model is
called here. Optional --assessments takes red-team results as JSONL lines
{"note_id", "risk", "clues": [{"category", "text", "ranges", "why"}]}.
"""

import argparse
import json
from pathlib import Path

from deid.baselines.common import read_notes
from deid.eval.run import read_jsonl, split_of
from deid.replace.engine import Replacer

from .build import build_note_audit, summarize
from .report import render
from .verify import LOW_CONFIDENCE


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--notes", default="data/generated/notes.jsonl")
    parser.add_argument("--pred", required=True, help="the detector's predictions JSONL")
    parser.add_argument("--detector", required=True, help="name recorded in the trace, e.g. muse-spark-1.3")
    parser.add_argument("--log", help="the detector's .log.json, for strings it listed but that were not found")
    parser.add_argument("--other", action="append", default=[], metavar="NAME=PATH",
                        help="predictions from another detector, to record agreement")
    parser.add_argument("--assessments", help="red-team results (JSONL) to include")
    parser.add_argument("--assessment-variant", help="use only records with this variant")
    parser.add_argument("--split", choices=("dev", "test"), default="dev")
    parser.add_argument("--allow-test", action="store_true")
    parser.add_argument("--low-confidence", type=float, default=LOW_CONFIDENCE)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if args.split == "test" and not args.allow_test:
        parser.error("the test split is for the final reporting run; pass --allow-test")

    predicted = {r["note_id"]: r["spans"] for r in read_jsonl(args.pred)}
    notes = [n for n in read_notes(args.notes)
             if split_of(n["patient_id"]) == args.split and n["note_id"] in predicted]
    others = {}
    for item in args.other:
        name, _, path = item.partition("=")
        others[name] = {r["note_id"]: r["spans"] for r in read_jsonl(path)}
    unmatched = {}
    if args.log:
        log = json.loads(Path(args.log).read_text(encoding="utf-8"))
        unmatched = {n["note_id"]: n["unmatched"] for n in log["notes"]}
    assessed = {}
    if args.assessments:
        for r in read_jsonl(args.assessments):
            if args.assessment_variant is None or r.get("variant") == args.assessment_variant:
                assessed[r["note_id"]] = r

    inputs = [{"note_id": n["note_id"], "patient_key": n["patient_id"], "text": n["text"],
               "spans": predicted[n["note_id"]]} for n in notes]
    replacer = Replacer(args.seed).fit(inputs)
    audits = []
    for note in inputs:
        _, changes = replacer.apply(note)
        audits.append(build_note_audit(
            note["note_id"], note["text"], note["spans"], changes, args.detector,
            {name: spans.get(note["note_id"], []) for name, spans in others.items()},
            unmatched.get(note["note_id"], []), assessed.get(note["note_id"]), args.low_confidence))
    summary = summarize(audits)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    Path(f"{out}.json").write_text(json.dumps({"summary": summary, "notes": audits}, indent=2, sort_keys=True) + "\n",
                                   encoding="utf-8", newline="\n")
    Path(f"{out}.html").write_text(render(audits, summary), encoding="utf-8", newline="\n")
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"-> {out}.json, {out}.html (contain original identifiers: do not share)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
