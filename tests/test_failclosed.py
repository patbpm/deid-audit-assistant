"""A note the agent could not clean must never come out looking cleaned."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from deid.agent.pipeline import detect_and_verify, review_and_clean
from deid.agent.run import main as agent_main
from deid.audit.build import build_note_audit, summarize
from deid.audit.report import render
from deid.detect.client import Budget, Completion, LargerLimitRetry
from deid.detect.detector import Cache, detect_note
from deid.ingest import fidelity
from deid.review.decisions import Store, empty_note, record


def completion(content, finish="stop", usage=(10, 5)):
    return Completion(content, {"prompt_tokens": usage[0], "completion_tokens": usage[1]}, 0.1, finish)


class Inner:
    model = "m"

    def __init__(self, replies):
        self.replies, self.limits, self.max_output_tokens = list(replies), [], 100

    @property
    def params(self):
        return {"max_tokens": self.max_output_tokens}

    def complete(self, messages, max_output_tokens=None):
        self.limits.append(max_output_tokens or self.max_output_tokens)
        return self.replies.pop(0)


class RetryTests(unittest.TestCase):
    def test_a_reply_cut_off_at_the_limit_is_asked_again_with_a_larger_one(self):
        inner = Inner([completion("", "length", (10, 100)), completion('{"identifiers": []}', "stop", (10, 300))])
        client = LargerLimitRetry(inner, 1000)
        result = client.complete([])
        self.assertEqual(inner.limits, [100, 1000])
        self.assertEqual(inner.max_output_tokens, 100)              # restored
        self.assertEqual(client.params, {"max_tokens": 100})         # cache keys stay on the normal limit
        self.assertEqual(result.finish_reason, "stop")
        self.assertEqual(result.usage, {"prompt_tokens": 20, "completion_tokens": 400})

    def test_no_retry_when_the_reply_is_complete_or_retrying_is_off(self):
        inner = Inner([completion("ok")])
        LargerLimitRetry(inner, 1000).complete([])
        self.assertEqual(inner.limits, [100])
        for limit in (0, 100, 50):
            inner = Inner([completion("", "length")])
            LargerLimitRetry(inner, limit).complete([])
            self.assertEqual(len(inner.limits), 1, limit)

    def test_a_second_cut_off_is_still_reported_as_cut_off(self):
        inner = Inner([completion("", "length"), completion("partial", "length")])
        self.assertEqual(LargerLimitRetry(inner, 1000).complete([]).finish_reason, "length")


class CacheTests(unittest.TestCase):
    def test_incomplete_replies_are_neither_kept_nor_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Cache(tmp)
            cache.put("a", completion("x", "length"))
            self.assertEqual(list(Path(tmp).glob("*.json")), [])
            (Path(tmp) / "b.json").write_text(json.dumps(
                {"content": "x", "usage": {}, "latency_s": 0, "finish_reason": "length"}), encoding="utf-8")
            self.assertIsNone(cache.get("b"))
            cache.put("c", completion("fine"))
            self.assertEqual(cache.get("c").content, "fine")


NOTE = {"note_id": "N1", "patient_id": "P1", "text": "Patient: Kim Reyes seen on 4/5/25. Call 555-0100."}


class Flaky:
    model, params = "m", {"max_tokens": 1}

    def __init__(self, detect_reply):
        self.detect_reply, self.calls = detect_reply, []

    def complete(self, messages):
        system = messages[0]["content"]
        kind = "detect" if "find personal identifiers" in system else "verify" if "double-check" in system else "redteam"
        self.calls.append(kind)
        if kind == "detect":
            return self.detect_reply
        if kind == "verify":
            return completion('{"verdicts": []}')
        return completion('{"risk": "low", "clues": []}')


GOOD = completion(json.dumps({"identifiers": [{"text": "Kim Reyes", "type": "NAME", "confidence": 0.95}]}))


class PipelineFailClosedTests(unittest.TestCase):
    def run_pipeline(self, detect_reply):
        client = Flaky(detect_reply)
        batch, _ = detect_and_verify([NOTE], client, Cache(None), Cache(None, "vf1"), Budget(0), 0.8)
        outcomes, _, _ = review_and_clean(batch, client, Cache(None, "rt1"), Budget(0), 0, 0.8, 2)
        return client, batch, outcomes

    def test_an_unreadable_detection_reply_leaves_the_note_not_cleaned(self):
        client, batch, outcomes = self.run_pipeline(completion("sorry, I cannot do that"))
        o = outcomes[0]
        self.assertIsNone(o.cleaned)
        self.assertTrue(batch[0].failures)
        self.assertEqual(o.audit["failed"], batch[0].failures)
        self.assertTrue(o.audit["review"][0]["reasons"][0].startswith("NOT CLEANED"))
        self.assertEqual(client.calls, ["detect"])          # no point reviewing a note that was never cleaned

    def test_a_cut_off_detection_reply_counts_even_if_the_json_looks_complete(self):
        reply = completion(GOOD.content, "length")
        _, batch, outcomes = self.run_pipeline(reply)
        self.assertIsNone(outcomes[0].cleaned)
        self.assertIn("cut off", batch[0].failures[0])

    def test_a_good_reply_is_cleaned_as_before(self):
        _, batch, outcomes = self.run_pipeline(GOOD)
        self.assertEqual(batch[0].failures, [])
        self.assertNotIn("Kim Reyes", outcomes[0].cleaned)
        self.assertEqual(outcomes[0].audit["failed"], [])

    def test_the_audit_page_and_summary_show_it(self):
        _, _, outcomes = self.run_pipeline(completion("nonsense"))
        audits = [o.audit for o in outcomes]
        self.assertEqual(summarize(audits)["notes_not_cleaned"], 1)
        self.assertIn("NOT CLEANED", render(audits, summarize(audits)))


class AgentRunTests(unittest.TestCase):
    def test_cleaned_file_leaves_out_a_failed_note_and_lists_it(self):
        good = {"note_id": "G1", "patient_id": "P1", "text": "Patient: Kim Reyes seen today."}
        bad = {"note_id": "B1", "patient_id": "P2", "text": "Patient: Ada Frost seen today."}

        class Model(Flaky):
            def complete(self, messages):
                user = messages[1]["content"]
                if "find personal identifiers" in messages[0]["content"] and "Ada Frost" in user:
                    return completion("", "length")
                self.detect_reply = GOOD
                return super().complete(messages)

        with tempfile.TemporaryDirectory() as tmp:
            notes = Path(tmp) / "notes.jsonl"
            notes.write_text("".join(json.dumps(n) + "\n" for n in (good, bad)), encoding="utf-8")
            argv = ["--live", "--unlabeled", "--notes", str(notes), "--name", "f", "--out-dir", tmp, "--cache-dir", tmp,
                    "--results-dir", str(Path(tmp) / "res"), "--retry-output-tokens", "0"]
            out = io.StringIO()
            with mock.patch("deid.agent.run.ChatClient.from_env", return_value=Model(GOOD)), contextlib.redirect_stdout(out):
                agent_main(argv)
            cleaned = [json.loads(l) for l in (Path(tmp) / "f.notes.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual([c["note_id"] for c in cleaned], ["G1"])
            failed = json.loads((Path(tmp) / "f.failed.json").read_text(encoding="utf-8"))
            self.assertEqual([f["note_id"] for f in failed], ["B1"])
            summary = json.loads((Path(tmp) / "res" / "f.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["notes_not_cleaned"], 1)
            self.assertIn("NOT CLEANED", out.getvalue())


class ReviewFailClosedTests(unittest.TestCase):
    def audit_note(self):
        return build_note_audit("N1", NOTE["text"], [], [], "m", failures=["the detection reply could not be read"])

    def test_the_not_cleaned_item_cannot_be_dismissed(self):
        note = self.audit_note()
        self.assertEqual(note["review"][0]["kind"], "failed")
        with self.assertRaises(ValueError):
            record(note, empty_note(), {"op": "item", "index": 0, "decision": "dismiss"})

    def test_export_withholds_a_note_that_was_not_cleaned(self):
        ok = build_note_audit("N2", "Patient: Ada Frost.", [], [], "m")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.audit.json"
            path.write_text(json.dumps({"summary": {}, "notes": [self.audit_note(), ok]}), encoding="utf-8")
            summary = Store(path).export()
            self.assertEqual(summary["notes_withheld_not_cleaned"], ["N1"])
            self.assertEqual(summary["notes_exported"], 1)
            lines = (Path(tmp) / "x.reviewed.notes.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual([json.loads(l)["note_id"] for l in lines], ["N2"])


class FidelityDateTests(unittest.TestCase):
    def test_a_date_kept_exactly_as_written_is_recognized(self):
        self.assertTrue(fidelity.present("DATE", "4/17/2025", "Date: 4/17/2025 and more"))
        self.assertTrue(fidelity.present("DATE", "04-13-25", "seen 04-13-25"))
        self.assertFalse(fidelity.present("DATE", "4/17/2025", "Date: 4/18/2025"))


if __name__ == "__main__":
    unittest.main()
