"""Philter (philter-ucsf 1.0.3) baseline with its bundled philter_delta config.

    python -m deid.baselines.philter_baseline --out runs/philter.jsonl

Philter treats everything it cannot whitelist as PHI and writes the note back
with each masked character replaced by '*'. It does not say which kind of
identifier it masked, so predictions are derived from the mask and written with
the type-agnostic label "PHI"; score them with `--agnostic`.

Compatibility shim: Philter's bundled patterns put inline flags such as (?i)
in the middle of an expression. Python 3.6-3.10 accepted that and applied the
flag to the whole pattern; Python 3.11+ rejects it. The shim below moves such
flags to the front of the pattern, which keeps the old meaning. This is the
only change made to Philter, but it means results come from Philter running
through a shim on Python 3.14, not from an unmodified install.

Mask-to-span rules (these affect precision counts, not recall):
  * a span is a run of masked characters;
  * runs separated by a single space, hyphen, slash or period are merged, so
    "**/**/****" and "**** *****" each become one span.
"""

import argparse
import os
import re
import shutil
from contextlib import contextmanager
from pathlib import Path

from .common import read_notes, write_predictions

GAP = re.compile(r"[ \-/.]")
PHI = "PHI"
GLOBAL_FLAGS = re.compile(r"\(\?([aiLmsux]+)\)")


def hoist_global_flags(pattern):
    """Move mid-pattern global flag groups like (?i) to the start."""
    flags = "".join(sorted(set("".join(GLOBAL_FLAGS.findall(pattern)))))
    if not flags:
        return pattern
    return f"(?{flags})" + GLOBAL_FLAGS.sub("", pattern)


class _ReWithHoistedFlags:
    """Stands in for the `re` module inside philter_ucsf.philter."""

    def __getattr__(self, name):
        return getattr(re, name)

    def compile(self, pattern, flags=0):
        return re.compile(hoist_global_flags(pattern), flags)


def mask_to_spans(original, masked):
    """Spans (start, end, type PHI) for characters masked in `masked`."""
    if len(original) != len(masked):
        raise ValueError(f"mask length {len(masked)} != original length {len(original)}")
    runs = []
    start = None
    for i, (o, m) in enumerate(zip(original, masked)):
        is_masked = m == "*" and o != "*"
        if is_masked and start is None:
            start = i
        elif not is_masked and start is not None:
            runs.append([start, i])
            start = None
    if start is not None:
        runs.append([start, len(original)])

    merged = []
    for run in runs:
        if merged and run[0] - merged[-1][1] == 1 and GAP.fullmatch(original[merged[-1][1]]):
            merged[-1][1] = run[1]
        else:
            merged.append(run)
    return [{"start": s, "end": e, "type": PHI} for s, e in merged]


@contextmanager
def working_directory(path):
    previous = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def run_philter(notes, work_dir):
    """Mask every note with Philter; return {note_id: masked text}."""
    import philter_ucsf
    import philter_ucsf.philter as philter_module
    from philter_ucsf.philter import Philter

    philter_module.re = _ReWithHoistedFlags()

    package = Path(philter_ucsf.__file__).resolve().parent
    work_dir = Path(work_dir).resolve()
    in_dir, out_dir = work_dir / "in", work_dir / "out"
    for directory in (in_dir, out_dir):
        shutil.rmtree(directory, ignore_errors=True)
        directory.mkdir(parents=True)
    for note in notes:
        with open(in_dir / f"{note['note_id']}.txt", "w", encoding="utf-8", newline="\n") as handle:
            handle.write(note["text"])

    config = {
        "verbose": False,
        "run_eval": False,
        "finpath": str(in_dir) + os.sep,
        "foutpath": str(out_dir) + os.sep,
        "outformat": "asterisk",
        "filters": str(package / "configs" / "philter_delta.json"),
        "cachepos": None,
    }
    # The config refers to filter files relative to the package directory.
    with working_directory(package):
        philter = Philter(config)
        philter.map_coordinates()
        philter.transform()

    masked = {}
    for note in notes:
        with open(out_dir / f"{note['note_id']}.txt", encoding="utf-8", newline="") as handle:
            masked[note["note_id"]] = handle.read().replace("\r\n", "\n")
    return masked


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--notes", default="data/generated/notes.jsonl")
    parser.add_argument("--out", default="runs/philter.jsonl")
    parser.add_argument("--work", default="runs/philter_work")
    parser.add_argument("--limit", type=int, default=0, help="only the first N notes (debugging)")
    args = parser.parse_args(argv)

    notes = read_notes(args.notes)
    if args.limit:
        notes = notes[: args.limit]
    masked = run_philter(notes, args.work)
    predictions = {n["note_id"]: mask_to_spans(n["text"], masked[n["note_id"]]) for n in notes}
    write_predictions(predictions, args.out)
    print(f"wrote predictions for {len(notes)} notes to {args.out}")


if __name__ == "__main__":
    main()
