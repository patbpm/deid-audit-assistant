"""Does reading a patient's notes together find risk that no single note shows?

    python -m deid.eval.linkage                                   # dry run: sizes the run, calls nothing
    python -m deid.eval.linkage --live --max-total-tokens 150000

Twelve invented patients with three cleaned notes each (deid.synth.linkage): six planted, where each note
holds one mild detail and the three together describe one findable person, and six ordinary controls.
For each patient the reviewer reads every note alone and then all three together. The result per patient
is the risk of each single note, the risk read together, and whether the pipeline would add a linkage item.

What would count as the idea working: planted patients flagged more often than controls. What would not:
a flag on controls. Whatever comes out is reported. Twelve patients is a demonstration, not a measurement;
the reviewer's risk level is a model's judgment and never a guarantee.
"""

import argparse
import json
from pathlib import Path

from deid.detect.client import Budget, ChatClient, LargerLimitRetry, estimate_tokens
from deid.detect.detector import Cache
from deid.redteam.assess import MaskedView, assess_note
from deid.redteam.bundle import RANK, bundle_view, linkage_item
from deid.redteam.prompt import PROMPT_VERSION, build_messages
from deid.synth.linkage import bundles


def view_of(text):
    return MaskedView(text, [])


def assess_patient(client, bundle, cache):
    """Single-note assessments, the bundle assessment, the pipeline's item (or None), and the calls' usage."""
    views = [view_of(t) for t in bundle["notes"]]
    singles = [assess_note(client, v, cache) for v in views]
    together = assess_note(client, bundle_view(views), cache)
    item = linkage_item([f"{bundle['patient']}-{i}" for i in range(1, len(views) + 1)], [s.risk for s in singles], together, views)
    return singles, together, item


def summarize(rows):
    def rate(kind, key):
        sel = [r for r in rows if r["kind"] == kind]
        return {"patients": len(sel), key: sum(bool(r[key]) for r in sel)}
    return {"planted": {**rate("planted", "flagged"), "any_single_medium_or_high": sum(
        max(RANK.get(x, 0) for x in r["single_risks"]) >= 1 for r in rows if r["kind"] == "planted"),
        "together_medium_or_high": sum(RANK.get(r["together_risk"], 0) >= 1 for r in rows if r["kind"] == "planted")},
            "control": {**rate("control", "flagged"), "any_single_medium_or_high": sum(
                max(RANK.get(x, 0) for x in r["single_risks"]) >= 1 for r in rows if r["kind"] == "control"),
                "together_medium_or_high": sum(RANK.get(r["together_risk"], 0) >= 1 for r in rows if r["kind"] == "control")}}


def markdown(rows, summary):
    lines = ["| Patient | Kind | Single notes | Together | Linkage item |", "|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['patient']} | {r['kind']} | {', '.join(r['single_risks'])} | {r['together_risk']} | {'yes' if r['flagged'] else 'no'} |")
    p, c = summary["planted"], summary["control"]
    lines += ["", f"Planted: {p['flagged']} of {p['patients']} flagged; read together {p['together_medium_or_high']} rated medium or high; "
                  f"{p['any_single_medium_or_high']} had a single note already rated medium or high.",
              f"Controls: {c['flagged']} of {c['patients']} flagged; read together {c['together_medium_or_high']} rated medium or high; "
              f"{c['any_single_medium_or_high']} had a single note already rated medium or high."]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", choices=("meta", "custom"), default="meta")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--max-total-tokens", type=int, default=100_000)
    parser.add_argument("--max-output-tokens", type=int, default=4096)
    parser.add_argument("--retry-output-tokens", type=int, default=16384)
    parser.add_argument("--price-in", type=float)
    parser.add_argument("--price-out", type=float)
    parser.add_argument("--cache-dir", default="runs/cache-linkage")
    parser.add_argument("--out", default="results/linkage")
    args = parser.parse_args(argv)
    data = bundles()
    if not args.live:
        calls = sum(len(b["notes"]) + 1 for b in data)
        guess = sum(estimate_tokens(" ".join(m["content"] for m in build_messages(t))) for b in data for t in b["notes"] + [" ".join(b["notes"])])
        print(f"DRY RUN (nothing sent). {len(data)} patients, {calls} reviewer calls, about {guess} input tokens; output is not predictable. "
              "Add --live and --max-total-tokens to run.")
        return 0
    client = LargerLimitRetry(ChatClient.from_env(args.provider, args.max_output_tokens), args.retry_output_tokens)
    cache, budget = Cache(args.cache_dir, PROMPT_VERSION), Budget(args.max_total_tokens, args.price_in, args.price_out)
    rows = []
    for b in data:
        if budget.exceeded:
            print("STOPPED EARLY: token cap reached. Raise --max-total-tokens only with Patrick's approval.")
            break
        singles, together, item = assess_patient(client, b, cache)
        for a in (*singles, together):
            budget.add(a.usage)
        rows.append({"patient": b["patient"], "kind": b["kind"], "single_risks": [s.risk for s in singles],
                     "together_risk": together.risk, "flagged": item is not None, "item": item,
                     "together_clues": [{k: c[k] for k in ("text", "category", "why")} for c in together.clues],
                     "unreadable": [a.parse_error for a in (*singles, together)]})
    summary = summarize(rows)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "linkage.json").write_text(json.dumps({"rows": rows, "summary": summary, "model": client.model,
                                                  "tokens_in": budget.tokens_in, "tokens_out": budget.tokens_out,
                                                  "cost_usd": budget.cost_usd}, indent=2, sort_keys=True) + "\n",
                                      encoding="utf-8", newline="\n")
    print(markdown(rows, summary))
    print(f"tokens in {budget.tokens_in}, out {budget.tokens_out}, cost {budget.cost_usd}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
