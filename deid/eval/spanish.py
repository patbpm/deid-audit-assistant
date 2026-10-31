"""Spanish-language notes: does the replacement step cope, and does the detector find the identifiers?

    python -m deid.synth.spanish                                   # builds data/generated/es (40 notes)
    python -m deid.eval.spanish check                              # offline: true labels through the Spanish replacement engine
    python -m deid.eval.spanish detect                             # dry run
    python -m deid.eval.spanish detect --live --max-total-tokens 250000
    python -m deid.eval.spanish score --pred runs/es-detector.jsonl --name es-detector

`check` needs no model. It applies the replacement engine (language es: Spanish stand-in names, dates read
day-first) to the TRUE spans and reports: original names, IDs, phones, emails and addresses left in a note;
replacements that fell back to a tag; whether every patient's dates moved by one shift; and the rules used.
It shows the engine copes with these formats, not that a detector finds the identifiers: `detect` and
`score` do that, with a hosted model.
"""

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from deid.detect.client import Budget, ChatClient, LargerLimitRetry, estimate_tokens
from deid.detect.detector import Cache
from deid.detect.prompt import build_messages
from deid.detect.run import run_detection
from deid.eval.run import read_jsonl, run as run_eval
from deid.replace import dates
from deid.replace.engine import Replacer, name_words

NOTES = "data/generated/es/notes.jsonl"
LETTERS = r"[^\W\d_]"


def whole_word(token, text):
    return re.search(rf"(?<!{LETTERS}){re.escape(token)}(?!{LETTERS})", text, re.I) is not None


def check(notes, seed=0):
    spans_by = [{"text": n["text"], "spans": [{"start": s["start"], "end": s["end"], "type": s["type"]} for s in n["spans"]]} for n in notes]
    replacer = Replacer(seed, lang="es").fit(spans_by)
    leaks, fallbacks, flagged, rules = [], 0, 0, Counter()
    deltas = defaultdict(set)
    dated = 0
    for n, spans in zip(notes, spans_by):
        new, changes = replacer.apply({**spans, "patient_key": n["patient_id"]})
        for c in changes:
            rules[c["rule"]] += 1
            fallbacks += c["rule"] == "fallback-tag"
            flagged += bool(c["flagged"])
        for s in n["spans"]:
            value = s["text"]
            if s["type"] == "NAME":
                gone = [w for w in name_words(value) if len(w) > 2 and whole_word(w, new)]
            elif s["type"] == "DATE":
                gone = []
            else:
                gone = [value] if value in new else []
            leaks += [{"note_id": n["note_id"], "type": s["type"], "left": g} for g in gone]
        for c in changes:
            if c["type"] != "DATE" or c["flagged"]:
                continue
            try:
                before = dates.parse_date(c["original"], True)
                after = dates.parse_date(c["replacement"], True)
            except dates.DateError:
                continue
            if before.has_year and after.has_year:
                dated += 1
                deltas[n["patient_id"]].add((dates.to_date(after, None) - dates.to_date(before, None)).days)
    return {"notes": len(notes), "replacements": sum(rules.values()), "leaks": leaks, "fallback_tags": fallbacks,
            "flagged": flagged, "rules": dict(sorted(rules.items())), "dates_compared": dated,
            "patients_with_one_shift": sum(len(v) == 1 for v in deltas.values()), "patients_with_dates": len(deltas)}


def do_check(args):
    result = check(read_jsonl(args.notes))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "es-replacement-check.json").write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                                                   encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in result.items() if k != "leaks"}, indent=2, sort_keys=True, ensure_ascii=False))
    print(f"original identifiers left in a cleaned note: {len(result['leaks'])}")
    return 0 if not result["leaks"] else 1


def do_detect(args):
    notes = read_jsonl(args.notes)[: args.limit or None]
    if not args.live:
        guess = sum(estimate_tokens(" ".join(m["content"] for m in build_messages(n["text"]))) for n in notes)
        print(f"DRY RUN (nothing sent). {len(notes)} notes: about {guess} input tokens; output is not predictable "
              "(the model reasons). Add --live and --max-total-tokens to run.")
        return 0
    client = LargerLimitRetry(ChatClient.from_env(args.provider, args.max_output_tokens), args.retry_output_tokens)
    budget = Budget(args.max_total_tokens, args.price_in, args.price_out)
    predictions, per_note, stopped = run_detection(
        notes, client, Cache(args.cache_dir), budget,
        lambda done, total, b: print(f"{done}/{total} notes, {b.total} tokens so far", flush=True))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "es-detector.jsonl", "w", encoding="utf-8", newline="\n") as handle:
        for note_id, spans in predictions.items():
            handle.write(json.dumps({"note_id": note_id, "spans": spans}, sort_keys=True) + "\n")
    summary = {"model": client.model, "request_params": client.params, "notes_done": len(per_note),
               "notes_from_cache": sum(n["cached"] for n in per_note), "stopped_early": stopped,
               "parse_errors": sum(n["parse_error"] for n in per_note), "truncated": sum(n["truncated"] for n in per_note),
               "tokens_in": budget.tokens_in, "tokens_out": budget.tokens_out, "cost_usd": budget.cost_usd}
    (out / "es-detector.log.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(summary, indent=2, sort_keys=True))
    if stopped:
        print("STOPPED EARLY: token cap reached. Raise --max-total-tokens only with Patrick's approval.")
    return 0


def do_score(args):
    for agnostic in (False, True):
        run_eval(args.notes, args.pred, args.name, "all", args.out, agnostic=agnostic)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("check", help="offline: true labels through the Spanish replacement engine")
    c.add_argument("--notes", default=NOTES)
    c.add_argument("--out", default="results/es")
    d = sub.add_parser("detect", help="run the detector on the Spanish notes (dry run unless --live)")
    d.add_argument("--notes", default=NOTES)
    d.add_argument("--provider", choices=("meta", "custom"), default="meta")
    d.add_argument("--limit", type=int, default=0)
    d.add_argument("--live", action="store_true")
    d.add_argument("--max-total-tokens", type=int, default=100_000)
    d.add_argument("--max-output-tokens", type=int, default=4096)
    d.add_argument("--retry-output-tokens", type=int, default=16384)
    d.add_argument("--price-in", type=float)
    d.add_argument("--price-out", type=float)
    d.add_argument("--cache-dir", default="runs/cache")
    d.add_argument("--out-dir", default="runs")
    s = sub.add_parser("score", help="score saved predictions on the Spanish notes")
    s.add_argument("--pred", required=True)
    s.add_argument("--name", required=True)
    s.add_argument("--notes", default=NOTES)
    s.add_argument("--out", default="results/es")
    args = parser.parse_args(argv)
    return {"check": do_check, "detect": do_detect, "score": do_score}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
