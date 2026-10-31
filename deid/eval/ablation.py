"""What each stage of the agent adds, measured from saved runs. No model is called.

    python -m deid.eval.ablation --all        # dev, adversarial set B and the held-out test set
    python -m deid.eval.ablation --set b

For each set, three states of the same run are scored against the labels (type ignored, a hit is any
overlap, as in deid.eval.adversarial):

  detector      the model's saved reply read with the matching rules (deid.eval.replay; needs the
                git-ignored runs/cache)
  + name check  the run's detector output: doubtful name occurrences settled by the name-use check
  + red-team    the run's final output: leftovers the red-team reviewer found were replaced too

Two stages change no text, only what a person is asked to look at, so they are counted instead:

  verifier      the answers it gave, against whether the span it was asked about is a real identifier
  name check    what it released (left as written) against whether that text was a real identifier

The Safe Harbor rules (deid.replace.rules) are not part of this table: no labeled note has an age
of 90 or more, a ZIP outside an address, a URL or an IP address.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

from .adversarial import score_group
from .replay import replay
from .run import load_predictions, read_jsonl, split_of

SETS = {
    "dev": {"title": "200 dev notes (easy template text, the split the prompts were tuned on)",
            "notes": "data/generated/notes.jsonl", "split": "dev", "version": "v2",
            "summary": "results/dev/agent-meta-dev-v2.json", "run": "agent-meta-dev-v2"},
    "b": {"title": "adversarial set B (200 short notes written to be hard; the name check and a red-team fix were tuned on set A and read set B)",
          "notes": "data/generated/adversarial-b/notes.jsonl", "split": None, "version": "v2",
          "summary": "results/adversarial-b/runs/agent-meta-advb-rtfix.json", "run": "agent-meta-advb-rtfix"},
    "test": {"title": "400 held-out test notes (easy template text, used once)",
             "notes": "data/generated/notes.jsonl", "split": "test", "version": "v2",
             "summary": "results/test/agent-meta-test.json", "run": "agent-meta-test"},
}


def overlaps(a, b):
    return a["start"] < b["end"] and b["start"] < a["end"]


def is_true(span, note):
    return any(overlaps(span, g) for g in note["spans"])


def added_spans(before, after):
    """Spans in `after` that overlap nothing in `before`, per note id."""
    return {nid: [s for s in spans if not any(overlaps(s, b) for b in before.get(nid, []))]
            for nid, spans in after.items()}


def verifier_table(audits, notes_by_id):
    """{decision: {"real": n, "not real": n}} for the spans the verifier answered about."""
    table = {}
    for audit in audits:
        note = notes_by_id[audit["note_id"]]
        for e in audit["entries"]:
            v = e.get("verifier")
            if v:
                row = table.setdefault(v["decision"], {"real": 0, "not real": 0})
                row["real" if is_true(e, note) else "not real"] += 1
    return table


def name_check_table(audits, notes_by_id):
    """What the name check left as written, by whether that text really was an identifier."""
    released = Counter()
    for audit in audits:
        note = notes_by_id[audit["note_id"]]
        for g in audit.get("ignored", []):
            if g.get("source") == "name-use check":
                released["real identifier (a leak a person is asked about)" if is_true(g, note)
                         else "not an identifier (a false positive avoided)"] += 1
    return {"released": dict(released)}


def stage_row(name, notes, predictions, bootstrap):
    g = score_group(notes, predictions, bootstrap)
    return {"stage": name, "gold": g["gold"], "recall": g["recall"], "recall_ci95": g["recall_ci95"],
            "false_positives": g["false_positives"], "leaked_char_rate": g["leaked_char_rate"]}


def run_set(key, cache="runs/cache", run_dir="runs", bootstrap=1000):
    cfg = SETS[key]
    notes = read_jsonl(cfg["notes"])
    if cfg["split"]:
        notes = [n for n in notes if split_of(n["patient_id"]) == cfg["split"]]
    ids = {n["note_id"] for n in notes}
    by_id = {n["note_id"]: n for n in notes}
    summary = json.loads(Path(cfg["summary"]).read_text(encoding="utf-8"))
    raw, _ = replay(notes, cache, cfg["version"], summary["model"], summary["request_params"])
    raw_pred = {r["note_id"]: r["spans"] for r in raw}
    detector = load_predictions(f"{run_dir}/{cfg['run']}.detector.jsonl", ids)
    final = load_predictions(f"{run_dir}/{cfg['run']}.final.jsonl", ids)
    audit = json.loads(Path(f"{run_dir}/{cfg['run']}.audit.json").read_text(encoding="utf-8"))["notes"]
    audit = [a for a in audit if a["note_id"] in ids]
    feedback = added_spans(detector, final)
    fb_real = sum(is_true(s, by_id[nid]) for nid, spans in feedback.items() for s in spans)
    fb_all = sum(len(spans) for spans in feedback.values())
    return {
        "set": key, "title": cfg["title"], "notes": len(notes), "run": cfg["run"],
        "stages": [stage_row("detector", notes, raw_pred, bootstrap),
                   stage_row("+ name check", notes, detector, bootstrap),
                   stage_row("+ red-team feedback", notes, final, bootstrap)],
        "verifier": verifier_table(audit, by_id),
        "name_check": name_check_table(audit, by_id),
        "red_team_added": {"spans": fb_all, "real identifiers": fb_real, "not identifiers": fb_all - fb_real},
    }


def markdown(results):
    lines = []
    for r in results:
        lines += [f"### {r['title']}", "", f"{r['notes']} notes; saved run `{r['run']}`.", "",
                  "| Stage | Labeled identifiers | Recall % (95% CI) | False positives | Leaked chars % |", "|---|---|---|---|---|"]
        for s in r["stages"]:
            lo, hi = s["recall_ci95"]
            lines.append(f"| {s['stage']} | {s['gold']} | {100 * s['recall']:.1f} ({100 * lo:.1f}-{100 * hi:.1f}) | "
                         f"{s['false_positives']} | {100 * s['leaked_char_rate']:.2f} |")
        v = r["verifier"]
        lines += ["", "Verifier (changes no text; a doubt sends the span to a person): " + (
            "; ".join(f"said {k}: {x['real']} real, {x['not real']} not real" for k, x in sorted(v.items())) if v else "asked about no span."),
            "", "Name check (settles doubtful name occurrences): " + (
                "; ".join(f"left as written, {k}: {n}" for k, n in sorted(r["name_check"]["released"].items()))
                or "left nothing as written."),
            "", f"Red-team feedback added {r['red_team_added']['spans']} spans: {r['red_team_added']['real identifiers']} real "
                f"identifiers, {r['red_team_added']['not identifiers']} not identifiers.", ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--set", choices=sorted(SETS))
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--cache", default="runs/cache")
    parser.add_argument("--run-dir", default="runs")
    parser.add_argument("--out", default="results/ablation")
    parser.add_argument("--bootstrap", type=int, default=1000)
    args = parser.parse_args(argv)
    keys = sorted(SETS) if args.all else [args.set]
    if not keys or keys == [None]:
        parser.error("give --set or --all")
    results = [run_set(k, args.cache, args.run_dir, args.bootstrap) for k in keys]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for r in results:
        (out / f"{r['set']}.json").write_text(json.dumps(r, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(markdown(results))


if __name__ == "__main__":
    main()
