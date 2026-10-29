"""Relative and year-only dates, eponym uses, and the per-occurrence name check (fix for the adversarial run)."""

import json
import unittest

from deid.agent import nameuse
from deid.agent.nameuse import check_name_use, parse_verdicts
from deid.agent.pipeline import detect_and_verify, detect_one, review_and_clean
from deid.audit.build import build_note_audit
from deid.detect.client import Budget, Completion
from deid.detect.context import is_eponym_use, set_aside_reason
from deid.detect.detector import Cache, ParseError, detect_note
from deid.detect.matching import clean_items, find_spans
from deid.detect.prompt import SYSTEM


def item(text, kind="NAME", confidence=0.95, **extra):
    return {"text": text, "type": kind, "confidence": confidence, **extra}


class Scripted:
    """Answers detection with a fixed list and the name check with a fixed decision."""
    model, params = "scripted", {"max_tokens": 1}

    def __init__(self, items, decision="ordinary_word", name_reply=None, finish="stop"):
        self.items, self.decision, self.name_reply, self.finish = items, decision, name_reply, finish
        self.calls = []

    def complete(self, messages):
        system = messages[0]["content"]
        if "find personal identifiers" in system:
            kind, content = "detect", json.dumps({"identifiers": self.items})
        elif "help remove personal names" in system:
            kind = "nameuse"
            ids = [int(i) for i in __import__("re").findall(r"^(\d+)\. type=", messages[1]["content"], __import__("re").M)]
            content = self.name_reply if self.name_reply is not None else json.dumps({"verdicts": [
                {"id": i, "decision": self.decision, "why": "scripted"} for i in ids]})
        else:
            kind, content = "verify", json.dumps({"verdicts": []})
        self.calls.append((kind, messages))
        return Completion(content, {"prompt_tokens": 100, "completion_tokens": 20}, 0.01,
                          self.finish if kind == "nameuse" else "stop")

    def kinds(self):
        return [k for k, _ in self.calls]


class SetAsideTests(unittest.TestCase):
    def test_year_only_and_relative_dates_are_not_identifiers(self):
        for string in ("2019", "in 2019", "since 2021", "last Tuesday", "tomorrow", "yesterday", "3 days ago",
                       "two weeks ago", "next week", "in 2 weeks", "this morning", "the day before", "today"):
            self.assertIsNotNone(set_aside_reason(string, "DATE"), string)

    def test_calendar_dates_are_kept(self):
        for string in ("04/21/2025", "Apr 21", "4/21", "2019-04-02", "21 April 2025", "March 3rd", "last March"):
            self.assertIsNone(set_aside_reason(string, "DATE"), string)

    def test_only_dates_are_set_aside(self):
        self.assertIsNone(set_aside_reason("2019", "ID"))
        self.assertIsNone(set_aside_reason("tomorrow", "NAME"))

    def test_find_spans_records_what_it_set_aside(self):
        ignored = []
        text = "Seen last Tuesday, again 4/21/2025. Symptoms since 2019."
        spans, unmatched = find_spans(text, [item("last Tuesday", "DATE"), item("4/21/2025", "DATE"),
                                             item("2019", "DATE")], ignored)
        self.assertEqual([text[s["start"]:s["end"]] for s in spans], ["4/21/2025"])
        self.assertEqual(unmatched, [])
        self.assertEqual([(g["text"], g["source"]) for g in ignored], [("last Tuesday", "rule"), ("2019", "rule")])
        self.assertTrue(all(g["reason"] for g in ignored))


class EponymTests(unittest.TestCase):
    def use(self, text, word):
        i = text.index(word)
        return is_eponym_use(text, i, i + len(word))

    def test_a_name_followed_by_its_noun_is_a_condition(self):
        for text, word in (("History of Wilson disease.", "Wilson"), ("A Foley catheter was placed.", "Foley"),
                           ("Parkinson's disease noted.", "Parkinson"), ("Graves disease", "Graves"),
                           ("Hodgkin lymphoma", "Hodgkin")):
            self.assertTrue(self.use(text, word), text)

    def test_a_title_or_label_before_it_means_a_person(self):
        for text, word in (("Seen by Dr. Wilson disease follow-up", "Wilson"), ("Patient: Foley test", "Foley"),
                           ("Spoke with Mr. Bell test results", "Bell")):
            self.assertFalse(self.use(text, word), text)

    def test_last_first_form_is_a_person(self):
        self.assertFalse(self.use("Wilson, Hope was seen.", "Wilson"))

    def test_an_ordinary_sentence_is_not_an_eponym_use(self):
        self.assertFalse(self.use("Wilson reported pain.", "Wilson"))
        self.assertFalse(self.use("Short of breath.", "Short"))

    def test_only_the_condition_occurrence_is_set_aside(self):
        ignored = []
        text = "Patient: Wilson, Hope\nHistory of Wilson disease.\nSpoke with Mr. Wilson today."
        spans, _ = find_spans(text, [item("Wilson")], ignored)
        self.assertEqual([text[s["start"]:s["end"]] for s in spans], ["Wilson", "Wilson"])
        self.assertEqual([s["start"] for s in spans], [text.index("Wilson"), text.index("Mr. Wilson") + 4])
        self.assertEqual(len(ignored), 1)
        self.assertEqual(ignored[0]["start"], text.index("Wilson disease"))
        self.assertEqual(ignored[0]["source"], "rule")


class DoubtfulOccurrenceTests(unittest.TestCase):
    TEXT = "Patient: Hope Short\nShort of breath on exertion.\nSpoke with Mr. Short by phone."

    def test_only_a_flagged_name_without_a_cue_is_doubtful(self):
        spans, _ = find_spans(self.TEXT, [item("Hope Short"), item("Short", also_a_word=True)])
        doubtful = [self.TEXT[s["start"]:s["end"]] for s in spans if s.get("doubt")]
        self.assertEqual(doubtful, ["Short"])
        self.assertEqual(len(spans), 3)                      # the full name, the sentence start, "Mr. Short"
        self.assertEqual([s["start"] for s in spans if s.get("doubt")], [self.TEXT.index("Short of")])

    def test_without_the_flag_nothing_changes(self):
        spans, _ = find_spans(self.TEXT, [item("Hope Short"), item("Short")])
        self.assertFalse(any(s.get("doubt") for s in spans))

    def test_clean_items_keeps_the_flag_only_for_names(self):
        items, dropped = clean_items([{"text": "Short", "type": "NAME", "also_a_word": True},
                                      {"text": "4/5", "type": "DATE", "also_a_word": True},
                                      {"text": "Page", "type": "NAME", "also_a_word": "yes"}])
        self.assertEqual([i.get("also_a_word") for i in items], [True, None, None])

    def test_the_prompt_asks_for_the_flag_and_names_the_date_rules(self):
        self.assertIn("also_a_word", SYSTEM)
        self.assertIn("relative expressions", SYSTEM)
        self.assertIn("year on its own", SYSTEM)


class CheckTests(unittest.TestCase):
    TEXT = "Short of breath. Spoke with Hope Short."

    def spans(self):
        return [{"start": 0, "end": 5, "type": "NAME", "confidence": 0.9, "doubt": "name_use"}]

    def test_parse_accepts_fenced_and_junk_decisions_become_unsure(self):
        got = parse_verdicts('```json\n{"verdicts": [{"id": 0, "decision": "Ordinary_Word", "why": "x"}, '
                             '{"id": 1, "decision": "maybe"}]}\n```')
        self.assertEqual(got[0]["decision"], "ordinary_word")
        self.assertEqual(got[1]["decision"], "unsure")
        with self.assertRaises(ParseError):
            parse_verdicts("no json")

    def test_the_prompt_shows_the_word_in_its_context(self):
        model = Scripted([])
        check_name_use(model, self.TEXT, self.spans())
        sent = model.calls[0][1][1]["content"]
        self.assertIn("<<Short>> of breath", sent)

    def test_nothing_to_ask_costs_nothing(self):
        model = Scripted([])
        self.assertEqual(check_name_use(model, self.TEXT, []).asked, 0)
        self.assertEqual(model.calls, [])

    def test_unreadable_cut_off_or_skipped_answers_are_unsure(self):
        for model in (Scripted([], name_reply="sorry"), Scripted([], finish="length"),
                      Scripted([], name_reply=json.dumps({"verdicts": []}))):
            result = check_name_use(model, self.TEXT, self.spans())
            self.assertEqual(result.verdicts[(0, 5)]["decision"], "unsure")
        self.assertTrue(check_name_use(Scripted([], name_reply="sorry"), self.TEXT, self.spans()).parse_error)
        self.assertTrue(check_name_use(Scripted([], finish="length"), self.TEXT, self.spans()).truncated)

    def test_a_cut_off_reply_is_not_trusted_even_if_it_parses(self):
        reply = json.dumps({"verdicts": [{"id": 0, "decision": "ordinary_word", "why": "x"}]})
        result = check_name_use(Scripted([], name_reply=reply, finish="length"), self.TEXT, self.spans())
        self.assertEqual(result.verdicts[(0, 5)]["decision"], "unsure")

    def test_replies_are_cached_and_the_prompt_version_is_part_of_the_key(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            cache = Cache(Path(tmp), nameuse.PROMPT_VERSION)
            model = Scripted([])
            first = check_name_use(model, self.TEXT, self.spans(), cache)
            second = check_name_use(model, self.TEXT, self.spans(), cache)
        self.assertEqual(len(model.calls), 1)
        self.assertTrue(second.cached and second.usage == {})
        self.assertEqual(first.verdicts, second.verdicts)


class PipelineTests(unittest.TestCase):
    NOTE = {"note_id": "N1", "patient_id": "P1", "text": "Patient: Hope Short\nShort of breath on exertion.\n"
                                                         "History of Wilson disease. Seen last Tuesday and 4/21/2025.\n"}
    ITEMS = [item("Hope Short"), item("Short", also_a_word=True), item("Wilson", also_a_word=True),
             item("last Tuesday", "DATE"), item("4/21/2025", "DATE")]

    def detect(self, model, verify=True):
        return detect_one(self.NOTE, model, Cache(None), Cache(None, "vf1"), 0.8, verify)

    def test_an_ordinary_word_is_left_as_written_and_recorded(self):
        model = Scripted(self.ITEMS, "ordinary_word")
        detected, usage = self.detect(model)
        texts = [self.NOTE["text"][s["start"]:s["end"]] for s in detected.spans]
        self.assertEqual(texts, ["Hope Short", "4/21/2025"])
        sources = sorted((g["source"], g["text"]) for g in detected.ignored)
        self.assertEqual(sources, [("name-use check", "Short"), ("rule", "Wilson"),
                                   ("rule", "last Tuesday")])
        self.assertEqual(model.kinds().count("nameuse"), 1)
        self.assertEqual(usage["prompt_tokens"], 100)
        self.assertEqual(detected.flags["nameuse_asked"], 1)

    def test_a_name_use_stays_replaced_and_is_confirmed(self):
        detected, _ = self.detect(Scripted(self.ITEMS, "name"))
        texts = [self.NOTE["text"][s["start"]:s["end"]] for s in detected.spans]
        self.assertEqual(texts, ["Hope Short", "Short", "4/21/2025"])
        key = (self.NOTE["text"].index("Short of"), self.NOTE["text"].index("Short of") + 5)
        self.assertEqual(detected.verdicts[key]["decision"], "identifier")

    def test_unsure_stays_replaced_and_goes_to_a_person(self):
        detected, _ = self.detect(Scripted(self.ITEMS, "unsure"))
        texts = [self.NOTE["text"][s["start"]:s["end"]] for s in detected.spans]
        self.assertIn("Short", texts)
        audit = self.audit(detected)
        entry = [e for e in audit["entries"] if e["original"] == "Short"][0]
        self.assertEqual(entry["status"], "review")

    def test_an_unreadable_name_check_keeps_the_name_replaced(self):
        detected, _ = self.detect(Scripted(self.ITEMS, name_reply="garbage"))
        self.assertIn("Short", [self.NOTE["text"][s["start"]:s["end"]] for s in detected.spans])
        self.assertTrue(detected.flags["nameuse_parse_error"])
        self.assertEqual(detected.failures, [])      # the note is still cleaned, with the occurrence replaced

    def test_without_a_second_model_the_occurrence_stays_replaced_and_is_flagged(self):
        model = Scripted(self.ITEMS)
        detected, _ = self.detect(model, verify=False)
        self.assertEqual(model.kinds().count("nameuse"), 0)
        short = [s for s in detected.spans if self.NOTE["text"][s["start"]:s["end"]] == "Short"][0]
        self.assertLessEqual(short["confidence"], 0.5)
        entry = [e for e in self.audit(detected)["entries"] if e["original"] == "Short"][0]
        self.assertEqual(entry["status"], "review")

    def audit(self, detected):
        from deid.replace.engine import Replacer, clean_spans
        replacer = Replacer(0).fit([{"text": self.NOTE["text"], "spans": detected.spans}])
        _, changes = replacer.apply({"text": self.NOTE["text"], "spans": clean_spans(self.NOTE["text"], detected.spans),
                                     "patient_key": "P1", "note_id": "N1"})
        return build_note_audit("N1", self.NOTE["text"], detected.spans, changes, "scripted",
                                verdicts=detected.verdicts, ignored=detected.ignored)

    def test_the_audit_lists_everything_left_as_written_and_a_person_checks_the_models_calls(self):
        detected, _ = self.detect(Scripted(self.ITEMS, "ordinary_word"))
        audit = self.audit(detected)
        self.assertEqual(len(audit["ignored"]), 3)
        kinds = [r["kind"] for r in audit["review"]]
        self.assertEqual(kinds.count("not-replaced"), 1)      # the model's call; the two rule-based ones are informational
        reason = [r for r in audit["review"] if r["kind"] == "not-replaced"][0]["reasons"][0]
        self.assertIn("'Short'", reason)

    def test_the_cleaned_note_keeps_the_ordinary_uses_and_replaces_the_patient(self):
        model = Scripted(self.ITEMS, "ordinary_word")
        batch, _ = detect_and_verify([self.NOTE], model, Cache(None), Cache(None, "vf1"), Budget(0), 0.8)

        class Reviewer:
            model, params = "scripted", {"max_tokens": 1}

            def complete(self, messages):
                return Completion(json.dumps({"risk": "low", "clues": []}), {"prompt_tokens": 1, "completion_tokens": 1}, 0.0, "stop")
        outcomes, stopped, _ = review_and_clean(batch, Reviewer(), Cache(None, "rt1"), Budget(0), 0, 0.8, 1)
        cleaned = outcomes[0].cleaned
        self.assertIn("Short of breath", cleaned)
        self.assertIn("Wilson disease", cleaned)
        self.assertIn("last Tuesday", cleaned)
        self.assertNotIn("Hope Short", cleaned)
        self.assertNotIn("4/21/2025", cleaned)

    def test_detect_note_carries_the_ignored_list(self):
        found = detect_note(Scripted(self.ITEMS), self.NOTE["text"])
        self.assertEqual(sorted(g["text"] for g in found.ignored), ["Wilson", "last Tuesday"])


if __name__ == "__main__":
    unittest.main()
