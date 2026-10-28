import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from deid.detect.client import Budget, Completion
from deid.detect.detector import Cache, ParseError
from deid.redteam import probes as probes_mod
from deid.redteam.assess import (assess_note, clean_clues, final_risk, locate, masked_view,
                                 parse_assessment)
from deid.redteam.loop import harden
from deid.redteam.probes import CLUES, make_probe
from deid.redteam.prompt import PROMPT_VERSION, build_messages
from deid.redteam.run import build_probes, main as run_main, run_probes
from deid.redteam.score import score, wilson
from deid.replace.engine import Replacer
from deid.synth import generate


class FakeClient:
    model, params = "fake-model", {"max_tokens": 1}

    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def complete(self, messages):
        self.calls.append(messages)
        content = self.reply(messages) if callable(self.reply) else self.reply
        return Completion(content, {"prompt_tokens": 100, "completion_tokens": 20}, 0.01, "stop")


def reply(risk, *clues):
    return json.dumps({"risk": risk, "clues": [
        {"text": t, "category": c, "type": k, "why": "test"} for t, c, k in clues]})


def note_text(messages):
    return messages[1]["content"].split("<<<\n", 1)[1].rsplit("\n>>>", 1)[0]


TEXT = "Patient: Kim Reyes seen on 2025-03-02. Lives on a tiny island. Call 555-0100 today."
NAME_SPAN = {"start": 9, "end": 18, "type": "NAME"}
DATE_SPAN = {"start": 27, "end": 37, "type": "DATE"}


class ViewTests(unittest.TestCase):
    def setUp(self):
        self.replacer = Replacer(0).fit([{"text": TEXT, "spans": [NAME_SPAN, DATE_SPAN]}])
        _, self.changes = self.replacer.apply({"text": TEXT, "spans": [NAME_SPAN, DATE_SPAN]})
        self.view = masked_view(TEXT, self.changes)

    def test_changed_spans_are_shown_as_tags(self):
        self.assertEqual(self.view.text, "Patient: [NAME] seen on [DATE]. Lives on a tiny island. Call 555-0100 today.")

    def test_masked_text_never_holds_a_surrogate_or_an_original(self):
        for c in self.changes:
            self.assertNotIn(c["original"], self.view.text)
            self.assertNotIn(c["replacement"], self.view.text)

    def test_plain_text_maps_back_to_original_offsets(self):
        a, b = locate(self.view.text, "tiny island")[0]
        start, end = self.view.to_original(a, b)
        self.assertEqual(TEXT[start:end], "tiny island")
        a, b = locate(self.view.text, "555-0100")[0]
        start, end = self.view.to_original(a, b)
        self.assertEqual(TEXT[start:end], "555-0100")

    def test_a_range_inside_one_tag_has_no_original(self):
        a, b = locate(self.view.text, "NAME")[0]
        self.assertIsNone(self.view.to_original(a, b))

    def test_a_range_touching_a_tag_covers_the_whole_tag(self):
        a, _ = locate(self.view.text, "[NAME] seen")[0]
        start, end = self.view.to_original(a, a + len("[NAME] seen"))
        self.assertEqual(TEXT[start:end], "Kim Reyes seen")


class ParseTests(unittest.TestCase):
    def test_fenced_and_surrounded_json(self):
        self.assertEqual(parse_assessment('```json\n{"risk": "High", "clues": []}\n```'), ("high", []))
        self.assertEqual(parse_assessment('Sure! {"risk": "low", "clues": []} Done.'), ("low", []))

    def test_unknown_risk_word_is_none_and_garbage_raises(self):
        self.assertEqual(parse_assessment('{"risk": "severe", "clues": []}')[0], None)
        with self.assertRaises(ParseError):
            parse_assessment("I cannot help with that.")

    def test_clues_are_cleaned(self):
        view = masked_view(TEXT, [])
        raw = [{"text": "tiny island", "category": "small_place", "why": "x"},
               {"text": "[NAME]", "category": "LEFTOVER", "type": "NAME"},
               {"text": "not in the note", "category": "WEIRD", "type": "PERSON"},
               {"text": "   "}, "junk"]
        clues, dropped = clean_clues(raw, view)
        self.assertEqual(dropped, 3)
        self.assertEqual([c["category"] for c in clues], ["SMALL_PLACE", "OTHER"])
        self.assertEqual(clues[1]["type"], "")
        self.assertEqual(clues[1]["ranges"], [])  # paraphrased: still a clue, no location

    def test_final_risk_rules(self):
        located = [{"category": "LEFTOVER", "type": "NAME", "ranges": [(0, 3)]}]
        unlocated = [{"category": "LEFTOVER", "type": "NAME", "ranges": []}]
        self.assertEqual(final_risk("low", located), "high")      # a direct identifier is always high
        self.assertEqual(final_risk("low", unlocated), "low")
        self.assertEqual(final_risk(None, []), "low")
        self.assertEqual(final_risk(None, unlocated), "medium")


class AssessTests(unittest.TestCase):
    def test_unreadable_reply_is_unknown_not_low(self):
        view = masked_view(TEXT, [])
        result = assess_note(FakeClient("no json here"), view)
        self.assertEqual(result.risk, "unknown")
        self.assertTrue(result.parse_error)

    def test_only_the_masked_text_is_sent(self):
        replacer = Replacer(0).fit([{"text": TEXT, "spans": [NAME_SPAN, DATE_SPAN]}])
        _, changes = replacer.apply({"text": TEXT, "spans": [NAME_SPAN, DATE_SPAN]})
        client = FakeClient(reply("low"))
        assess_note(client, masked_view(TEXT, changes))
        sent = json.dumps(client.calls)
        for banned in ("Kim", "Reyes", "2025-03-02"):
            self.assertNotIn(banned, sent)

    def test_cache_hit_costs_nothing(self):
        view = masked_view(TEXT, [])
        client = FakeClient(reply("low"))
        with tempfile.TemporaryDirectory() as tmp:
            cache = Cache(tmp, PROMPT_VERSION)
            first = assess_note(client, view, cache)
            second = assess_note(client, view, cache)
        self.assertEqual(len(client.calls), 1)
        self.assertTrue(second.cached)
        self.assertEqual(second.usage, {})
        self.assertEqual(first.risk, second.risk)

    def test_cache_key_depends_on_the_prompt_version(self):
        client = FakeClient(reply("low"))
        self.assertNotEqual(Cache(None, "rt1").key(client, "x"), Cache(None, "rt2").key(client, "x"))


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.note = generate.generate_notes(5, 3)[0]

    def test_variants_are_deterministic(self):
        for variant in probes_mod.VARIANTS:
            self.assertEqual(make_probe(self.note, variant, 1), make_probe(self.note, variant, 1))

    def test_true_spans_stay_valid_after_the_appended_line(self):
        probe = make_probe(self.note, "planted")
        for s in probe["spans"]:
            self.assertEqual(probe["text"][s["start"]:s["end"]], s["text"])

    def test_planted_range_covers_a_clue_sentence_and_control_has_none(self):
        planted = make_probe(self.note, "planted")
        start, end = planted["planted"]
        self.assertIn(planted["text"][start:end], CLUES[planted["category"]])
        control = make_probe(self.note, "control")
        self.assertIsNone(control["planted"])
        self.assertEqual(control["withheld"], [])
        self.assertEqual(len(control["spans"]), len(self.note["spans"]))

    def test_leak_withholds_spans_from_the_replacement_step(self):
        leak = make_probe(self.note, "leak")
        self.assertEqual(len(leak["withheld"]), 2)
        self.assertEqual(len(leak["spans"]), len(self.note["spans"]) - 2)
        kept = {(s["start"], s["end"]) for s in leak["spans"]}
        self.assertTrue(all((w["start"], w["end"]) not in kept for w in leak["withheld"]))

    def test_unknown_variant_is_rejected(self):
        with self.assertRaises(ValueError):
            make_probe(self.note, "sneaky")


class ScoreTests(unittest.TestCase):
    def rec(self, variant, risk, clues=(), planted=None, withheld=(), category=""):
        return {"variant": variant, "risk": risk, "planted": planted, "category": category,
                "withheld": [dict(w) for w in withheld],
                "clues": [{"category": c, "ranges": [r]} for c, r in clues]}

    def test_scores(self):
        records = [
            self.rec("control", "low"),
            self.rec("control", "medium"),
            self.rec("planted", "high", [("OCCUPATION", (100, 120))], (105, 130), category="OCCUPATION"),
            self.rec("planted", "medium", [("OCCUPATION", (0, 5))], (105, 130), category="OCCUPATION"),
            self.rec("leak", "high", [("LEFTOVER", (10, 15))],
                     withheld=[{"start": 10, "end": 15, "type": "NAME"}, {"start": 40, "end": 50, "type": "DATE"}]),
        ]
        s = score(records)
        self.assertEqual(s["control"]["flagged_medium_or_high"]["count"], 1)
        self.assertEqual(s["planted"]["flagged_medium_or_high"]["count"], 2)
        self.assertEqual(s["planted"]["planted_line_cited"]["count"], 1)   # the second cited elsewhere
        self.assertEqual(s["planted"]["flagged_and_cited"]["count"], 1)
        self.assertEqual(s["leak"]["withheld_found"]["count"], 1)
        self.assertEqual(s["leak"]["by_type"]["DATE"]["count"], 0)

    def test_empty_groups_do_not_divide_by_zero(self):
        s = score([])
        self.assertIsNone(s["control"]["flagged_medium_or_high"]["rate"])
        self.assertIsNone(wilson(0, 0))

    def test_interval_is_wide_for_few_notes(self):
        low, high = wilson(5, 5)
        self.assertLess(low, 0.6)
        self.assertEqual(high, 1.0)


class LoopTests(unittest.TestCase):
    def test_leftover_is_sent_back_and_removed_but_rare_clue_is_only_reviewed(self):
        text = "Patient: Kim Reyes. Works as the only blacksmith in town. Call 555-0100."
        spans = [{"start": 9, "end": 18, "type": "NAME"}]
        replacer = Replacer(0).fit([{"text": text, "spans": spans + [{"start": 9, "end": 18, "type": "NAME"}]}])

        def model(messages):
            seen = note_text(messages)
            clues = [("only blacksmith in town", "OCCUPATION", "")]
            if "555-0100" in seen:
                clues.append(("555-0100", "LEFTOVER", "PHONE"))
            return reply("medium", *clues)

        result = harden(replacer, {"text": text, "spans": spans, "patient_key": "P1"}, FakeClient(model))
        self.assertEqual(len(result.assessments), 2)
        self.assertEqual(result.assessments[0].risk, "high")
        self.assertEqual(result.risk, "medium")
        self.assertEqual([a["type"] for a in result.added], ["PHONE"])
        self.assertNotIn("555-0100", result.text)
        self.assertIn("only blacksmith in town", result.text)   # clinical content is never edited
        self.assertEqual([r["category"] for r in result.review], ["OCCUPATION"])

    def test_clean_note_takes_one_round(self):
        text = "Patient: Kim Reyes."
        spans = [{"start": 9, "end": 18, "type": "NAME"}]
        replacer = Replacer(0).fit([{"text": text, "spans": spans}])
        client = FakeClient(reply("low"))
        result = harden(replacer, {"text": text, "spans": spans}, client)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(result.added, [])

    def test_loop_stops_after_max_rounds_even_if_the_model_keeps_finding_things(self):
        text = "Call 555-0100 or 555-0101 or 555-0102 or 555-0103."
        replacer = Replacer(0).fit([{"text": text, "spans": []}])
        order = iter(["555-0100", "555-0101", "555-0102", "555-0103"])
        client = FakeClient(lambda m: reply("high", (next(order), "LEFTOVER", "PHONE")))
        result = harden(replacer, {"text": text, "spans": []}, client, max_rounds=2)
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(len(result.assessments), 3)


class RunTests(unittest.TestCase):
    def test_plumbing_with_a_scripted_reviewer(self):
        """Not a measurement of any model: a scripted reviewer that reports the planted
        line and any withheld string checks that probes, masking and scoring line up."""
        notes = generate.generate_notes(5, 4)[:3]
        probes = build_probes(notes, probes_mod.VARIANTS, 0)
        sentences = [s for group in CLUES.values() for s in group]
        withheld = {t for p in probes for t in (p["text"][w["start"]:w["end"]] for w in p["withheld"])}

        def model(messages):
            seen = note_text(messages)
            clues = [(s, "OTHER", "") for s in sentences if s in seen]
            clues += [(t, "LEFTOVER", "NAME") for t in withheld if t in seen]
            return reply("medium" if clues else "low", *clues)

        replacer = Replacer(0).fit([{"text": p["text"], "spans": p["spans"]} for p in probes])
        records, stopped = run_probes(probes, replacer, FakeClient(model), Cache(None), Budget(0))
        self.assertFalse(stopped)
        s = score(records)
        self.assertEqual(s["control"]["flagged_medium_or_high"]["count"], 0)
        self.assertEqual(s["planted"]["flagged_and_cited"]["count"], 3)
        self.assertEqual(s["leak"]["withheld_found"]["count"], s["leak"]["withheld_found"]["of"])
        self.assertGreater(s["leak"]["withheld_found"]["of"], 0)

    def test_token_cap_stops_the_run(self):
        notes = generate.generate_notes(5, 4)[:3]
        probes = build_probes(notes, probes_mod.VARIANTS, 0)
        replacer = Replacer(0).fit([{"text": p["text"], "spans": p["spans"]} for p in probes])
        records, stopped = run_probes(probes, replacer, FakeClient(reply("low")), Cache(None), Budget(250))
        self.assertTrue(stopped)
        self.assertEqual(len(records), 3)

    def test_dry_run_calls_nothing_and_test_split_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notes.jsonl"
            path.write_text("".join(json.dumps(n) + "\n" for n in generate.generate_notes(3, 4)),
                            encoding="utf-8")
            out = io.StringIO()
            with mock.patch("urllib.request.urlopen") as net, contextlib.redirect_stdout(out):
                self.assertEqual(run_main(["--notes", str(path), "--limit", "2"]), 0)
            net.assert_not_called()
            self.assertIn("DRY RUN", out.getvalue())
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                run_main(["--notes", str(path), "--split", "test"])

    def test_messages_never_include_answers(self):
        note = generate.generate_notes(5, 3)[0]
        probe = make_probe(note, "planted")
        replacer = Replacer(0).fit([{"text": probe["text"], "spans": probe["spans"]}])
        _, changes = replacer.apply({"text": probe["text"], "spans": probe["spans"], "patient_key": "P1"})
        sent = json.dumps(build_messages(masked_view(probe["text"], changes).text))
        for s in note["spans"]:
            if s["type"] in ("NAME", "ID", "PHONE", "EMAIL") and len(s["text"]) > 4:
                self.assertNotIn(s["text"], sent)


if __name__ == "__main__":
    unittest.main()
