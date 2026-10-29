"""Turn dictated audio and scanned pages into note text for the de-identification agent.

    python -m deid.ingest.run --audio data/generated/ingest/audio --images data/generated/ingest/images
    python -m deid.ingest.run --audio ... --images ... --live --name ingest-first5

Dry run unless --live: lists the files, checks each WAV against the endpoint's
limits, and sizes the run, calling nothing. Live runs transcribe each WAV with
Muse Voice Transcribe and read each image with the vision model, within a token
cap (images) and an audio-seconds cap. A file that fails is recorded and skipped.
Cached results cost nothing. Only synthetic files belong here: both services are
hosted.

Writes runs/<name>.notes.jsonl (one note per file: note_id from the file name,
patient_id from --truth if given, text, source, source_file) and
runs/<name>.log.json. Then clean them with:

    python -m deid.agent.run --unlabeled --notes runs/<name>.notes.jsonl --live
"""

import argparse
import json
import statistics
from pathlib import Path

from deid.detect.client import ApiError, Budget, ChatClient
from deid.detect.detector import Cache

from . import vision
from .audio import AudioCache, SpeechClient, WavError, check_wav, transcribe_file

IMAGE_TOKENS_ESTIMATE = 1500  # about 1,300-1,500 input tokens for a 1280 px image, per Meta's docs


def find_files(folder, suffixes):
    if not folder:
        return []
    return sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in suffixes)


def patient_map(truth_path):
    if not truth_path:
        return {}
    rows = [json.loads(line) for line in Path(truth_path).read_text(encoding="utf-8").splitlines() if line.strip()]
    return {r["note_id"]: r["patient_id"] for r in rows}


def dry_run(audio, images, args):
    print("DRY RUN (nothing sent).")
    seconds = 0.0
    for p in audio:
        try:
            info = check_wav(p)
            seconds += info.seconds
            print(f"  audio {p.name}: {info.seconds:.0f} s, {info.rate} Hz, {info.size:,} bytes: ok")
        except WavError as err:
            print(f"  audio {err}: would be skipped")
    for p in images:
        try:
            data, mime = vision.load_image(p)
            print(f"  image {p.name}: {len(data):,} bytes, {mime}: ok")
        except vision.ImageError as err:
            print(f"  image {err}: would be skipped")
    print(f"{len(audio)} audio files, {seconds:.0f} s in total (cap {args.max_audio_seconds} s); "
          f"{len(images)} images, about {IMAGE_TOKENS_ESTIMATE} input tokens each plus output and reasoning "
          f"tokens (cap {args.max_total_tokens} tokens).")
    if args.audio_price_per_hour is not None:
        print(f"Audio at {args.audio_price_per_hour} USD per hour: about {seconds / 3600 * args.audio_price_per_hour:.3f} USD.")
    else:
        print("Audio cost not shown: pass --audio-price-per-hour (see docs/PRICES.md).")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--audio", help="folder of WAV files (mono, 16-bit, 16 or 24 kHz, at most 10 minutes)")
    parser.add_argument("--images", help="folder of page images (png, jpg, gif, webp)")
    parser.add_argument("--truth", help="truth.jsonl from deid.ingest.make, to carry patient ids across")
    parser.add_argument("--name", default="ingest")
    parser.add_argument("--live", action="store_true", help="make real API calls")
    parser.add_argument("--limit", type=int, default=5, help="files per kind (0 = all)")
    parser.add_argument("--mode", default="PUSH_TO_TALK", choices=("PUSH_TO_TALK", "ENDPOINTING", "DIARIZATION"))
    parser.add_argument("--max-total-tokens", type=int, default=100_000)
    parser.add_argument("--max-audio-seconds", type=int, default=600)
    parser.add_argument("--max-output-tokens", type=int, default=4096)
    parser.add_argument("--audio-price-per-hour", type=float)
    parser.add_argument("--price-in", type=float)
    parser.add_argument("--price-out", type=float)
    parser.add_argument("--cache-dir", default="runs")
    parser.add_argument("--out-dir", default="runs")
    args = parser.parse_args(argv)
    if not (args.audio or args.images):
        parser.error("give --audio and/or --images")
    audio = find_files(args.audio, {".wav"})
    images = find_files(args.images, set(vision.MIME))
    if args.limit:
        audio, images = audio[: args.limit], images[: args.limit]
    if not args.live:
        dry_run(audio, images, args)
        return 0

    patients = patient_map(args.truth)
    root = Path(args.cache_dir)
    notes, log = [], []
    seconds_used, budget = 0.0, Budget(args.max_total_tokens, args.price_in, args.price_out)
    stopped, chat = [], None
    if audio:
        speech = SpeechClient.from_env(args.mode)
        cache = AudioCache(root / "cache-audio")
        for p in audio:
            try:
                info = check_wav(p)
                if seconds_used + info.seconds > args.max_audio_seconds:
                    stopped.append(f"audio cap reached before {p.name}")
                    break
                result = transcribe_file(speech, p, cache)
            except (WavError, ApiError) as err:
                log.append({"source": "audio", "file": p.name, "error": str(err)})
                continue
            seconds_used += 0 if result.cached else result.seconds
            notes.append({"note_id": p.stem, "patient_id": patients.get(p.stem, p.stem), "text": result.text,
                          "source": "audio", "source_file": p.name})
            log.append({"source": "audio", "file": p.name, "seconds": result.seconds,
                        "latency_s": result.latency_s, "cached": result.cached})
    if images:
        chat = ChatClient.from_env("meta", args.max_output_tokens)
        cache = Cache(root / "cache-scan", vision.PROMPT_VERSION)
        for p in images:
            if budget.exceeded:
                stopped.append(f"token cap reached before {p.name}")
                break
            try:
                scan = vision.read_scan(chat, p, cache)
            except (vision.ImageError, ApiError) as err:
                log.append({"source": "scan", "file": p.name, "error": str(err)})
                continue
            budget.add(scan.usage)
            notes.append({"note_id": p.stem, "patient_id": patients.get(p.stem, p.stem), "text": scan.text,
                          "source": "scan", "source_file": p.name})
            log.append({"source": "scan", "file": p.name, "latency_s": scan.latency_s, "cached": scan.cached,
                        "truncated": scan.truncated, "usage": scan.usage})

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{args.name}.notes.jsonl").write_text("".join(json.dumps(n, sort_keys=True) + "\n" for n in notes),
                                                  encoding="utf-8", newline="\n")
    latencies = sorted(r["latency_s"] for r in log if "latency_s" in r and not r.get("cached"))
    summary = {
        "name": args.name, "audio_files": sum(r["source"] == "audio" for r in log),
        "scan_files": sum(r["source"] == "scan" for r in log), "notes_written": len(notes),
        "errors": [r for r in log if "error" in r], "stopped": stopped,
        "audio_seconds_sent": seconds_used, "audio_model": "muse-voice-transcribe-1.0", "audio_mode": args.mode,
        "vision_model": chat.model if chat else None, "vision_prompt": vision.PROMPT_VERSION,
        "tokens_in": budget.tokens_in, "tokens_out": budget.tokens_out, "cost_usd_tokens": budget.cost_usd,
        "cost_usd_audio": None if args.audio_price_per_hour is None else seconds_used / 3600 * args.audio_price_per_hour,
        "latency_s_median": statistics.median(latencies) if latencies else None,
        "truncated_scans": sum(bool(r.get("truncated")) for r in log),
    }
    (out / f"{args.name}.log.json").write_text(json.dumps({"summary": summary, "files": log}, indent=2, sort_keys=True) + "\n",
                                               encoding="utf-8", newline="\n")
    print(json.dumps(summary, indent=2, sort_keys=True))
    if stopped:
        print("STOPPED EARLY: a cap was reached. Raise it only with the project owner's approval.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
