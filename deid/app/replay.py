"""Replay mode: the app runs its whole pipeline on saved replies from a real Muse Spark run.

    python -m deid.app --replay                  # no key, no network, no cost
    python -m deid.app.replay record --from runs/app-live/cache --out data/replay

The saved replies are the hosted model's answers to the four sample notes (synthetic, invented by
the project's generator), recorded when the front page was run once with --live (recording.json has the
date and the prompt versions). Every
stage (detection, the verifier, the name check, the re-identification reviewer) reads its reply from
the saved copy by the same cache key a live run uses, so what the page shows is what that run produced
and nothing is made up. Text the recording does not hold cannot be processed in this mode: the job says
so instead of guessing. Use --live for that.
"""

import argparse
import json
import shutil
from datetime import date
from pathlib import Path

from deid.agent.pipeline import detect_and_verify, review_and_clean
from deid.agent.verifier import PROMPT_VERSION as VERIFY_VERSION
from deid.audit.verify import LOW_CONFIDENCE
from deid.detect.prompt import PROMPT_VERSION as DETECT_VERSION
from deid.detect.client import Budget
from deid.detect.detector import Cache
from deid.redteam.prompt import PROMPT_VERSION as REDTEAM_VERSION

from . import kinds, samples
from .backend import Backend

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "data" / "replay"
MODEL, PARAMS = "muse-spark-1.3", {"max_completion_tokens": 4096}  # what the recorded run used: part of every cache key
MAX_ROUNDS = 2
STAGES = (("cache", None), ("cache-verify", VERIFY_VERSION), ("cache-redteam", REDTEAM_VERSION))


class ReplayClient:
    """Looks like the hosted chat client for cache keys, and refuses every call."""
    model, params = MODEL, PARAMS

    def complete(self, messages):
        raise LookupError("this is not in the recording; start the app with --live to process new text")


def replay_backend(root=DEFAULT_DIR):
    root = Path(root)
    if not (root / "cache").is_dir():
        raise SystemExit(f"no recording at {root}; it is created by: python -m deid.app.replay record --from <cache> --out {root}")
    meta = json.loads((root / "recording.json").read_text(encoding="utf-8")) if (root / "recording.json").exists() else {}
    label = f"Replay of saved {meta.get('model', MODEL)} replies (no model is called)"
    return Backend(
        "replay", label, False, ReplayClient, verify=True, redteam=True, replay_root=root,
        notes=[f"Replay: the screens show the replies a real {meta.get('model', MODEL)} run saved on "
               f"{meta.get('recorded', 'an earlier day')} for the four sample notes. No model is called and nothing is sent anywhere.",
               "Only the sample notes can be processed in this mode; start the app with --live for other text.",
               "Tables are typed by the offline rules; audio and scanned pages need --live."])


def note_cache(root, name, version):
    return Cache(Path(root) / name, version) if version else Cache(Path(root) / name)


def missing(notes, root):
    """Ids of the notes whose detection reply is not in the recording."""
    client = ReplayClient()
    detect = note_cache(root, "cache", None)
    return [n["note_id"] for n in notes if detect.get(detect.key(client, n["text"])) is None]


class Logging(Cache):
    """A cache that remembers which saved replies were read."""

    def __init__(self, directory, version=None):
        super().__init__(directory, version) if version else super().__init__(directory)
        self.used = set()

    def get(self, key):
        found = super().get(key)
        if found is not None:
            self.used.add(key)
        return found


def sample_notes():
    (_, data), = samples.notes()
    return [{"note_id": str(r["note_id"]), "patient_id": str(r.get("patient_id") or r["note_id"]), "text": r["text"]}
            for r in kinds.notes_from_jsonl(data.decode("utf-8"))]


def record(source, out):
    """Run the sample notes through the pipeline against the saved replies in `source`, and copy only the
    replies that were read into `out`."""
    source, out = Path(source), Path(out)
    client = ReplayClient()
    caches = {name: Logging(source / name, version) for name, version in STAGES}
    notes = sample_notes()
    budget = Budget(10 ** 9)
    batch, _ = detect_and_verify(notes, client, caches["cache"], caches["cache-verify"], budget, LOW_CONFIDENCE)
    outcomes, _, _ = review_and_clean(batch, client, caches["cache-redteam"], budget, 0, LOW_CONFIDENCE, MAX_ROUNDS)
    if out.exists():
        shutil.rmtree(out)
    copied = 0
    for name, cache in caches.items():
        (out / name).mkdir(parents=True)
        for key in sorted(cache.used):
            shutil.copy(source / name / f"{key}.json", out / name / f"{key}.json")
            copied += 1
    meta = {"model": MODEL, "request_params": PARAMS, "recorded": date.today().isoformat(),
            "prompt_versions": {"detect": DETECT_VERSION, "verify": VERIFY_VERSION, "redteam": REDTEAM_VERSION},
            "notes": [n["note_id"] for n in notes], "replies": copied,
            "source": "the front page run once with --live on the four sample notes; synthetic text only"}
    (out / "recording.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return meta, outcomes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    rec = sub.add_parser("record", help="copy the saved replies the sample notes need out of a live run's cache folder")
    rec.add_argument("--from", dest="source", required=True, help="the live run's cache folder (holds cache, cache-verify, cache-redteam)")
    rec.add_argument("--out", default=str(DEFAULT_DIR))
    args = parser.parse_args(argv)
    meta, outcomes = record(args.source, args.out)
    print(f"recorded {meta['replies']} replies for {len(meta['notes'])} notes -> {args.out}; "
          f"{sum(len(o.changes) for o in outcomes)} replacements")


if __name__ == "__main__":
    main()
