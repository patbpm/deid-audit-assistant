"""Run the hosted-model detector over a split and write predictions.

    python -m deid.detect.run                       # dry run: shows the prompt and a size estimate, calls nothing
    python -m deid.detect.run --live --limit 5      # real calls (billed unless credits are applied)

Safety defaults: dry run unless --live; the dev split only (--allow-test is for
the final reporting run); at most --limit notes (default 5, 0 = all); a token cap
(--max-total-tokens) that stops the run. Only note text is sent, never the
ground-truth spans. Score the output with:

    python -m deid.eval.run --pred runs/<name>.jsonl --name <name> --split dev --only-predicted --out results/dev
"""

import argparse
import json
import statistics
from pathlib import Path

from deid.baselines.common import read_notes, write_predictions
from deid.eval.run import split_of

from .client import Budget, ChatClient, LargerLimitRetry, estimate_tokens
from .detector import Cache, detect_note
from .prompt import PROMPT_VERSION, build_messages


def run_detection(notes, client, cache, budget, progress=None):
    """Detect over notes (only n["text"] is used). Stops when the budget is hit."""
    predictions, per_note = {}, []
    stopped_early = False
    for note in notes:
        if budget.exceeded:
            stopped_early = True
            break
        result = detect_note(client, note["text"], cache)
        budget.add(result.usage)
        predictions[note["note_id"]] = [
            {k: v for k, v in s.items() if v is not None} for s in result.spans
        ]
        per_note.append({
            "note_id": note["note_id"], "cached": result.cached,
            "parse_error": result.parse_error, "truncated": result.truncated,
            "unmatched": result.unmatched, "dropped_items": result.dropped_items,
            "latency_s": result.latency_s, "usage": result.usage,
        })
        if progress:
            progress(len(per_note), len(notes), budget)
    return predictions, per_note, stopped_early


def summarize_run(args, client, per_note, budget, requested, stopped_early):
    live = [n for n in per_note if not n["cached"]]
    latencies = sorted(n["latency_s"] for n in live)
    return {
        "name": args.name, "provider": args.provider, "model": client.model,
        "prompt_version": PROMPT_VERSION, "request_params": client.params,
        "split": args.split, "notes_requested": requested, "notes_done": len(per_note),
        "notes_from_cache": len(per_note) - len(live), "stopped_early": stopped_early,
        "parse_errors": sum(n["parse_error"] for n in per_note),
        "truncated": sum(n["truncated"] for n in per_note),
        "unmatched_strings": sum(len(n["unmatched"]) for n in per_note),
        "dropped_items": sum(n["dropped_items"] for n in per_note),
        "tokens_in": budget.tokens_in, "tokens_out": budget.tokens_out,
        "max_total_tokens": budget.max_total_tokens,
        "cost_usd": budget.cost_usd, "prices_usd_per_million": [budget.price_in, budget.price_out],
        "latency_s_median": statistics.median(latencies) if latencies else None,
        "latency_s_max": latencies[-1] if latencies else None,
    }


def dry_run(notes, client_hint):
    messages = build_messages(notes[0]["text"])
    est_in = sum(estimate_tokens(m["content"]) for m in messages)
    print(f"DRY RUN (nothing sent). Provider/model: {client_hint}. Prompt version {PROMPT_VERSION}.")
    print(f"{len(notes)} notes; about {est_in} input tokens for the first note (rough estimate, "
          f"~4 chars/token); about {est_in * len(notes)} for all of them, plus output and reasoning tokens.")
    print("\n--- system ---\n" + messages[0]["content"])
    print("\n--- user (first note) ---\n" + messages[1]["content"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", choices=("meta", "custom"), default="meta")
    parser.add_argument("--name", default=None, help="run name (default: <provider>-<split>)")
    parser.add_argument("--notes", default="data/generated/notes.jsonl")
    parser.add_argument("--split", choices=("dev", "test"), default="dev")
    parser.add_argument("--allow-test", action="store_true", help="needed for --split test")
    parser.add_argument("--limit", type=int, default=5, help="notes to process (0 = all)")
    parser.add_argument("--live", action="store_true", help="make real API calls")
    parser.add_argument("--max-total-tokens", type=int, default=100_000)
    parser.add_argument("--max-output-tokens", type=int, default=4096)
    parser.add_argument("--retry-output-tokens", type=int, default=0,
                        help="a reply cut off at the limit is asked again once with this limit (0 = never; the agent uses 16384)")
    parser.add_argument("--price-in", type=float, help="USD per million input tokens")
    parser.add_argument("--price-out", type=float, help="USD per million output tokens")
    parser.add_argument("--cache-dir", default="runs/cache")
    parser.add_argument("--out-dir", default="runs")
    args = parser.parse_args(argv)
    args.name = args.name or f"{args.provider}-{args.split}"

    if args.split == "test" and not args.allow_test:
        parser.error("the test split is for the final reporting run; tune on dev, or pass --allow-test")
    notes = [n for n in read_notes(args.notes) if split_of(n["patient_id"]) == args.split]
    requested = notes[: args.limit] if args.limit else notes

    if not args.live:
        dry_run(requested, args.provider)
        return 0

    client = LargerLimitRetry(ChatClient.from_env(args.provider, args.max_output_tokens), args.retry_output_tokens)
    budget = Budget(args.max_total_tokens, args.price_in, args.price_out)

    def progress(done, total, b):
        print(f"{done}/{total} notes, {b.total} tokens so far", flush=True)

    predictions, per_note, stopped = run_detection(
        requested, client, Cache(args.cache_dir), budget, progress)
    out_dir = Path(args.out_dir)
    write_predictions(predictions, out_dir / f"{args.name}.jsonl")
    summary = summarize_run(args, client, per_note, budget, len(requested), stopped)
    log = {"summary": summary, "notes": per_note}
    (out_dir / f"{args.name}.log.json").write_text(
        json.dumps(log, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(summary, indent=2, sort_keys=True))
    if stopped:
        print("STOPPED EARLY: token cap reached. Raise --max-total-tokens only with Patrick's approval.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
