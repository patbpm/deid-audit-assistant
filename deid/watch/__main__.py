"""Watch a source of notes and clean them as they arrive.

    python -m deid.watch --source folder:feed --state runs/watch/demo               (offline rules, no model)
    python -m deid.watch --source sqlite:notes.db#notes --state runs/watch/db --once
    python -m deid.review.server --audit runs/watch/demo/audit.json --follow         (the review page)

Only synthetic data. With --live the note text goes to a hosted model, so --synthetic-only must be given.
"""

import argparse

from deid.app.backend import live_backend, offline_backend

from .sources import parse_source
from .watcher import Watcher


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", required=True, help="folder:PATH or sqlite:PATH#TABLE[:id_col:text_col:patient_col]")
    parser.add_argument("--state", required=True, help="where mapping, audits, released notes and status live (git-ignored)")
    parser.add_argument("--interval", type=float, default=5.0, help="seconds between looks (default 5)")
    parser.add_argument("--once", action="store_true", help="look once and exit")
    parser.add_argument("--live", action="store_true", help="use a hosted model instead of the offline rules")
    parser.add_argument("--provider", choices=("meta", "custom"), default="meta")
    parser.add_argument("--synthetic-only", action="store_true",
                        help="required with --live: you confirm every note in the source is synthetic or public")
    parser.add_argument("--max-total-tokens", type=int, default=200_000, help="stop taking new notes past this (live only)")
    args = parser.parse_args(argv)
    if args.live and not args.synthetic_only:
        parser.error("--live sends note text to a hosted service; add --synthetic-only to confirm it is all synthetic")
    try:
        source = parse_source(args.source)
    except ValueError as err:
        parser.error(str(err))
    backend = live_backend(args.provider) if args.live else offline_backend()
    watcher = Watcher(source, backend, args.state, token_cap=args.max_total_tokens)
    print(f"Watching {args.source} with {backend.label}. State: {args.state}. Status page: {args.state}/status.html")
    try:
        watcher.run(args.interval, args.once)
    except KeyboardInterrupt:
        print("stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
