import json
import tempfile
import unittest
from pathlib import Path

from deid.agent.pipeline import detect_and_verify, review_and_clean
from deid.app.offline import OfflineModel
from deid.detect.client import Budget, Completion
from deid.detect.detector import Cache
from deid.eval import linkage as linkage_eval
from deid.redteam.assess import Assessment, MaskedView
from deid.redteam.bundle import HEADER, bundle_view, linkage_item, run_linkage, which_notes
from deid.synth import linkage as probes


def clue(text, category="OCCUPATION"):
    return {"text": text, "category": category, "type": "", "why": "narrows the field", "ranges": []}


class Pieces(unittest.TestCase):
    VIEWS = [MaskedView("A teacher. [NAME] seen.", []), MaskedView("Won a state award.", [])]

    def test_bundle_view_labels_each_note(self):
        view = bundle_view(self.VIEWS)
        self.assertTrue(view.text.startswith(HEADER))
        self.assertIn("--- Note 2 of 2 ---", view.text)
        self.assertEqual(which_notes("state  award", self.VIEWS), [2])

    def test_a_raised_risk_makes_an_item_naming_the_notes_the_clues_come_from(self):
        a = Assessment("high", "high", [clue("A teacher"), clue("state award", "PUBLIC_EVENT")])
        item = linkage_item(["n1", "n2"], ["low", "low"], a, self.VIEWS)
        self.assertEqual(item["kind"], "linkage")
        self.assertEqual(item["patient_notes"], ["n1", "n2"])
        text = item["reasons"][0]
        self.assertIn("rated high risk", text)
        self.assertIn("up from low", text)
        self.assertIn("note 1", text)
        self.assertIn("note 2", text)

    def test_no_item_when_together_adds_nothing(self):
        self.assertIsNone(linkage_item(["n1", "n2"], ["low", "medium"], Assessment("medium", "medium", []), self.VIEWS))
        self.assertIsNone(linkage_item(["n1", "n2"], ["low", "low"], Assessment("low", "low", [clue("A teacher")]), self.VIEWS))

    def test_clues_at_the_same_level_still_surface_when_the_level_is_not_low(self):
        item = linkage_item(["n1", "n2"], ["medium", "medium"], Assessment("medium", "medium", [clue("A teacher")]), self.VIEWS)
        self.assertIsNotNone(item)
        self.assertNotIn("up from", item["reasons"][0])

    def test_an_unreadable_reply_is_said_not_ignored(self):
        item = linkage_item(["n1", "n2"], ["low", "low"], Assessment(None, "unknown", parse_error=True), self.VIEWS)
        self.assertIn("could not be assessed", item["reasons"][0])


class Reviewer:
    """Rates one note low; rates the bundle high with a clue."""
    model, params = "scripted-reviewer", {"max_tokens": 1}

    def __init__(self):
        self.calls = []

    def complete(self, messages):
        user = messages[1]["content"]
        self.calls.append(user)
        if HEADER in user:
            body = {"risk": "high", "clues": [{"text": "teaches high school chemistry", "category": "OCCUPATION",
                                               "type": "", "why": "few people"}]}
        else:
            body = {"risk": "low", "clues": []}
        return Completion(json.dumps(body), {"prompt_tokens": 10, "completion_tokens": 5}, 0.0, "stop")


class InThePipeline(unittest.TestCase):
    def outcomes(self, tmp, notes):
        client = OfflineModel()
        batch, _ = detect_and_verify(notes, client, Cache(Path(tmp) / "a"), Cache(Path(tmp) / "b"), Budget(10 ** 9), 0.8, verify=False)
        out, _, _ = review_and_clean(batch, client, Cache(Path(tmp) / "c"), Budget(10 ** 9), 0, 0.8, 0, redteam=False)
        return out

    def test_patients_with_two_notes_are_read_together_and_flagged_on_the_first_note(self):
        notes = [{"note_id": "N1", "patient_id": "P1", "text": "Patient: Kim Reyes\nShe teaches high school chemistry.\nSeen 2025-03-04."},
                 {"note_id": "N2", "patient_id": "P1", "text": "Patient: Kim Reyes\nShe lives in a town of 900 people.\nSeen 2025-04-04."},
                 {"note_id": "N3", "patient_id": "P2", "text": "Patient: Lee Wu\nSeen 2025-05-04 for a cough."}]
        with tempfile.TemporaryDirectory() as tmp:
            outcomes = self.outcomes(tmp, notes)
            reviewer = Reviewer()
            results = run_linkage(outcomes, reviewer, Cache(Path(tmp) / "link"), Budget(10 ** 9))
        self.assertEqual([r["patient_id"] for r in results], ["P1"])  # P2 has one note: nothing to link
        self.assertEqual(len(reviewer.calls), 1)
        self.assertNotIn("Kim", reviewer.calls[0])  # only masked views are sent
        self.assertNotIn("2025-03-04", reviewer.calls[0])
        first = next(o for o in outcomes if o.note_id == "N1")
        second = next(o for o in outcomes if o.note_id == "N2")
        self.assertEqual([i["kind"] for i in first.audit["review"] if i["kind"] == "linkage"], ["linkage"])
        self.assertFalse([i for i in second.audit["review"] if i["kind"] == "linkage"])
        self.assertTrue(results[0]["flagged"])

    def test_a_note_that_was_not_cleaned_is_left_out(self):
        notes = [{"note_id": "N1", "patient_id": "P1", "text": "Patient: Kim Reyes\nSeen 2025-03-04."},
                 {"note_id": "N2", "patient_id": "P1", "text": "Patient: Kim Reyes\nSeen 2025-04-04."}]
        with tempfile.TemporaryDirectory() as tmp:
            outcomes = self.outcomes(tmp, notes)
            outcomes[1].cleaned = None
            self.assertEqual(run_linkage(outcomes, Reviewer(), Cache(Path(tmp) / "link"), Budget(10 ** 9)), [])


class Probes(unittest.TestCase):
    def test_twelve_patients_three_notes_each_and_no_real_looking_identifier(self):
        data = probes.bundles()
        self.assertEqual([b["kind"] for b in data], ["planted"] * 6 + ["control"] * 6)
        for b in data:
            self.assertEqual(len(b["notes"]), 3)
            self.assertTrue(all("[NAME]" in n or "[DATE]" in n for n in b["notes"]))

    def test_the_eval_summary_counts(self):
        rows = [{"patient": "a", "kind": "planted", "single_risks": ["low", "low", "low"], "together_risk": "high", "flagged": True},
                {"patient": "b", "kind": "planted", "single_risks": ["medium", "low", "low"], "together_risk": "medium", "flagged": False},
                {"patient": "c", "kind": "control", "single_risks": ["low", "low", "low"], "together_risk": "low", "flagged": False}]
        s = linkage_eval.summarize(rows)
        self.assertEqual(s["planted"]["flagged"], 1)
        self.assertEqual(s["planted"]["any_single_medium_or_high"], 1)
        self.assertEqual(s["planted"]["together_medium_or_high"], 2)
        self.assertEqual(s["control"]["flagged"], 0)
        self.assertIn("Planted: 1 of 2 flagged", linkage_eval.markdown(rows, s))


class AppOption(unittest.TestCase):
    def test_the_option_is_read_and_ignored_by_an_engine_with_no_reviewer(self):
        from deid.app.backend import offline_backend
        from deid.app.jobs import JobStore
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(tmp, offline_backend())
            self.assertTrue(store.options({"linkage": True})["linkage"])
            self.assertFalse(store.options({})["linkage"])
            self.assertFalse(store.options({"linkage": "yes"})["linkage"])  # only a real true counts


if __name__ == "__main__":
    unittest.main()
