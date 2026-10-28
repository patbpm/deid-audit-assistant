"""Run the re-identification red-team on probe notes built from the dev split.

    python -m deid.redteam.run                      # dry run: shows the prompt and a size estimate, calls nothing
    python -m deid.redteam.run --live --limit 5     # real calls (billed unless credits are applied)

Each chosen dev note becomes up to three probes (control, planted, leak; see
deid.redteam.probes). Safety defaults: dry run unless --live; the dev split only
(--allow-test is for the final reporting run); at most --limit notes (default 5,
0 = all); a token cap that stops the run. Only masked note text is sent, never
the answers. Writes runs/<name>.jsonl (records, synthetic text only) and
results/dev/<name>.json (scores).
"""

import argparse
import json
import statistics
from pathlib import Path

from deid.baselines.common import read_notes
from deid.detect.client import Budget, ChatClient, estimate_tokens
from deid.detect.detector import Cache
from deid.eval.run import split_of
from deid.replace.engine import Replacer

from .assess import assess_note, masked_view
from .loop import harden, review_items
from .probes import VARIANTS, make_probe
from .prompt import PROMPT_VERSION, SYSTEM, build_messages
from .score import score


def build_probes(notes, variants, seed):
    probes = []
    for note in notes:
        for variant in variants:
            probe = make_probe(note, variant, seed)
            probes.append({**probe, "variant": variant, "note_id": note["note_id"],
                           "patient_key": note["patient_id"]})
    return probes


def record_of(probe, assessments, changes, added, leaked_after=None):
    first = assessments[0]
    return {
        "note_id": probe["note_id"], "variant": probe["variant"], "category": probe["category"],
        "planted": probe["planted"],
        "withheld": [{k: w[k] for k in ("start", "end", "type")} for w in probe["withheld"]],
        "risk_model": first.risk_model, "risk": first.risk, "clues": first.clues,
        "parse_error": first.parse_error, "truncated": first.truncated,
        "dropped_clues": first.dropped_clues,
        "review": review_items(first), "rounds": len(assessments),
        "risk_after_feedback": assessments[-1].risk, "spans_added_by_feedback": added,
        "withheld_still_present": leaked_after,
        "flagged_replacements": sum(c["flagged"] for c in changes),
        "cached": all(a.cached for a in assessments),
        "usage": {k: sum(a.usage.get(k, 0) for a in assessments) for k in ("prompt_tokens", "completion_tokens")},
        "latency_s": sum(a.latency_s for a in assessments),
    }


def run_probes(probes, replacer, client, cache, budget, use_feedback=False, progress=None):
    records, stopped = [], False
    for probe in probes:
        if budget.exceeded:
            stopped = True
            break
        note = {"text": probe["text"], "spans": probe["spans"],
                "patient_key": probe["patient_key"], "note_id": probe["note_id"]}
        leaked = None
        if use_feedback and probe["variant"] == "leak":
            result = harden(replacer, note, client, cache)
            assessments, changes, added = result.assessments, result.changes, result.added
            leaked = sum(w_text in result.text for w_text in withheld_texts(probe))
        else:
            text, changes = replacer.apply(note)
            assessments = [assess_note(client, masked_view(probe["text"], changes), cache)]
            added = []
        for a in assessments:
            budget.add(a.usage)
        records.append(record_of(probe, assessments, changes, added, leaked))
        if progress:
            progress(len(records), len(probes), budget)
    return records, stopped


def withheld_texts(probe):
    return [probe["text"][w["start"]:w["end"]] for w in probe["withheld"]]


def summarize(args, client, records, budget, requested, stopped):
    live = [r for r in records if not r["cached"]]
    latencies = sorted(r["latency_s"] for r in live)
    return {
        "name": args.name, "provider": args.provider, "model": client.model,
        "prompt_version": PROMPT_VERSION, "request_params": client.params,
        "split": args.split, "notes": args.limit or "all", "variants": args.variants,
        "feedback_loop": args.feedback, "probes_requested": requested, "probes_done": len(records),
        "stopped_early": stopped, "unreadable_replies": sum(r["parse_error"] for r in records),
        "truncated": sum(r["truncated"] for r in records),
        "tokens_in": budget.tokens_in, "tokens_out": budget.tokens_out,
        "max_total_tokens": budget.max_total_tokens, "cost_usd": budget.cost_usd,
        "latency_s_median": statistics.median(latencies) if latencies else None,
    }


def dry_run(probes, provider, feedback):
    first = next((p for p in probes if p["variant"] == "planted"), probes[0])
    replacer = Replacer(0).fit([{"text": p["text"], "spans": p["spans"]} for p in probes])
    _, changes = replacer.apply({"text": first["text"], "spans": first["spans"],
                                 "patient_key": first["patient_key"]})
    view = masked_view(first["text"], changes)
    est = sum(estimate_tokens(m["content"]) for m in build_messages(view.text))
    print(f"DRY RUN (nothing sent). Provider: {provider}. Prompt version {PROMPT_VERSION}.")
    print(f"{len(probes)} probes (one call each; the feedback loop adds up to 2 more calls per leak probe"
          f"{'' if feedback else ', off'}); about {est} input tokens for the first (rough estimate, "
          f"~4 chars/token), plus output and reasoning tokens.")
    print("\n--- system ---\n" + SYSTEM)
    print(f"\n--- user (a {first['variant']} probe, masked) ---\n" + build_messages(view.text)[1]["content"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", choices=("meta", "custom"), default="meta")
    parser.add_argument("--name", default=None, help="run name (default: redteam-<provider>-<split>)")
    parser.add_argument("--notes", default="data/generated/notes.jsonl")
    parser.add_argument("--split", choices=("dev", "test"), default="dev")
    parser.add_argument("--allow-test", action="store_true", help="needed for --split test")
    parser.add_argument("--limit", type=int, default=5, help="notes to use (0 = all)")
    parser.add_argument("--variants", nargs="+", choices=VARIANTS, default=list(VARIANTS))
    parser.add_argument("--feedback", action="store_true", help="send leftovers back and re-clean (leak probes)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--live", action="store_true", help="make real API calls")
    parser.add_argument("--max-total-tokens", type=int, default=100_000)
    parser.add_argument("--max-output-tokens", type=int, default=4096)
    parser.add_argument("--price-in", type=float, help="USD per million input tokens")
    parser.add_argument("--price-out", type=float, help="USD per million output tokens")
    parser.add_argument("--cache-dir", default="runs/cache-redteam")
    parser.add_argument("--out-dir", default="runs")
    parser.add_argument("--results-dir", default="results/dev")
    args = parser.parse_args(argv)
    args.name = args.name or f"redteam-{args.provider}-{args.split}"
    if args.split == "test" and not args.allow_test:
        parser.error("the test split is for the final reporting run; tune on dev, or pass --allow-test")

    notes = [n for n in read_notes(args.notes) if split_of(n["patient_id"]) == args.split]
    notes = notes[: args.limit] if args.limit else notes
    probes = build_probes(notes, args.variants, args.seed)
    if not args.live:
        dry_run(probes, args.provider, args.feedback)
        return 0

    client = ChatClient.from_env(args.provider, args.max_output_tokens)
    budget = Budget(args.max_total_tokens, args.price_in, args.price_out)
    replacer = Replacer(args.seed).fit([{"text": p["text"], "spans": p["spans"]} for p in probes])

    def progress(done, total, b):
        print(f"{done}/{total} probes, {b.total} tokens so far", flush=True)

    records, stopped = run_probes(probes, replacer, client, Cache(args.cache_dir, PROMPT_VERSION),
                                  budget, args.feedback, progress)
    out_dir, results_dir = Path(args.out_dir), Path(args.results_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / f"{args.name}.jsonl", "w", encoding="utf-8", newline="\n") as handle:
        for r in records:
            handle.write(json.dumps(r, sort_keys=True) + "\n")
    result = {"summary": summarize(args, client, records, budget, len(probes), stopped),
              "scores": score(records)}
    (results_dir / f"{args.name}.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    if stopped:
        print("STOPPED EARLY: token cap reached. Raise --max-total-tokens only with Patrick's approval.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
