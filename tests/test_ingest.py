import contextlib
import io
import json
import struct
import sys
import tempfile
import unittest
import urllib.error
import wave
from pathlib import Path
from unittest import mock

from deid.detect.client import ApiError, Completion
from deid.detect.detector import Cache
from deid.ingest import audio, dictation, fidelity, run as ingest_run, vision
from deid.ingest.audio import AudioCache, SpeechClient, WavError, check_wav, multipart, transcribe_file
from deid.synth import generate


def write_wav(path, seconds=1.0, rate=16000, channels=1, width=2):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(b"\x00" * int(seconds * rate) * channels * width)
    return path


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def ok(transcript="hello world"):
    return Response(json.dumps({"transcript": transcript}).encode())


class WavTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_accepts_the_documented_format(self):
        info = check_wav(write_wav(self.dir / "a.wav", 2.0, 16000))
        self.assertEqual((info.seconds, info.rate), (2.0, 16000))
        self.assertEqual(check_wav(write_wav(self.dir / "b.wav", 1.0, 24000)).rate, 24000)

    def test_refuses_what_the_endpoint_would_refuse_and_says_why(self):
        for name, kwargs, fragment in [("stereo", dict(channels=2), "2 channel"),
                                       ("rate", dict(rate=44100), "44100 Hz"),
                                       ("8bit", dict(width=1), "8-bit")]:
            with self.assertRaises(WavError, msg=name) as caught:
                check_wav(write_wav(self.dir / f"{name}.wav", **kwargs))
            self.assertIn(fragment, str(caught.exception))
        (self.dir / "junk.wav").write_bytes(b"not a wav at all")
        with self.assertRaises(WavError):
            check_wav(self.dir / "junk.wav")

    def test_duration_and_size_limits(self):
        path = write_wav(self.dir / "c.wav", 2.0)
        with mock.patch.object(audio, "MAX_SECONDS", 1):
            with self.assertRaises(WavError):
                check_wav(path)
        with mock.patch.object(audio, "MAX_BYTES", 100):
            with self.assertRaises(WavError):
                check_wav(path)


class SpeechClientTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.wav = write_wav(Path(self.tmp.name) / "n.wav", 1.0)
        self.client = SpeechClient("https://example.test/v1/", "SECRET-KEY", sleep=lambda s: None)

    def test_multipart_has_a_json_part_and_an_audio_part(self):
        body, header = multipart([("request", None, "application/json", b"{}"), ("audio", "audio.wav", "audio/wav", b"RIFF")])
        boundary = header.split("boundary=")[1]
        self.assertIn(f'name="request"\r\nContent-Type: application/json'.encode(), body)
        self.assertIn(b'name="audio"; filename="audio.wav"', body)
        self.assertTrue(body.endswith(f"--{boundary}--\r\n".encode()))

    def test_request_follows_the_documented_shape(self):
        seen = {}

        def fake(request, timeout=None):
            seen["url"], seen["auth"] = request.full_url, request.get_header("Authorization")
            seen["type"], seen["body"] = request.get_header("Content-type"), request.data
            return ok("Dr. Kim called")

        with mock.patch("urllib.request.urlopen", fake):
            result = transcribe_file(self.client, self.wav)
        self.assertEqual(result.text, "Dr. Kim called")
        self.assertEqual(seen["url"], "https://example.test/v1/asr/transcribe")
        self.assertEqual(seen["auth"], "Bearer SECRET-KEY")
        self.assertTrue(seen["type"].startswith("multipart/form-data; boundary="))
        self.assertIn(b'"model": "muse-voice-transcribe-1.0"', seen["body"])
        self.assertIn(b'"audioEncoding": "WAV"', seen["body"])
        self.assertIn(b'"mode": "PUSH_TO_TALK"', seen["body"])

    def test_retries_on_429_then_succeeds(self):
        calls = []

        def fake(request, timeout=None):
            calls.append(1)
            if len(calls) < 3:
                raise urllib.error.HTTPError(request.full_url, 429, "Too Many", {}, io.BytesIO(b"slow down"))
            return ok()

        with mock.patch("urllib.request.urlopen", fake):
            self.assertEqual(transcribe_file(self.client, self.wav).text, "hello world")
        self.assertEqual(len(calls), 3)

    def test_errors_do_not_leak_the_key_and_name_what_was_missing(self):
        def bad_status(request, timeout=None):
            raise urllib.error.HTTPError(request.full_url, 400, "Bad", {}, io.BytesIO(b"unsupported audio"))

        with mock.patch("urllib.request.urlopen", bad_status):
            with self.assertRaises(ApiError) as caught:
                transcribe_file(self.client, self.wav)
        self.assertNotIn("SECRET-KEY", str(caught.exception))
        self.assertIn("400", str(caught.exception))
        with mock.patch("urllib.request.urlopen", lambda r, timeout=None: Response(b'{"turns": []}')):
            with self.assertRaises(ApiError) as caught:
                transcribe_file(self.client, self.wav)
        self.assertIn("turns", str(caught.exception))

    def test_cache_hit_makes_no_request(self):
        cache = AudioCache(Path(self.tmp.name) / "cache")
        with mock.patch("urllib.request.urlopen", lambda r, timeout=None: ok("first")):
            first = transcribe_file(self.client, self.wav, cache)
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("called")):
            second = transcribe_file(self.client, self.wav, cache)
        self.assertEqual((first.text, second.text, second.cached), ("first", "first", True))

    def test_missing_key_is_a_clear_error(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ApiError):
                SpeechClient.from_env()


class FakeChat:
    model, params = "vision-model", {"max_completion_tokens": 1}

    def __init__(self, reply="HISTORY AND PHYSICAL\nPatient: Kim Reyes"):
        self.reply, self.calls = reply, []

    def complete(self, messages):
        self.calls.append(messages)
        return Completion(self.reply, {"prompt_tokens": 1500, "completion_tokens": 200}, 0.5, "stop")


PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


class VisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.png = Path(self.tmp.name) / "page.png"
        self.png.write_bytes(PNG)

    def test_image_goes_in_the_user_message_as_a_data_url_only(self):
        chat = FakeChat()
        vision.read_scan(chat, self.png)
        system, user = chat.calls[0]
        self.assertEqual(system["role"], "system")
        self.assertIsInstance(system["content"], str)
        kinds = [part["type"] for part in user["content"]]
        self.assertEqual(kinds, ["text", "image_url"])
        self.assertTrue(user["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_text_is_cleaned_and_cached(self):
        chat = FakeChat("```\nPatient: Kim Reyes\nMRN: 1234567\n```")
        cache = Cache(Path(self.tmp.name) / "cache", vision.PROMPT_VERSION)
        first = vision.read_scan(chat, self.png, cache)
        second = vision.read_scan(chat, self.png, cache)
        self.assertEqual(first.text, "Patient: Kim Reyes\nMRN: 1234567")
        self.assertEqual(len(chat.calls), 1)
        self.assertTrue(second.cached)
        self.assertEqual(second.usage, {})

    def test_bad_files_are_refused_before_any_call(self):
        bad = Path(self.tmp.name) / "page.tiff"
        bad.write_bytes(PNG)
        with self.assertRaises(vision.ImageError):
            vision.load_image(bad)
        with mock.patch.object(vision, "MAX_BYTES", 10):
            with self.assertRaises(vision.ImageError):
                vision.load_image(self.png)

    def test_truncated_reply_is_flagged(self):
        class Cut(FakeChat):
            def complete(self, messages):
                return Completion("Patient: Ki", {}, 0.1, "length")
        self.assertTrue(vision.read_scan(Cut(), self.png).truncated)


class DictationTests(unittest.TestCase):
    def test_spoken_forms(self):
        self.assertEqual(dictation.spoken_form("ID", "ACCT1068456722"), "A C C T 1 0 6 8 4 5 6 7 2 2")
        self.assertEqual(dictation.spoken_form("PHONE", "(528) 555-0137"), "5 2 8 5 5 5 0 1 3 7")
        self.assertEqual(dictation.spoken_form("EMAIL", "colleen.larsen@example.org"), "colleen dot larsen at example dot org")
        self.assertEqual(dictation.spoken_form("DATE", "1980-08-17"), "August 17, 1980")
        self.assertEqual(dictation.spoken_form("DATE", "Apr 21"), "April 21")
        self.assertEqual(dictation.spoken_form("NAME", "Larsen-Hughes, Colleen"), "Larsen Hughes, Colleen")

    def test_script_contains_every_spoken_identifier_in_order(self):
        note = generate.generate_notes(5, 3)[0]
        script, gold = dictation.dictate(note["text"], note["spans"])
        self.assertEqual(len(gold), len(note["spans"]))
        cursor = 0
        for g in gold:
            at = script.find(g["spoken"], cursor)
            self.assertGreaterEqual(at, 0, g)
            cursor = at + len(g["spoken"])
        self.assertNotIn("\n", script)


class FidelityTests(unittest.TestCase):
    def test_edit_distance_and_rates(self):
        self.assertEqual(fidelity.edit_distance(list("kitten"), list("sitting")), 3)
        we, wn, ce, cn = fidelity.error_rates("The patient is Kim", "the patient is Tim")
        self.assertEqual((we, wn), (1, 4))
        self.assertGreater(cn, 0)

    def test_presence_by_type_tolerates_spoken_and_spaced_forms(self):
        self.assertTrue(fidelity.present("ID", "6167853", "MRN 6 1 6 7 8 5 3 noted"))
        self.assertTrue(fidelity.present("PHONE", "(528) 555-0137", "call 528 555 0137"))
        self.assertTrue(fidelity.present("EMAIL", "a.b@example.org", "a dot b at example dot org"))
        self.assertTrue(fidelity.present("NAME", "Colleen J Larsen-Hughes", "colleen larsen hughes"))
        self.assertFalse(fidelity.present("NAME", "Colleen Larsen-Hughes", "colleen larsen"))
        self.assertTrue(fidelity.present("NAME", "Colleen Larsen-Hughes", "mrs hughes", any_token=True))
        self.assertTrue(fidelity.present("DATE", "1980-08-17", "born August 17th 1980"))
        self.assertFalse(fidelity.present("DATE", "1980-08-17", "born August 18 1980"))
        self.assertFalse(fidelity.present("ID", "6167853", "6 1 6 7 8 5 4"))

    def test_check_reports_recovery_and_leaks_by_source(self):
        truth = [{"note_id": "N1", "script": "Patient Kim Reyes MRN 1 2 3 4 5 6 7", "text": "Patient: Kim Reyes MRN: 1234567",
                  "gold": [{"type": "NAME", "written": "Kim Reyes", "spoken": "Kim Reyes"},
                           {"type": "ID", "written": "1234567", "spoken": "1 2 3 4 5 6 7"}]}]
        ingested = [{"note_id": "N1", "source": "audio", "text": "patient kim reyes mrn 1 2 3 4 5 6 7"},
                    {"note_id": "N1", "source": "scan", "text": "Patient: Kim Reyes MRN: 1234500"}]
        result = fidelity.check(truth, ingested, {"N1": "Patient: Ada Frost MRN: 1234567"})
        self.assertEqual(result["audio"]["word_error_rate"], 0.0)
        self.assertEqual(result["audio"]["recovery_rate"], 1.0)
        self.assertEqual(result["audio"]["after_cleaning"]["still_present"], 1)       # the ID survived
        self.assertEqual(result["audio"]["after_cleaning"]["by_type"]["NAME"]["still_present"], 0)
        self.assertEqual(result["scan"]["recovered_by_type"]["ID"], {"of": 1, "found": 0})
        self.assertGreater(result["scan"]["char_error_rate"], 0)


class RenderAndSpeakTests(unittest.TestCase):
    def test_scan_rendering_is_deterministic_and_a_real_png(self):
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("Pillow is only needed to build test data")
        from deid.ingest.render import render_scan
        with tempfile.TemporaryDirectory() as tmp:
            a = render_scan("Patient: Kim Reyes\nMRN: 1234567", Path(tmp) / "a.png", seed=3).read_bytes()
            b = render_scan("Patient: Kim Reyes\nMRN: 1234567", Path(tmp) / "b.png", seed=3).read_bytes()
            c = render_scan("Patient: Kim Reyes\nMRN: 1234567", Path(tmp) / "c.png", seed=4).read_bytes()
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertTrue(a.startswith(b"\x89PNG"))

    def test_speech_synthesis_refuses_off_windows(self):
        from deid.ingest import speak
        with mock.patch.object(sys, "platform", "linux"):
            with self.assertRaises(speak.SpeechUnavailable):
                speak.synthesize("hello", "x.wav")


class FakeSpeech:
    def __init__(self, *a, **k):
        self.model, self.mode = "muse-voice-transcribe-1.0", "PUSH_TO_TALK"

    params = {}

    @classmethod
    def from_env(cls, mode="PUSH_TO_TALK"):
        return cls()

    def transcribe(self, path):
        return f"transcript of {Path(path).stem}", 0.2


class IngestRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        (self.dir / "audio").mkdir()
        (self.dir / "images").mkdir()
        write_wav(self.dir / "audio" / "N0001.wav", 2.0)
        write_wav(self.dir / "audio" / "N0002.wav", 3.0)
        write_wav(self.dir / "audio" / "bad.wav", 1.0, rate=44100)
        (self.dir / "images" / "N0001.png").write_bytes(PNG)
        (self.dir / "truth.jsonl").write_text(json.dumps({"note_id": "N0001", "patient_id": "P0001"}) + "\n", encoding="utf-8")

    def argv(self, *extra):
        return ["--audio", str(self.dir / "audio"), "--images", str(self.dir / "images"), "--name", "t",
                "--out-dir", str(self.dir), "--cache-dir", str(self.dir), *extra]

    def test_dry_run_calls_nothing_and_flags_bad_files(self):
        out = io.StringIO()
        with mock.patch("urllib.request.urlopen") as net, mock.patch("deid.ingest.run.SpeechClient") as speech, \
                mock.patch("deid.ingest.run.ChatClient") as chat, contextlib.redirect_stdout(out):
            self.assertEqual(ingest_run.main(self.argv()), 0)
        net.assert_not_called()
        speech.from_env.assert_not_called()
        chat.from_env.assert_not_called()
        text = out.getvalue()
        self.assertIn("DRY RUN", text)
        self.assertIn("would be skipped", text)
        self.assertFalse((self.dir / "t.notes.jsonl").exists())

    def test_live_run_writes_notes_with_sources_and_patient_ids_and_records_errors(self):
        with mock.patch("deid.ingest.run.SpeechClient", FakeSpeech), \
                mock.patch("deid.ingest.run.ChatClient.from_env", return_value=FakeChat("Patient: page text")), \
                contextlib.redirect_stdout(io.StringIO()):
            ingest_run.main(self.argv("--live", "--truth", str(self.dir / "truth.jsonl")))
        notes = [json.loads(line) for line in (self.dir / "t.notes.jsonl").read_text(encoding="utf-8").splitlines()]
        by = {(n["note_id"], n["source"]): n for n in notes}
        self.assertEqual(by[("N0001", "audio")]["text"], "transcript of N0001")
        self.assertEqual(by[("N0001", "scan")]["text"], "Patient: page text")
        self.assertEqual(by[("N0001", "audio")]["patient_id"], "P0001")
        self.assertEqual(by[("N0002", "audio")]["patient_id"], "N0002")      # no truth entry: its own patient
        log = json.loads((self.dir / "t.log.json").read_text(encoding="utf-8"))
        self.assertEqual([e["file"] for e in log["summary"]["errors"]], ["bad.wav"])
        self.assertEqual(log["summary"]["tokens_in"], 1500)

    def test_audio_seconds_cap_stops_the_run(self):
        with mock.patch("deid.ingest.run.SpeechClient", FakeSpeech), contextlib.redirect_stdout(io.StringIO()):
            ingest_run.main(["--audio", str(self.dir / "audio"), "--name", "cap", "--out-dir", str(self.dir),
                             "--cache-dir", str(self.dir), "--live", "--max-audio-seconds", "4"])
        log = json.loads((self.dir / "cap.log.json").read_text(encoding="utf-8"))
        self.assertTrue(1 <= log["summary"]["audio_files"] <= 2)   # N0002 (3 s) would push the total past 4 s
        self.assertTrue(log["summary"]["stopped"])

    def test_nothing_to_do_is_a_usage_error(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            ingest_run.main([])


class UnlabeledAgentTests(unittest.TestCase):
    def test_agent_runs_on_notes_without_truth_and_scores_nothing(self):
        from deid.agent.run import main as agent_main

        class Model:
            model, params = "scripted", {"max_tokens": 1}

            def complete(self, messages):
                system = messages[0]["content"]
                if "find personal identifiers" in system:
                    body = {"identifiers": [{"text": "Kim Reyes", "type": "NAME", "confidence": 0.95}]}
                elif "double-check" in system:
                    body = {"verdicts": []}
                else:
                    body = {"risk": "low", "clues": []}
                return Completion(json.dumps(body), {"prompt_tokens": 10, "completion_tokens": 5}, 0.0, "stop")

        with tempfile.TemporaryDirectory() as tmp:
            notes = Path(tmp) / "notes.jsonl"
            notes.write_text(json.dumps({"note_id": "X1", "text": "Patient Kim Reyes seen today.", "source": "audio"}) + "\n",
                             encoding="utf-8")
            argv = ["--live", "--unlabeled", "--notes", str(notes), "--name", "u", "--out-dir", tmp,
                    "--cache-dir", tmp, "--results-dir", str(Path(tmp) / "res")]
            out = io.StringIO()
            with mock.patch("deid.agent.run.ChatClient.from_env", return_value=Model()), contextlib.redirect_stdout(out):
                self.assertEqual(agent_main(argv), 0)
            cleaned = json.loads((Path(tmp) / "u.notes.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertNotIn("Kim Reyes", cleaned["text"])
            self.assertIn("nothing was scored", out.getvalue())
            self.assertFalse(list((Path(tmp) / "res").glob("u-detector*")))


if __name__ == "__main__":
    unittest.main()
