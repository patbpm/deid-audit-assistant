"""Run the app's four sample notes once with the hosted model, then save the replies for replay mode.

    python scripts/record_replay_live.py --live --max-tokens 100000

Billed (a few cents to about 0.2 USD at list price). Needs the model key in the environment. Synthetic
sample notes only. Writes the live job under runs/app-replay-live (git-ignored) and the saved replies
under data/replay (committed: they are the model's answers to invented text).
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deid.app import replay, samples  # noqa: E402
from deid.app.backend import live_backend  # noqa: E402
from deid.app.jobs import JobStore  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--live", action="store_true", help="make real, billed calls")
    parser.add_argument("--max-tokens", type=int, default=100_000)
    parser.add_argument("--work-dir", default="runs/app-replay-live")
    parser.add_argument("--out", default=str(replay.DEFAULT_DIR))
    args = parser.parse_args()
    if not args.live:
        print("DRY RUN: would run the four sample notes through the app with the hosted model "
              f"(cap {args.max_tokens} tokens) and record the replies to {args.out}. Add --live.")
        return 0
    store = JobStore(args.work_dir, live_backend("meta"), args.max_tokens, 0)
    job = store.create("replay recording")
    (name, data), = samples.notes()
    store.add_file(job["id"], name, data)
    store.start(job["id"], {"confirm_synthetic": True, "token_cap": args.max_tokens})
    while True:
        j = store.get(job["id"])
        if j["state"] in ("done", "failed"):
            break
        time.sleep(1)
    print("job:", j["state"], j.get("error"), j["tokens"])
    if j["state"] != "done":
        return 1
    meta, outcomes = replay.record(Path(args.work_dir) / "cache", args.out)
    print(f"recorded {meta['replies']} replies -> {args.out}; {sum(len(o.changes) for o in outcomes)} replacements; "
          f"risk {[o.audit['risk'] for o in outcomes]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
