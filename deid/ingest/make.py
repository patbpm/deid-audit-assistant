"""Build a small synthetic test set of dictated and scanned notes from dev notes.

    python -m deid.ingest.make --limit 5 --out data/generated/ingest

For each note: images/<note_id>.png (the written text drawn on a page with mild
scan damage), audio/<note_id>.wav (a dictation script spoken by a Windows voice),
and one line in truth.jsonl with the written text, the script and every
identifier in written and spoken form. Everything is synthetic and made offline
(the folder is git-ignored). Only dev-split notes are used unless --allow-test is
passed.
"""

import argparse
import json
from pathlib import Path

from deid.baselines.common import read_notes
from deid.eval.run import split_of

from .dictation import dictate
from .render import render_scan


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--notes", default="data/generated/notes.jsonl")
    parser.add_argument("--out", default="data/generated/ingest")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--split", choices=("dev", "test"), default="dev")
    parser.add_argument("--allow-test", action="store_true")
    parser.add_argument("--no-audio", action="store_true")
    parser.add_argument("--no-scans", action="store_true")
    parser.add_argument("--voice", default="Microsoft Zira Desktop")
    args = parser.parse_args(argv)
    if args.split == "test" and not args.allow_test:
        parser.error("the test split is for the final reporting run; pass --allow-test")
    notes = [n for n in read_notes(args.notes) if split_of(n["patient_id"]) == args.split][: args.limit]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    speak = None
    if not args.no_audio:
        from .speak import synthesize as speak
    truth = []
    for n in notes:
        script, gold = dictate(n["text"], n["spans"])
        if not args.no_scans:
            render_scan(n["text"], out / "images" / f"{n['note_id']}.png", seed=int(n["note_id"][1:]))
        if speak:
            speak(script, out / "audio" / f"{n['note_id']}.wav", args.voice)
        truth.append({"note_id": n["note_id"], "patient_id": n["patient_id"], "text": n["text"],
                      "script": script, "gold": gold})
    (out / "truth.jsonl").write_text("".join(json.dumps(t, sort_keys=True) + "\n" for t in truth),
                                     encoding="utf-8", newline="\n")
    print(f"{len(truth)} notes -> {out} (scans: {not args.no_scans}, audio: {not args.no_audio})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
