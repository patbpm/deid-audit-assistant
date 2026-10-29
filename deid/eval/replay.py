"""Re-read saved detector replies with the current matching rules. No model is called.

    python -m deid.eval.replay --notes data/generated/adversarial/notes.jsonl --cache runs/cache \
        --version v1 --summary results/adversarial/runs/agent-meta-adv.json --out runs/adv-replay.jsonl

The cache holds the model's raw replies, so changing how replies are turned into spans
(deid.detect.matching, deid.detect.context) can be checked on the same replies for free. A note
whose reply is not in the cache is an error, never a silent gap. Only the matching rules are
replayed: the occurrence check and verifier are model calls and are not. On a set whose errors
were read, a replay shows what a rule does, not how well it generalizes.
"""

import argparse
import json
from pathlib import Path

from deid.detect.detector import Cache, detect_note
from deid.eval.run import read_jsonl, split_of


class CacheOnly:
    """Stands in for the model client: same cache key, but any call is a missing reply."""

    def __init__(self, model, params):
        self.model, self.params = model, params

    def complete(self, messages):
        raise LookupError("no saved reply for this note (wrong --cache, --version or --summary?)")


def replay(notes, cache_dir, version, model, params):
    client, cache = CacheOnly(model, params), Cache(Path(cache_dir), version)
    out, ignored = [], 0
    for note in notes:
        found = detect_note(client, note["text"], cache)
        if found.parse_error or found.truncated:
            raise ValueError(f"{note['note_id']}: the saved reply is unreadable or cut off")
        ignored += len(found.ignored)
        out.append({"note_id": note["note_id"], "spans": [
            {k: s[k] for k in ("start", "end", "type", "confidence") if s.get(k) is not None} for s in found.spans]})
    return out, ignored


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--notes", required=True)
    parser.add_argument("--cache", default="runs/cache")
    parser.add_argument("--version", required=True, help="detection prompt version whose replies are cached (for example v1)")
    parser.add_argument("--summary", required=True, help="the run summary JSON that holds model and request_params")
    parser.add_argument("--split", choices=("dev", "test"), help="only notes of this split (main dataset)")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    summary = json.loads(Path(args.summary).read_text(encoding="utf-8"))
    notes = read_jsonl(args.notes)
    if args.split:
        notes = [n for n in notes if split_of(n["patient_id"]) == args.split]
    records, ignored = replay(notes, args.cache, args.version, summary["model"], summary["request_params"])
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    print(f"replayed {len(records)} notes from saved replies; {ignored} strings or occurrences set aside -> {args.out}")


if __name__ == "__main__":
    main()
