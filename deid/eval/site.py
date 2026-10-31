"""Does a site profile help? Run the detector on the invented-site notes without and with a profile, and score.

    python -m deid.eval.site detect --arm generic            # dry run: sizes the run, calls nothing
    python -m deid.eval.site detect --arm generic --live --max-total-tokens 400000
    python -m deid.eval.site detect --arm profile --live --max-total-tokens 400000
    python -m deid.eval.site score --pred runs/site-generic.jsonl --name generic
    python -m deid.eval.site score --pred runs/site-profile.jsonl --name profile --profile data/site/hartwell.json

Notes come from `python -m deid.synth.site` (an invented hospital whose places are named for trees).
The "profile" arm adds the profile's local rules to the detection prompt (deid.detect.site); `score
--profile` then also adds the profile's rule spans, as the agent does. Scoring ignores type (a hit is any
overlap): it reports recall on the base notes' own identifiers, on the site identifiers the profile lists,
on those it does not list, and false positives (predictions overlapping no label).
"""

import argparse
import json
from pathlib import Path

from deid.agent.pipeline import with_rules
from deid.detect import site
from deid.detect.client import Budget, ChatClient, LargerLimitRetry, estimate_tokens
from deid.detect.detector import Cache
from deid.detect.prompt import build_messages
from deid.detect.run import run_detection
from deid.eval.run import load_predictions, read_jsonl

NOTES = "data/generated/site/notes.jsonl"
PROFILE = "data/site/hartwell.json"


def overlap(a, b):
    return a["start"] < b["end"] and b["start"] < a["end"]


def score(notes, predictions):
    """Counts by group. Groups: base (labels from the generator), listed and unlisted (site identifiers)."""
    out = {g: {"gold": 0, "hit": 0} for g in ("base", "listed", "unlisted")}
    fp = pred = 0
    misses = []
    for n in notes:
        preds = predictions.get(n["note_id"], [])
        for g in n["spans"]:
            group = g.get("site") or "base"
            out[group]["gold"] += 1
            hit = any(overlap(g, p) for p in preds)
            out[group]["hit"] += hit
            if not hit and group != "base":
                misses.append({"note_id": n["note_id"], "text": g["text"], "site": group})
        pred += len(preds)
        fp += sum(not any(overlap(p, g) for g in n["spans"]) for p in preds)
    return {"groups": out, "predictions": pred, "false_positives": fp,
            "false_positives_per_note": fp / len(notes) if notes else None, "missed_site_identifiers": misses}


def merge_profile(notes, predictions, profile):
    """The pipeline's rule step on saved predictions: retype listed facility names, add rule spans."""
    out = {}
    for n in notes:
        d = type("D", (), {"note": n, "spans": predictions.get(n["note_id"], [])})()
        out[n["note_id"]] = with_rules(d, profile)
    return out


def percent(g):
    return "n/a" if not g["gold"] else f"{100 * g['hit'] / g['gold']:.1f}% ({g['hit']}/{g['gold']})"


def markdown(name, result):
    g = result["groups"]
    return (f"**{name}**: base-note identifiers {percent(g['base'])}; site identifiers the profile lists {percent(g['listed'])}; "
            f"site identifiers it does not list {percent(g['unlisted'])}; false positives {result['false_positives']} "
            f"({result['false_positives_per_note']:.2f} per note).")


def do_detect(args):
    notes = read_jsonl(args.notes)[: args.limit or None]
    profile = site.load(args.profile) if args.arm == "profile" else None
    inner = ChatClient.from_env(args.provider, args.max_output_tokens) if args.live else None
    if not args.live:
        sample = build_messages(notes[0]["text"])
        guess = sum(estimate_tokens(" ".join(m["content"] for m in sample)) for _ in notes)
        extra = len(profile.prompt_addition()) // 4 * len(notes) if profile else 0
        print(f"DRY RUN (nothing sent). {len(notes)} notes, arm {args.arm}: about {guess + extra} input tokens; "
              "output is not predictable (the model reasons). Add --live and --max-total-tokens to run.")
        return 0
    client = site.wrap(LargerLimitRetry(inner, args.retry_output_tokens), profile)
    budget = Budget(args.max_total_tokens, args.price_in, args.price_out)
    predictions, per_note, stopped = run_detection(
        notes, client, Cache(args.cache_dir), budget,
        lambda done, total, b: print(f"{done}/{total} notes, {b.total} tokens so far", flush=True))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / f"site-{args.arm}.jsonl", "w", encoding="utf-8", newline="\n") as handle:
        for note_id, spans in predictions.items():
            handle.write(json.dumps({"note_id": note_id, "spans": spans}, sort_keys=True) + "\n")
    summary = {"arm": args.arm, "model": client.model, "request_params": client.params, "notes_done": len(per_note),
               "notes_from_cache": sum(n["cached"] for n in per_note), "stopped_early": stopped,
               "parse_errors": sum(n["parse_error"] for n in per_note), "truncated": sum(n["truncated"] for n in per_note),
               "tokens_in": budget.tokens_in, "tokens_out": budget.tokens_out,
               "cost_usd": budget.cost_usd}
    (out / f"site-{args.arm}.log.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(summary, indent=2, sort_keys=True))
    if stopped:
        print("STOPPED EARLY: token cap reached. Raise --max-total-tokens only with Patrick's approval.")
    return 0


def do_score(args):
    notes = read_jsonl(args.notes)
    keep = {r["note_id"] for r in read_jsonl(args.only_in or args.pred)}  # score only notes both arms were run on
    predictions = load_predictions(args.pred, {n["note_id"] for n in notes})
    notes = [n for n in notes if n["note_id"] in keep]
    predictions = {k: v for k, v in predictions.items() if k in keep}
    if args.profile:
        predictions = merge_profile(notes, predictions, site.load(args.profile))
    result = score(notes, predictions)
    result.update(name=args.name, notes=len(notes), profile=args.profile, pred_file=args.pred)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{args.name}.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(markdown(args.name, result))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("detect", help="run the detector on the site notes (dry run unless --live)")
    d.add_argument("--arm", choices=("generic", "profile"), required=True)
    d.add_argument("--notes", default=NOTES)
    d.add_argument("--profile", default=PROFILE)
    d.add_argument("--provider", choices=("meta", "custom"), default="meta")
    d.add_argument("--limit", type=int, default=0, help="notes to process (0 = all)")
    d.add_argument("--live", action="store_true")
    d.add_argument("--max-total-tokens", type=int, default=100_000)
    d.add_argument("--max-output-tokens", type=int, default=4096)
    d.add_argument("--retry-output-tokens", type=int, default=16384)
    d.add_argument("--price-in", type=float)
    d.add_argument("--price-out", type=float)
    d.add_argument("--cache-dir", default="runs/cache")
    d.add_argument("--out-dir", default="runs")
    s = sub.add_parser("score", help="score saved predictions on the site notes")
    s.add_argument("--pred", required=True)
    s.add_argument("--name", required=True)
    s.add_argument("--notes", default=NOTES)
    s.add_argument("--profile", default=None, help="also add this profile's rule spans before scoring")
    s.add_argument("--only-in", default=None, help="score only the notes that this predictions file has (to compare arms on the same notes)")
    s.add_argument("--out", default="results/site")
    args = parser.parse_args(argv)
    return do_detect(args) if args.command == "detect" else do_score(args)


if __name__ == "__main__":
    raise SystemExit(main())
