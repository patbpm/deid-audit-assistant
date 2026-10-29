import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from deid.audit.build import build_note_audit, summarize
from deid.audit.report import cleaned_text, marked, render
from deid.audit.run import main as run_main
from deid.audit.verify import format_problems, verify_span
from deid.replace.engine import Replacer
from deid.synth import generate

TEXT = "Patient: Kim Reyes seen on 4/5/25 and Apr 21. Cell 555-0142. Note <b>bold</b> & more."
SPANS = [
    {"start": 9, "end": 18, "type": "NAME", "confidence": 0.95},
    {"start": 27, "end": 33, "type": "DATE", "confidence": 0.5},
    {"start": 38, "end": 44, "type": "DATE", "confidence": 0.9},
    {"start": 51, "end": 59, "type": "PHONE", "confidence": 0.99},
]


def audit(**kw):
    replacer = Replacer(0).fit([{"text": TEXT, "spans": SPANS}])
    _, changes = replacer.apply({"text": TEXT, "spans": SPANS, "patient_key": "P1"})
    return build_note_audit("N1", TEXT, SPANS, changes, "fake-model", **kw), changes


class VerifyTests(unittest.TestCase):
    def change(self, **kw):
        return {"flagged": False, "rule": "name-token", "type": "NAME", "original": "Kim", **kw}

    def test_clean_span_is_accepted(self):
        self.assertEqual(verify_span(self.change(), 0.95), {"decision": "accept", "reasons": []})

    def test_no_confidence_is_not_an_objection(self):
        self.assertEqual(verify_span(self.change(), None)["decision"], "accept")

    def test_each_reason_triggers_review(self):
        self.assertEqual(verify_span(self.change(), 0.5)["decision"], "review")
        self.assertEqual(verify_span(self.change(flagged=True))["decision"], "review")
        self.assertEqual(verify_span(self.change(rule="date-shift-assumed-month-first", type="DATE", original="4/5/25"))["decision"], "review")
        self.assertEqual(verify_span(self.change(rule="date-shift-no-year", type="DATE", original="Apr 21"))["decision"], "review")

    def test_format_problems(self):
        self.assertTrue(format_problems("PHONE", "12"))
        self.assertTrue(format_problems("ID", "ABCDEF"))
        self.assertTrue(format_problems("EMAIL", "nobody"))
        self.assertEqual(format_problems("PHONE", "555-0142"), [])


class BuildTests(unittest.TestCase):
    def test_every_change_has_a_full_trace(self):
        a, changes = audit()
        self.assertEqual(len(a["entries"]), len(changes))
        for e, c in zip(a["entries"], changes):
            self.assertEqual(TEXT[e["start"]:e["end"]], e["original"])
            self.assertEqual(e["replacement"], c["replacement"])
            self.assertEqual(e["detector"], "fake-model")
        self.assertEqual([e["confidence"] for e in a["entries"]], [0.95, 0.5, 0.9, 0.99])

    def test_review_queue_lists_low_confidence_and_guessed_dates(self):
        a, _ = audit()
        flagged = {e["original"] for e in a["entries"] if e["status"] == "review"}
        self.assertEqual(flagged, {"4/5/25", "Apr 21"})
        self.assertEqual(len(a["review"]), 2)

    def test_agreement_between_detectors_is_recorded(self):
        a, _ = audit(others={"regex": [{"start": 51, "end": 59, "type": "PHONE"}], "other": []})
        self.assertEqual([e["also_found_by"] for e in a["entries"]], [[], [], [], ["regex"]])

    def test_unmatched_strings_and_clues_join_the_queue(self):
        assessment = {"risk": "high", "clues": [
            {"category": "OCCUPATION", "text": "only blacksmith", "ranges": [(60, 70)], "why": "rare"}]}
        a, _ = audit(unmatched=["Ghost Name"], assessment=assessment)
        kinds = sorted(i["kind"] for i in a["review"])
        self.assertEqual(kinds, ["clue", "span", "span", "unmatched"])
        self.assertEqual(a["risk"], "high")
        self.assertTrue(a["assessed"])

    def test_unassessed_note_has_no_risk(self):
        a, _ = audit()
        self.assertIsNone(a["risk"])
        self.assertFalse(a["assessed"])

    def test_summary_counts(self):
        a, _ = audit()
        s = summarize([a])
        self.assertEqual((s["notes"], s["changes"], s["changes_needing_review"]), (1, 4, 2))
        self.assertEqual(s["by_type"], {"DATE": 2, "NAME": 1, "PHONE": 1})
        self.assertEqual(s["risk_levels"], {"not assessed": 1})


class ReportTests(unittest.TestCase):
    def test_cleaned_text_matches_the_engine(self):
        a, _ = audit()
        replacer = Replacer(0).fit([{"text": TEXT, "spans": SPANS}])
        expected, _ = replacer.apply({"text": TEXT, "spans": SPANS, "patient_key": "P1"})
        self.assertEqual(cleaned_text(a), expected)

    def test_text_is_escaped_so_a_note_cannot_inject_markup(self):
        a, _ = audit()
        page = render([a], summarize([a]))
        self.assertNotIn("<b>bold</b>", page)
        self.assertIn("&lt;b&gt;bold&lt;/b&gt;", page)

    def test_page_is_self_contained_and_carries_the_warnings(self):
        a, _ = audit()
        page = render([a], summarize([a]))
        self.assertNotIn("http://", page.replace("http://www.w3.org", ""))
        self.assertIn("Contains original identifiers", page)
        self.assertIn("not a compliance certification", page)
        self.assertIn('data-id="N1:0"', page)

    def test_marked_skips_overlaps(self):
        html = marked("abcdef", [(0, 3, "a", "x", ""), (2, 5, "b", "x", "")])
        self.assertEqual(html.count("<mark"), 1)


class RunTests(unittest.TestCase):
    def test_end_to_end_and_test_split_refusal(self):
        notes = generate.generate_notes(5, 3)
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "notes.jsonl").write_text("".join(json.dumps(n) + "\n" for n in notes), encoding="utf-8")
            pred = [{"note_id": n["note_id"], "spans": [
                {"start": s["start"], "end": s["end"], "type": s["type"], "confidence": 1.0}
                for s in n["spans"]]} for n in notes[:2]]
            (tmp / "pred.jsonl").write_text("".join(json.dumps(p) + "\n" for p in pred), encoding="utf-8")
            argv = ["--notes", str(tmp / "notes.jsonl"), "--pred", str(tmp / "pred.jsonl"),
                    "--detector", "fake", "--out", str(tmp / "out" / "audit")]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run_main(argv), 0)
            data = json.loads((tmp / "out" / "audit.json").read_text(encoding="utf-8"))
            self.assertEqual(data["summary"]["notes"], 2)
            self.assertTrue((tmp / "out" / "audit.html").exists())
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                run_main(argv + ["--split", "test"])


if __name__ == "__main__":
    unittest.main()
