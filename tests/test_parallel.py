"""Running notes at once must give the same results, in the same order, as running them one by one."""

import contextlib
import io
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from deid.agent.parallel import run_ordered
from deid.agent.pipeline import detect_and_verify, prefetch_redteam, review_and_clean
from deid.agent.run import main as run_main
from deid.detect.client import Budget, ChatClient, Completion, LargerLimitRetry
from deid.detect.detector import Cache
from deid.synth import generate
from tests.test_agent import ScriptedModel


class RunOrderedTests(unittest.TestCase):
    def collect(self, workers, items, work=lambda x: x * 2, stop=lambda: False):
        got = []
        stopped = run_ordered(work, items, workers, stop, got.append)
        return got, stopped

    def test_results_come_back_in_input_order_whatever_the_speed(self):
        def slow_first(x):
            time.sleep(0.05 if x % 3 == 0 else 0.0)
            return x * 2
        sequential, _ = self.collect(1, list(range(20)))
        parallel, stopped = self.collect(4, list(range(20)), slow_first)
        self.assertEqual(parallel, sequential)
        self.assertFalse(stopped)

    def test_no_more_than_the_requested_number_run_at_once(self):
        live, peak, lock = [0], [0], threading.Lock()

        def work(x):
            with lock:
                live[0] += 1
                peak[0] = max(peak[0], live[0])
            time.sleep(0.02)
            with lock:
                live[0] -= 1
            return x
        self.collect(3, list(range(15)), work)
        self.assertLessEqual(peak[0], 3)
        self.assertGreater(peak[0], 1)

    def test_stopping_hands_out_nothing_more_and_reports_it(self):
        seen = []
        got = []
        stopped = run_ordered(lambda x: x, list(range(100)), 4, lambda: len(got) >= 10, lambda r: (got.append(r), seen.append(r)))
        self.assertTrue(stopped)
        self.assertEqual(got, list(range(len(got))))             # still in order, no gaps
        self.assertGreaterEqual(len(got), 10)
        self.assertLessEqual(len(got), 10 + 2 * 4)              # only what was already in flight is added
        got.clear()
        self.assertTrue(run_ordered(lambda x: x, list(range(5)), 1, lambda: len(got) >= 2, got.append))
        self.assertEqual(got, [0, 1])

    def test_a_stop_after_the_last_item_is_not_a_stop(self):
        got = []
        self.assertFalse(run_ordered(lambda x: x, [1, 2, 3], 4, lambda: len(got) >= 3, got.append))
        self.assertEqual(got, [1, 2, 3])

    def test_an_error_in_a_worker_reaches_the_caller(self):
        def work(x):
            if x == 3:
                raise ValueError("boom")
            return x
        with self.assertRaises(ValueError):
            self.collect(4, list(range(10)), work)

    def test_empty_input(self):
        self.assertEqual(self.collect(4, []), ([], False))


class PipelineEquivalenceTests(unittest.TestCase):
    def setUp(self):
        self.notes = generate.generate_notes(5, 8)

    def stage1(self, workers, budget=None):
        model = ScriptedModel(self.notes)
        budget = budget or Budget(0)
        batch, stopped = detect_and_verify(self.notes, model, Cache(None), Cache(None, "vf1"), budget, 0.8, workers=workers)
        return model, budget, batch, stopped

    def test_detection_and_verification_are_the_same_with_four_workers(self):
        m1, b1, one, s1 = self.stage1(1)
        m4, b4, four, s4 = self.stage1(4)
        self.assertEqual([(d.note["note_id"], d.spans, d.verdicts, d.unmatched, d.failures, d.flags) for d in one],
                         [(d.note["note_id"], d.spans, d.verdicts, d.unmatched, d.failures, d.flags) for d in four])
        self.assertEqual((b1.tokens_in, b1.tokens_out), (b4.tokens_in, b4.tokens_out))
        self.assertEqual(sorted(k for k, _ in m1.calls), sorted(k for k, _ in m4.calls))
        self.assertEqual((s1, s4), (False, False))

    def test_the_token_cap_still_stops_stage_one_within_the_notes_in_flight(self):
        _, _, batch, stopped = self.stage1(4, Budget(1000))
        self.assertTrue(stopped)
        self.assertLess(len(batch), len(self.notes))
        # one detection call costs 120 tokens and one verification 120 here: at most the notes in flight go past
        self.assertLessEqual(len(batch), 1000 // 240 + 1 + 2 * 4)

    def finish(self, workers, tmp):
        model, budget, batch, _ = self.stage1(workers)
        cache = Cache(Path(tmp), "rt1")
        stopped_early = False
        if workers > 1:
            stopped_early = prefetch_redteam(batch, model, cache, budget, 0, workers)
        outcomes, stopped, replacer = review_and_clean(batch, model, cache, budget, 0, 0.8, 2)
        return model, budget, outcomes, replacer, stopped_early or stopped

    def test_prefetching_the_first_red_team_look_changes_nothing_but_the_waiting(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            m1, b1, one, r1, s1 = self.finish(1, a)
            m4, b4, four, r4, s4 = self.finish(4, b)
        self.assertEqual([o.cleaned for o in one], [o.cleaned for o in four])
        self.assertEqual([o.audit for o in one], [o.audit for o in four])
        self.assertEqual([(o.risk_before, o.risk_after) for o in one], [(o.risk_before, o.risk_after) for o in four])
        self.assertEqual(r1.key_tables(), r4.key_tables())                       # the same stand-in values
        self.assertEqual((b1.tokens_in, b1.tokens_out), (b4.tokens_in, b4.tokens_out))
        count = lambda m: sorted(k for k, _ in m.calls)
        self.assertEqual(count(m1), count(m4))                                   # no call was made twice or dropped
        self.assertEqual((s1, s4), (False, False))

    def test_notes_that_could_not_be_detected_are_not_sent_to_the_reviewer(self):
        model, budget, batch, _ = self.stage1(2)
        batch[0].failures.append("the detection reply could not be read")
        with tempfile.TemporaryDirectory() as tmp:
            before = sum(1 for k, _ in model.calls if k == "redteam")
            prefetch_redteam(batch, model, Cache(Path(tmp), "rt1"), budget, 0, 2)
            asked = sum(1 for k, _ in model.calls if k == "redteam") - before
        self.assertEqual(asked, len(batch) - 1)


class CommandTests(unittest.TestCase):
    def run_command(self, workers):
        notes = generate.generate_notes(5, 4)[:3]
        model = ScriptedModel(notes)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notes.jsonl"
            path.write_text("".join(json.dumps(n) + "\n" for n in notes), encoding="utf-8")
            argv = ["--live", "--notes", str(path), "--limit", "3", "--name", "t", "--out-dir", tmp, "--cache-dir", tmp,
                    "--results-dir", str(Path(tmp) / "res"), "--workers", str(workers)]
            with mock.patch("deid.agent.run.ChatClient.from_env", return_value=model), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run_main(argv), 0)
            files = {n: (Path(tmp) / f"t.{n}").read_text(encoding="utf-8")
                     for n in ("notes.jsonl", "detector.jsonl", "final.jsonl", "key.json", "audit.json")}
            summary = json.loads((Path(tmp) / "res" / "t.json").read_text(encoding="utf-8"))
        return files, summary

    def test_the_command_writes_identical_files_with_one_worker_or_three(self):
        one, s1 = self.run_command(1)
        three, s3 = self.run_command(3)
        self.assertEqual(one, three)
        for key in ("tokens_in", "tokens_out", "risk_before_feedback", "risk_after_feedback", "notes_finished",
                    "spans_added_by_feedback", "redteam_calls"):
            self.assertEqual(s1[key], s3[key], key)
        self.assertEqual((s1["workers"], s3["workers"]), (1, 3))


class ThreadSafeRetryTests(unittest.TestCase):
    def test_a_larger_limit_is_for_one_call_only_and_nothing_shared_changes(self):
        sent = []

        class Response:
            def __init__(self, finish):
                self.finish = finish

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, *a):
                return json.dumps({"choices": [{"message": {"content": "x"}, "finish_reason": self.finish}],
                                   "usage": {"prompt_tokens": 1, "completion_tokens": 1}}).encode()

        replies = [Response("length"), Response("stop")]

        def fake_urlopen(request, timeout=None):
            sent.append(json.loads(request.data)["max_completion_tokens"])
            return replies.pop(0)

        inner = ChatClient("https://x/v1", "m", "k", "max_completion_tokens", 100)
        with mock.patch("urllib.request.urlopen", fake_urlopen), mock.patch("json.load", lambda r: json.loads(r.read())):
            result = LargerLimitRetry(inner, 900).complete([{"role": "user", "content": "hi"}])
        self.assertEqual(sent, [100, 900])
        self.assertEqual(inner.max_output_tokens, 100)
        self.assertEqual(inner.params, {"max_completion_tokens": 100})
        self.assertEqual(result.finish_reason, "stop")


if __name__ == "__main__":
    unittest.main()
