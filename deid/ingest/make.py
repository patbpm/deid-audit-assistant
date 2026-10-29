"""Build a small synthetic test set of dictated and scanned notes from dev notes.

    python -m deid.ingest.make --limit 5 --out data/generated/ingest

For each note: images/<note_id>.png (the written text drawn on a page with mild
scan damage), audio/<note_id>.wav (a dictation script spoken by a Windows voice),
and one line in truth.jsonl with the written text, the script and every
identifier in written and spoken form. Everything is synthetic and made offline
(the folder is git-ignored). Only dev-split notes are used unless --allow-test is
passed.

With --harder it also writes images_noisy/<id>.jpg (more tilt, blur, speckle, a shadow,
lower resolution, heavy JPEG compression), audio_noisy/<id>.wav (background noise at
--snr dB) and audio_long/<first>-<last>-long.wav (the first four notes of the first
patient dictated back to back, a few minutes long), with a matching truth line.
"""

import argparse
import json
from pathlib import Path

from deid.baselines.common import read_notes
from deid.eval.run import split_of

from .degrade import add_noise_wav, degrade_image, join_wavs
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
    parser.add_argument("--harder", action="store_true", help="also write noisy audio, rough scans and one long recording")
    parser.add_argument("--snr", type=float, default=12.0, help="signal-to-noise ratio of the noisy audio, in dB")
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
    if args.harder:
        for t in truth[:]:
            n = t["note_id"]
            if not args.no_scans:
                degrade_image(out / "images" / f"{n}.png", out / "images_noisy" / f"{n}.jpg", seed=int(n[1:]))
            if speak:
                add_noise_wav(out / "audio" / f"{n}.wav", out / "audio_noisy" / f"{n}.wav", args.snr, seed=int(n[1:]))
        first_patient = [t for t in truth if t["patient_id"] == truth[0]["patient_id"]]
        if speak and len(first_patient) > 1:
            ids = [t["note_id"] for t in first_patient]
            long_id = f"{ids[0]}-{ids[-1]}-long"
            join_wavs([out / "audio" / f"{i}.wav" for i in ids], out / "audio_long" / f"{long_id}.wav")
            truth.append({"note_id": long_id, "patient_id": first_patient[0]["patient_id"],
                          "text": "\n\n".join(t["text"] for t in first_patient),
                          "script": " ".join(t["script"] for t in first_patient),
                          "gold": [g for t in first_patient for g in t["gold"]]})
    (out / "truth.jsonl").write_text("".join(json.dumps(t, sort_keys=True) + "\n" for t in truth),
                                     encoding="utf-8", newline="\n")
    print(f"{len(truth)} notes -> {out} (scans: {not args.no_scans}, audio: {not args.no_audio})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
