import contextlib
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from deid.detect import client as client_mod
from deid.detect.client import ApiError, Budget, ChatClient, Completion
from deid.detect.detector import Cache, ParseError, detect_note, parse_items
from deid.detect.matching import clean_items, find_spans
from deid.detect.prompt import build_messages
from deid.detect.run import main as run_main
from deid.detect.run import run_detection
from deid.eval.metrics import score_note
from deid.synth import generate


class FakeClient:
    model, params = "fake-model", {"max_tokens": 1}

    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def complete(self, messages):
        self.calls.append(messages)
        content = self.reply(messages) if callable(self.reply) else self.reply
        return Completion(content, {"prompt_tokens": 100, "completion_tokens": 20}, 0.01, "stop")


def item(text, kind="NAME", confidence=0.9):
    return {"text": text, "type": kind, "confidence": confidence}


class MatchingTests(unittest.TestCase):
    def test_every_occurrence_is_marked(self):
        spans, unmatched = find_spans("Kim saw Kim today.", [item("Kim")])
        self.assertEqual([(s["start"], s["end"]) for s in spans], [(0, 3), (8, 11)])
        self.assertEqual(unmatched, [])

    def test_not_inside_a_longer_word(self):
        spans, _ = find_spans("Leeds and Lee", [item("Lee")])
        self.assertEqual([(s["start"], s["end"]) for s in spans], [(10, 13)])

    def test_longer_match_wins_overlap(self):
        spans, _ = find_spans("Kim, Susan saw Kim.", [item("Kim"), item("Kim, Susan")])
        self.assertEqual([(s["start"], s["end"]) for s in spans], [(0, 10), (15, 18)])

    def test_unfound_strings_are_reported_not_guessed(self):
        spans, unmatched = find_spans("No names here.", [item("Smith")])
        self.assertEqual((spans, unmatched), ([], ["Smith"]))

    def test_whitespace_runs_are_tolerated(self):
        spans, _ = find_spans("Susan\n  Kim", [item("Susan Kim")])
        self.assertEqual((spans[0]["start"], spans[0]["end"]), (0, 11))

    def test_first_type_wins_for_a_repeated_string(self):
        spans, _ = find_spans("12345", [item("12345", "ID"), item("12345", "PHONE")])
        self.assertEqual([s["type"] for s in spans], ["ID"])

    def test_clean_items_drops_malformed(self):
        items, dropped = clean_items([item("a"), {"text": "b", "type": "SHOE"}, "x", {"type": "NAME"},
                                      {"text": "c", "type": "name", "confidence": "high"}])
        self.assertEqual([i["text"] for i in items], ["a", "c"])
        self.assertEqual((dropped, items[1]["type"], items[1]["confidence"]), (3, "NAME", None))


class ParseTests(unittest.TestCase):
    def test_plain_fenced_surrounded_and_bare_list(self):
        body = '{"identifiers": [{"text": "A", "type": "NAME"}]}'
        for content in (body, f"```json\n{body}\n```", f"Here you go: {body} done", '[{"text": "A"}]'):
            self.assertEqual(len(parse_items(content)), 1, content)

    def test_junk_raises(self):
        for content in ("", "no json", '{"other": 1}'):
            with self.assertRaises(ParseError):
                parse_items(content)


class DetectNoteTests(unittest.TestCase):
    def test_spans_and_cache(self):
        reply = json.dumps({"identifiers": [item("Kim"), item("Ghost")]})
        fake = FakeClient(reply)
        with tempfile.TemporaryDirectory() as tmp:
            cache = Cache(tmp)
            first = detect_note(fake, "Dr. Kim", cache)
            second = detect_note(fake, "Dr. Kim", cache)
        self.assertEqual(len(fake.calls), 1)
        self.assertFalse(first.cached)
        self.assertTrue(second.cached)
        self.assertEqual(second.usage, {})
        self.assertEqual([(s["start"], s["end"]) for s in first.spans], [(4, 7)])
        self.assertEqual(first.unmatched, ["Ghost"])

    def test_parse_error_is_recorded_not_raised(self):
        result = detect_note(FakeClient("sorry, I cannot"), "text")
        self.assertTrue(result.parse_error)
        self.assertEqual(result.spans, [])

    def test_only_the_note_text_is_sent(self):
        messages = build_messages("hello note")
        self.assertEqual([m["role"] for m in messages], ["system", "user"])
        self.assertIn("hello note", messages[1]["content"])


class RunTests(unittest.TestCase):
    def test_gold_spans_never_reach_the_model(self):
        notes = [{"note_id": "N1", "text": "Dr. Kim", "spans": [{"text": "SENTINEL_GOLD"}]}]

        def reply(messages):
            self.assertNotIn("SENTINEL_GOLD", json.dumps(messages))
            return '{"identifiers": []}'

        run_detection(notes, FakeClient(reply), Cache(None), Budget(1000))

    def test_token_cap_stops_the_run(self):
        notes = [{"note_id": f"N{i}", "text": "Dr. Kim"} for i in range(10)]
        preds, per_note, stopped = run_detection(
            notes, FakeClient('{"identifiers": []}'), Cache(None), Budget(250))
        self.assertTrue(stopped)
        self.assertEqual(len(per_note), 3)  # 120 tokens per call; cap hit after the third
        self.assertEqual(len(preds), 3)

    def test_oracle_model_recovers_every_gold_span(self):
        notes = generate.generate_notes(5, 12)
        by_text = {n["text"]: n for n in notes}

        def oracle(messages):
            text = messages[1]["content"].split("<<<\n", 1)[1].rsplit("\n>>>", 1)[0]
            gold = by_text[text]["spans"]
            return json.dumps({"identifiers": [item(s["text"], s["type"]) for s in gold]})

        preds, per_note, _ = run_detection(notes, FakeClient(oracle), Cache(None), Budget(0))
        per = [score_note(n["spans"], preds[n["note_id"]]) for n in notes]
        recall_hits = sum(p_[t]["gold_hit"] for p_ in per for t in p_)
        gold_total = sum(p_[t]["gold"] for p_ in per for t in p_)
        self.assertEqual(recall_hits, gold_total)
        self.assertFalse(any(n["unmatched"] for n in per_note))

    def test_test_split_needs_explicit_permission(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            run_main(["--split", "test"])

    def test_default_is_a_dry_run_that_calls_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notes.jsonl"
            path.write_text("".join(json.dumps(n) + "\n" for n in generate.generate_notes(3, 4)),
                            encoding="utf-8")
            with mock.patch.object(ChatClient, "complete", side_effect=AssertionError("called")), \
                    mock.patch("urllib.request.urlopen", side_effect=AssertionError("network")):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(run_main(["--notes", str(path), "--limit", "1"]), 0)


class ClientTests(unittest.TestCase):
    def make(self, **kw):
        return ChatClient("http://x/v1/", "m", "SECRETKEY", "max_tokens", sleep=lambda s: None, **kw)

    def test_retries_then_gives_up_without_leaking_the_key(self):
        err = urllib.error.HTTPError("http://x", 429, "Too Many", {}, None)
        err.read = lambda: b"slow down"
        self.addCleanup(err.close)
        with mock.patch("urllib.request.urlopen", side_effect=err) as opened:
            with self.assertRaises(ApiError) as caught:
                self.make(retries=2).complete([{"role": "user", "content": "hi"}])
        self.assertEqual(opened.call_count, 3)
        self.assertNotIn("SECRETKEY", str(caught.exception))

    def test_missing_key_is_a_clear_error(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ApiError) as caught:
                ChatClient.from_env("meta")
        self.assertIn("MODEL_API_KEY", str(caught.exception))

    def test_budget_cost_only_with_prices(self):
        b = Budget(1000)
        b.add({"prompt_tokens": 500_000, "completion_tokens": 100_000})
        self.assertIsNone(b.cost_usd)
        b.price_in, b.price_out = 1.0, 2.0
        self.assertAlmostEqual(b.cost_usd, 0.7)
        self.assertTrue(b.exceeded)


if __name__ == "__main__":
    unittest.main()
