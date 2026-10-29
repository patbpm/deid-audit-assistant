import json
import tempfile
import unittest
from pathlib import Path

from deid.detect.client import Completion
from deid.detect.detector import Cache
from deid.eval.replay import CacheOnly, main, replay


class ReplayTests(unittest.TestCase):
    NOTE = {"note_id": "N1", "patient_id": "P1", "text": "Patient: Kim Lee\nWilson disease since 2019, seen 4/5/25."}
    REPLY = json.dumps({"identifiers": [
        {"text": "Kim Lee", "type": "NAME", "confidence": 0.9}, {"text": "Wilson", "type": "NAME", "confidence": 0.9},
        {"text": "2019", "type": "DATE", "confidence": 0.9}, {"text": "4/5/25", "type": "DATE", "confidence": 0.9}]})

    def fill(self, tmp, version="v1"):
        client = CacheOnly("m", {"max_tokens": 1})
        cache = Cache(Path(tmp), version)
        cache.put(cache.key(client, self.NOTE["text"]), Completion(self.REPLY, {}, 0.0, "stop"))

    def test_saved_replies_are_re_read_with_the_current_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.fill(tmp)
            records, ignored = replay([self.NOTE], tmp, "v1", "m", {"max_tokens": 1})
        texts = [self.NOTE["text"][s["start"]:s["end"]] for s in records[0]["spans"]]
        self.assertEqual(texts, ["Kim Lee", "4/5/25"])
        self.assertEqual(ignored, 2)

    def test_a_missing_reply_is_an_error_not_a_gap(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(LookupError):
                replay([self.NOTE], tmp, "v1", "m", {"max_tokens": 1})

    def test_command_writes_predictions(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.fill(tmp)
            notes, summary, out = Path(tmp) / "n.jsonl", Path(tmp) / "s.json", Path(tmp) / "o" / "p.jsonl"
            notes.write_text(json.dumps(self.NOTE) + "\n", encoding="utf-8")
            summary.write_text(json.dumps({"model": "m", "request_params": {"max_tokens": 1}}), encoding="utf-8")
            main(["--notes", str(notes), "--cache", tmp, "--version", "v1", "--summary", str(summary), "--out", str(out)])
            self.assertEqual(len(out.read_text(encoding="utf-8").splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
