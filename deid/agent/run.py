"""Run the whole agent on dev notes: detect, verify, replace, red-team, feed back, audit.

    python -m deid.agent.run                       # dry run: describes the stages and sizes the run, calls nothing
    python -m deid.agent.run --live --limit 5      # real calls (billed unless credits are applied)

Safety defaults: dry run unless --live; dev split only (--allow-test is for the
final reporting run); at most --limit notes (default 5, 0 = all); a token cap
checked between notes (a note in progress can overshoot it by a few calls).
Per note there are at most 1 detection call, 1 verification call (only if some
span is uncertain) and 1 + --max-rounds red-team calls. Only note text and the
masked cleaned view are sent, never the answers.

Writes, under --out-dir (git-ignored runs/):
  <name>.notes.jsonl     the cleaned notes
  <name>.detector.jsonl  spans from the detector alone
  <name>.final.jsonl     spans after red-team feedback (both are scored here)
  <name>.audit.json/.html, <name>.key.json   contain original identifiers or the key: do not share
and aggregate numbers only under --results-dir (results/dev/<name>.json).
"""

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path

from deid.audit.build import summarize
from deid.audit.report import render
from deid.audit.verify import LOW_CONFIDENCE
from deid.baselines.common import read_notes, write_predictions
from deid.detect.client import Budget, ChatClient, LargerLimitRetry, estimate_tokens
from deid.detect.detector import Cache
from deid.detect.prompt import PROMPT_VERSION as DETECT_VERSION
from deid.detect.prompt import build_messages
from deid.eval.run import run as run_eval
from deid.eval.run import split_of
from deid.redteam.prompt import PROMPT_VERSION as REDTEAM_VERSION

from .pipeline import detect_and_verify, review_and_clean
from .verifier import PROMPT_VERSION as VERIFY_VERSION


def write_jsonl(path, records):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def spans_of(spans):
    return [{k: v for k, v in s.items() if v is not None} for s in spans]


def aggregate(args, client, budget, batch, outcomes, stopped):
    verdicts = Counter(v["decision"] for d in batch for v in d.verdicts.values())
    live = [d for d in batch if not d.flags["detect_cached"]]
    latencies = sorted(d.flags["latency_s"] for d in live)
    return {
        "name": args.name, "provider": args.provider, "model": client.model,
        "prompt_versions": {"detect": DETECT_VERSION, "verify": VERIFY_VERSION, "redteam": REDTEAM_VERSION},
        "request_params": client.params, "split": args.split, "max_rounds": args.max_rounds,
        "low_confidence": args.low_confidence,
        "notes_requested": args.requested, "notes_detected": len(batch), "notes_finished": len(outcomes),
        "notes_not_cleaned": sum(bool(o.detected.failures) for o in outcomes),
        "retry_output_tokens": args.retry_output_tokens,
        "stopped_early": stopped,
        "parse_errors": {"detect": sum(d.flags["detect_parse_error"] for d in batch),
                         "verify": sum(d.flags["verify_parse_error"] for d in batch),
                         "redteam": sum(o.calls["redteam_parse_errors"] for o in outcomes)},
        "truncated": sum(d.flags["detect_truncated"] or d.flags["verify_truncated"] for d in batch),
        "unmatched_strings": sum(len(d.unmatched) for d in batch),
        "verifier": {"spans_asked": sum(d.flags["verify_asked"] for d in batch), "verdicts": dict(verdicts)},
        "redteam_calls": sum(o.calls["redteam_calls"] for o in outcomes),
        "risk_before_feedback": dict(sorted(Counter(o.risk_before for o in outcomes).items())),
        "risk_after_feedback": dict(sorted(Counter(o.risk_after for o in outcomes).items())),
        "spans_added_by_feedback": sum(len(o.added) for o in outcomes),
        "audit": summarize([o.audit for o in outcomes]),
        "tokens_in": budget.tokens_in, "tokens_out": budget.tokens_out,
        "max_total_tokens": budget.max_total_tokens, "cost_usd": budget.cost_usd,
        "latency_s_median_detect_verify": statistics.median(latencies) if latencies else None,
    }


def dry_run(notes, provider, args):
    est = estimate_tokens(" ".join(m["content"] for m in build_messages(notes[0]["text"])))
    print(f"DRY RUN (nothing sent). Provider: {provider}. {len(notes)} dev notes.")
    print(f"Stages per note: detect (prompt {DETECT_VERSION}), verify uncertain spans (prompt {VERIFY_VERSION}, "
          f"only if a span has confidence below {args.low_confidence} or an odd shape), replace, red-team review "
          f"(prompt {REDTEAM_VERSION}), and up to {args.max_rounds} more rounds if leftovers are found.")
    print(f"Calls: at most {len(notes) * (2 + 1 + args.max_rounds)} "
          f"(the smoke tests averaged about 3.7k tokens per detection call and 2.3k per red-team call, "
          f"with more for extra rounds). First note's detection input is about {est} tokens.")
    print(f"Token cap: {args.max_total_tokens}.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", choices=("meta", "custom"), default="meta")
    parser.add_argument("--name", default=None, help="run name (default: agent-<provider>-<split>)")
    parser.add_argument("--notes", default="data/generated/notes.jsonl")
    parser.add_argument("--split", choices=("dev", "test"), default="dev")
    parser.add_argument("--allow-test", action="store_true", help="needed for --split test")
    parser.add_argument("--unlabeled", action="store_true",
                        help="notes without ground truth (for example from deid.ingest.run): every note in the "
                             "file is used, nothing is scored")
    parser.add_argument("--limit", type=int, default=5, help="notes to process (0 = all)")
    parser.add_argument("--max-rounds", type=int, default=2, help="extra feedback rounds per note")
    parser.add_argument("--low-confidence", type=float, default=LOW_CONFIDENCE)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--live", action="store_true", help="make real API calls")
    parser.add_argument("--max-total-tokens", type=int, default=100_000)
    parser.add_argument("--max-output-tokens", type=int, default=4096)
    parser.add_argument("--retry-output-tokens", type=int, default=16384,
                        help="a reply cut off at the limit is asked again once with this limit (0 = never)")
    parser.add_argument("--price-in", type=float, help="USD per million input tokens")
    parser.add_argument("--price-out", type=float, help="USD per million output tokens")
    parser.add_argument("--cache-dir", default="runs")
    parser.add_argument("--out-dir", default="runs")
    parser.add_argument("--results-dir", default="results/dev")
    args = parser.parse_args(argv)
    args.name = args.name or f"agent-{args.provider}-{args.split}"
    if args.split == "test" and not args.allow_test:
        parser.error("the test split is for the final reporting run; tune on dev, or pass --allow-test")

    notes = read_notes(args.notes)
    if args.unlabeled:
        notes = [{**n, "patient_id": n.get("patient_id") or n["note_id"]} for n in notes]
    else:
        notes = [n for n in notes if split_of(n["patient_id"]) == args.split]
    notes = notes[: args.limit] if args.limit else notes
    args.requested = len(notes)
    if not args.live:
        dry_run(notes, args.provider, args)
        return 0

    client = LargerLimitRetry(ChatClient.from_env(args.provider, args.max_output_tokens), args.retry_output_tokens)
    budget = Budget(args.max_total_tokens, args.price_in, args.price_out)
    root = Path(args.cache_dir)

    def progress(stage, done, total, b):
        print(f"{stage}: {done}/{total} notes, {b.total} tokens so far", flush=True)

    batch, stopped1 = detect_and_verify(
        notes, client, Cache(root / "cache"), Cache(root / "cache-verify", VERIFY_VERSION), budget,
        args.low_confidence, progress)
    outcomes, stopped2, replacer = review_and_clean(
        batch, client, Cache(root / "cache-redteam", REDTEAM_VERSION), budget, args.seed,
        args.low_confidence, args.max_rounds, progress)

    out_dir, results_dir = Path(args.out_dir), Path(args.results_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / args.name
    # A note that could not be cleaned is never written as cleaned: it is listed in <name>.failed.json instead.
    write_jsonl(f"{base}.notes.jsonl", [{"note_id": o.note_id, "text": o.cleaned} for o in outcomes
                                        if o.cleaned is not None])
    failed = [{"note_id": o.note_id, "reasons": o.detected.failures} for o in outcomes if o.detected.failures]
    Path(f"{base}.failed.json").write_text(json.dumps(failed, indent=2) + "\n", encoding="utf-8", newline="\n")
    write_predictions({o.note_id: spans_of(o.detected.spans) for o in outcomes}, f"{base}.detector.jsonl")
    write_predictions({o.note_id: spans_of(o.final_spans) for o in outcomes}, f"{base}.final.jsonl")
    Path(f"{base}.key.json").write_text(
        json.dumps(replacer.key_tables(), indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    audits = [o.audit for o in outcomes]
    summary_audit = summarize(audits)
    Path(f"{base}.audit.json").write_text(
        json.dumps({"summary": summary_audit, "notes": audits}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n")
    Path(f"{base}.audit.html").write_text(render(audits, summary_audit), encoding="utf-8", newline="\n")
    summary = aggregate(args, client, budget, batch, outcomes, stopped1 or stopped2)
    (results_dir / f"{args.name}.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    if not args.unlabeled:
        for stage in ("detector", "final"):
            run_eval(args.notes, f"{base}.{stage}.jsonl", f"{args.name}-{stage}", args.split, results_dir,
                     only_predicted=True)
    print(json.dumps(summary, indent=2, sort_keys=True))
    if args.unlabeled:
        print("unlabeled notes: nothing was scored (no ground truth)")
    else:
        print(f"scores: {results_dir}/{args.name}-detector-{args.split}.json and -final-{args.split}.json")
    if failed:
        print(f"NOT CLEANED: {len(failed)} note(s) were left out of {base}.notes.jsonl; see {base}.failed.json")
    print(f"-> {base}.* (audit, key and notes contain original identifiers or the key: do not share)")
    if stopped1 or stopped2:
        print("STOPPED EARLY: token cap reached. Raise --max-total-tokens only with Patrick's approval.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
