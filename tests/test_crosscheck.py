"""The two-model cross-check, with scripted models. These check the plumbing and the policy, not any model."""

import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from deid.agent.crosscheck import AGREE, ONLY_PRIMARY, ONLY_SECOND, cross_check, disagreements, reason
from deid.agent.pipeline import detect_and_verify, detect_one, review_and_clean
from deid.agent.run import main as run_main
from deid.detect.client import Budget, Completion
from deid.detect.detector import Cache
from deid.eval.burden import analyse, with_disagreement_flagged

NOTE = {"note_id": "N1", "patient_id": "P1",
        "text": "Patient: Kim Reyes\nSeen on 4/25/25 by Dr. Wu.\nCall 555-0142 about MRN 7788991.\n"}


def item(text, kind, confidence=0.95):
    return {"text": text, "type": kind, "confidence": confidence}


ALL = [item("Kim Reyes", "NAME"), item("4/25/25", "DATE"), item("Wu", "NAME"), item("555-0142", "PHONE"),
       item("7788991", "ID")]


class Model:
    """Detects a fixed list. Answers the verifier (everything an identifier) and the name check (a name)."""

    def __init__(self, name, items, reply=None, finish="stop"):
        self.model, self.params = name, {"max_tokens": 1}
        self.items, self.reply, self.finish = items, reply, finish
        self.calls = []

    def complete(self, messages):
        system = messages[0]["content"]
        usage = {"prompt_tokens": 10, "completion_tokens": 5}
        if "find personal identifiers" in system:
            self.calls.append("detect")
            content = self.reply if self.reply is not None else json.dumps({"identifiers": self.items})
            return Completion(content, usage, 0.0, self.finish)
        ids = [int(i) for i in re.findall(r"^(\d+)\. type=", messages[1]["content"], re.M)]
        kind = "nameuse" if "help remove personal names" in system else "verify"
        self.calls.append(kind)
        decision = "name" if kind == "nameuse" else "identifier"
        return Completion(json.dumps({"verdicts": [{"id": i, "decision": decision, "why": "scripted"} for i in ids]}),
                          usage, 0.0, "stop")


def run(primary, second, verify=True):
    return detect_one(NOTE, primary, Cache(None), Cache(None, "vf1"), 0.8, verify, (second, Cache(None)))


def texts(detected):
    return [NOTE["text"][s["start"]:s["end"]] for s in detected.spans]


class MergeTests(unittest.TestCase):
    A = {"start": 0, "end": 5, "type": "NAME"}
    B = {"start": 10, "end": 14, "type": "DATE"}
    C = {"start": 20, "end": 28, "type": "PHONE"}

    def test_agreement_primary_only_and_second_only(self):
        merged = cross_check([self.A, self.B], [{**self.A, "start": 1}, self.C])
        marks = {(s["start"], s["end"]): s["cross"] for s in merged}
        self.assertEqual(marks, {(0, 5): AGREE, (10, 14): ONLY_PRIMARY, (20, 28): ONLY_SECOND})

    def test_overlapping_spans_of_different_types_agree_on_place_but_are_flagged_for_type(self):
        merged = cross_check([self.A], [{**self.A, "type": "ID"}])
        self.assertEqual(merged[0]["cross"], AGREE)
        self.assertEqual(merged[0]["second_type"], "ID")
        self.assertIn("disagree on the type", reason(merged[0], "m1", "m2"))
        self.assertEqual(disagreements(merged), merged)

    def test_inputs_are_not_changed_and_no_overlaps_come_out(self):
        first, second = [dict(self.A)], [dict(self.C), {"start": 22, "end": 40, "type": "ADDRESS"}]
        merged = cross_check(first, second)
        self.assertEqual(first, [self.A])
        self.assertNotIn("cross", second[0])
        spans = sorted((s["start"], s["end"]) for s in merged)
        self.assertTrue(all(a[1] <= b[0] for a, b in zip(spans, spans[1:])))

    def test_reasons_name_the_models(self):
        self.assertIn("only m1 found this; m2 did not", reason({"cross": ONLY_PRIMARY, "type": "NAME"}, "m1", "m2"))
        self.assertIn("only m2 found this; m1 did not", reason({"cross": ONLY_SECOND, "type": "NAME"}, "m1", "m2"))
        self.assertIsNone(reason({"cross": AGREE, "type": "NAME"}, "m1", "m2"))


class DetectionTests(unittest.TestCase):
    def test_two_models_that_agree_change_nothing_and_flag_nothing(self):
        detected, _ = run(Model("one", ALL), Model("two", ALL))
        self.assertEqual(texts(detected), ["Kim Reyes", "4/25/25", "Wu", "555-0142", "7788991"])
        self.assertTrue(all(s["cross"] == AGREE for s in detected.spans))
        self.assertEqual(detected.notices, [])

    def test_a_span_only_the_second_found_is_added_and_a_span_only_the_first_found_is_kept(self):
        detected, usage = run(Model("one", ALL[:3] + [ALL[4]]), Model("two", ALL[:3] + [ALL[3]]))
        marks = {NOTE["text"][s["start"]:s["end"]]: s["cross"] for s in detected.spans}
        self.assertEqual(marks["555-0142"], ONLY_SECOND)
        self.assertEqual(marks["7788991"], ONLY_PRIMARY)
        self.assertEqual(marks["Kim Reyes"], AGREE)
        self.assertEqual(detected.second_name, "two")
        self.assertEqual(len(detected.second_spans), 4)
        self.assertGreaterEqual(usage["prompt_tokens"], 20)        # the second model's tokens are counted

    def test_disagreements_get_a_third_opinion_from_the_verifier(self):
        primary = Model("one", ALL[:4])
        run(primary, Model("two", ALL[:3] + [ALL[4]]))
        self.assertEqual(primary.calls.count("verify"), 1)
        agreeing = Model("one", ALL)
        run(agreeing, Model("two", ALL))
        self.assertEqual(agreeing.calls.count("verify"), 0)

    def test_without_a_verifier_disagreements_still_stay_replaced(self):
        detected, _ = run(Model("one", ALL[:3]), Model("two", ALL), verify=False)
        self.assertEqual(texts(detected), ["Kim Reyes", "4/25/25", "Wu", "555-0142", "7788991"])

    def test_an_unreadable_or_cut_off_second_model_costs_a_notice_never_the_clean(self):
        for second in (Model("two", [], reply="sorry"), Model("two", ALL, finish="length")):
            detected, _ = run(Model("one", ALL), second)
            self.assertEqual(texts(detected), ["Kim Reyes", "4/25/25", "Wu", "555-0142", "7788991"])
            self.assertEqual(detected.failures, [])
            self.assertEqual(len(detected.notices), 1)
            self.assertIn("one model only", detected.notices[0])
            self.assertTrue(all("cross" not in s for s in detected.spans))

    def test_a_failed_primary_is_still_not_cleaned_and_the_second_is_not_asked(self):
        second = Model("two", ALL)
        detected, _ = run(Model("one", [], reply="sorry"), second)
        self.assertTrue(detected.failures)
        self.assertEqual(second.calls, [])

    def test_without_a_second_model_nothing_changes(self):
        detected, _ = detect_one(NOTE, Model("one", ALL), Cache(None), Cache(None, "vf1"), 0.8, True)
        self.assertTrue(all("cross" not in s for s in detected.spans))
        self.assertEqual((detected.second_name, detected.notices, detected.second_spans), ("", [], []))


class AuditTests(unittest.TestCase):
    def audit(self, primary, second):
        model = Model("one", [])
        batch, _ = detect_and_verify([NOTE], primary, Cache(None), Cache(None, "vf1"), Budget(0), 0.8,
                                     second=(second, Cache(None)))

        class Reviewer:
            model, params = "one", {"max_tokens": 1}

            def complete(self, messages):
                return Completion(json.dumps({"risk": "low", "clues": []}), {"prompt_tokens": 1, "completion_tokens": 1}, 0.0, "stop")
        outcomes, _, _ = review_and_clean(batch, Reviewer(), Cache(None, "rt1"), Budget(0), 0, 0.8, 1)
        return outcomes[0].audit

    def test_agreeing_spans_list_the_other_model_and_are_accepted(self):
        audit = self.audit(Model("one", ALL), Model("two", ALL))
        self.assertTrue(all(e["also_found_by"] == ["two"] for e in audit["entries"]))
        self.assertEqual([e for e in audit["entries"] if e["status"] == "review"], [])

    def test_disagreements_go_to_review_with_both_models_named(self):
        audit = self.audit(Model("one", ALL[:4]), Model("two", ALL[:3] + [ALL[4]]))
        flagged = {e["original"]: e for e in audit["entries"] if e["status"] == "review"}
        self.assertEqual(set(flagged), {"555-0142", "7788991"})
        self.assertTrue(any("only one found this; two did not" in r for r in flagged["555-0142"]["checks"]["reasons"]))
        self.assertTrue(any("only two found this; one did not" in r for r in flagged["7788991"]["checks"]["reasons"]))
        self.assertEqual(flagged["555-0142"]["verifier"]["decision"], "identifier")      # the third opinion is on record

    def test_a_note_checked_by_one_model_says_so_in_the_review_queue(self):
        audit = self.audit(Model("one", ALL), Model("two", [], reply="sorry"))
        self.assertEqual([r["kind"] for r in audit["review"]], ["notice"])


class CommandTests(unittest.TestCase):
    def test_the_command_writes_the_second_models_spans_and_counts_agreement(self):
        notes = [NOTE]
        primary, second = Model("one", ALL[:4]), Model("two", ALL[:3] + [ALL[4]])

        class Reviewer(Model):
            def complete(self, messages):
                if "red-team" in messages[0]["content"] or "re-identif" in messages[0]["content"].lower():
                    return Completion(json.dumps({"risk": "low", "clues": []}), {"prompt_tokens": 1, "completion_tokens": 1}, 0.0, "stop")
                return primary.complete(messages)
        client = Reviewer("one", ALL[:4])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notes.jsonl"
            path.write_text(json.dumps(NOTE) + "\n", encoding="utf-8")
            argv = ["--live", "--unlabeled", "--notes", str(path), "--limit", "1", "--name", "t", "--out-dir", tmp,
                    "--cache-dir", tmp, "--results-dir", str(Path(tmp) / "res"), "--second-provider", "custom"]
            seen = []

            def from_env(provider, max_output_tokens=4096):
                seen.append(provider)
                return client if provider == "meta" else second
            with mock.patch("deid.agent.run.ChatClient.from_env", side_effect=from_env), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run_main(argv), 0)
            summary = json.loads((Path(tmp) / "res" / "t.json").read_text(encoding="utf-8"))
            second_spans = (Path(tmp) / "t.second.jsonl").read_text(encoding="utf-8")
        self.assertEqual(seen, ["meta", "custom"])
        self.assertEqual(summary["cross_check"]["second_model"], "two")
        self.assertEqual((summary["cross_check"]["spans_agree"], summary["cross_check"]["only_primary"],
                          summary["cross_check"]["only_second"]), (3, 1, 1))
        self.assertEqual(len(json.loads(second_spans)["spans"]), 4)

    def test_the_same_provider_twice_is_refused(self):
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                run_main(["--live", "--second-provider", "meta"])


class BurdenTests(unittest.TestCase):
    def test_disagreement_caps_confidence_so_those_spans_need_a_look(self):
        preds = {"N1": [{"start": 0, "end": 3, "type": "NAME", "confidence": 0.99, "cross": ONLY_SECOND},
                        {"start": 5, "end": 8, "type": "NAME", "confidence": 0.99, "cross": AGREE},
                        {"start": 9, "end": 12, "type": "NAME", "cross": ONLY_PRIMARY}]}
        flagged = with_disagreement_flagged(preds)["N1"]
        self.assertEqual([p["confidence"] for p in flagged], [0.5, 0.99, 0.5])
        self.assertEqual(preds["N1"][0]["confidence"], 0.99)

    def test_a_disagreement_that_is_a_false_positive_costs_a_review_but_no_recall(self):
        notes = [{"note_id": "N1", "patient_id": "P1", "spans": [{"start": 0, "end": 3, "type": "NAME"},
                                                                  {"start": 5, "end": 8, "type": "NAME"}]}]
        preds = {"N1": [{"start": 0, "end": 3, "type": "NAME", "confidence": 0.99, "cross": AGREE},
                        {"start": 5, "end": 8, "type": "NAME", "confidence": 0.99, "cross": ONLY_SECOND},
                        {"start": 20, "end": 25, "type": "NAME", "confidence": 0.99, "cross": ONLY_PRIMARY}]}
        plain = analyse(notes, preds)
        flagged = analyse(notes, with_disagreement_flagged(preds))
        self.assertEqual(plain["band_candidates"], 0)
        self.assertEqual(flagged["band_candidates"], 2)
        self.assertEqual(flagged["recall_without_review"], 0.5)
        self.assertEqual(flagged["curves"]["ranked"][-1], 1.0)


if __name__ == "__main__":
    unittest.main()
