import json
import re
import unittest
from pathlib import Path

from deid.agent.pipeline import detect_and_verify, review_and_clean
from deid.app.offline import OfflineModel
from deid.audit import coverage
from deid.audit.report import render
from deid.detect.client import Budget
from deid.detect.detector import Cache
from deid.replace.engine import Replacer, clean_spans
from deid.replace.rules import find_rule_spans, zip_replacement

ROOT = Path(__file__).resolve().parents[1]


def found(text, existing=()):
    return [(s["type"], text[s["start"]:s["end"]]) for s in find_rule_spans(text, existing)]


class RuleSpans(unittest.TestCase):
    def test_ages_of_ninety_or_more(self):
        text = "A 92-year-old man, age 94; her mother, a 101 yo woman, and a 95 y/o neighbor."
        self.assertEqual(found(text), [("AGE", "92"), ("AGE", "94"), ("AGE", "101"), ("AGE", "95")])

    def test_ages_that_are_not_ages(self):
        for text in ("88-year-old", "age 89", "smoked 95 years", "BP 95/60", "dose 95 mg", "age 95 mg",
                     "He is 9 years old", "ID 12345", "aged 150"):
            self.assertEqual(found(text), [], text)

    def test_zip_needs_a_cue_and_loses_its_last_digits(self):
        text = "Ames, IA 50010-1234 and ZIP code 55601, but MRN 12345 and ID 67890 and 123456 alone"
        self.assertEqual(found(text), [("ZIP", "50010-1234"), ("ZIP", "55601")])
        self.assertEqual(zip_replacement("50010-1234"), "50000")
        self.assertEqual(zip_replacement("03601"), "00000")  # a restricted three-digit prefix

    def test_urls_and_ip_addresses(self):
        text = "Portal https://portal.clinic.org/p/1?x=2. Also www.clinic.org, logged from 10.20.30.40; version 1.2.3; 300.1.1.1"
        self.assertEqual(found(text), [("URL", "https://portal.clinic.org/p/1?x=2"), ("URL", "www.clinic.org"),
                                       ("IP", "10.20.30.40")])

    def test_existing_spans_win(self):
        text = "Lives in Ames, IA 50010."
        zip_at = text.index("50010")
        self.assertEqual(found(text, [{"start": 9, "end": zip_at + 5}]), [])

    def test_no_rule_hit_in_the_project_datasets_once_addresses_are_labeled(self):
        for name in ("data/generated/notes.jsonl",):
            for line in (ROOT / name).read_text(encoding="utf-8").splitlines():
                note = json.loads(line)
                self.assertEqual(find_rule_spans(note["text"], note["spans"]), [], note["note_id"])


class Replacement(unittest.TestCase):
    TEXT = "Mr Kim, 92-year-old, ZIP 50010-1234, from 10.20.30.40 and 10.20.30.41, https://a.example.com/x, www.b.org. Seen 2025-04-11 and 4/12/2025."

    def run_mode(self, mode):
        spans = find_rule_spans(self.TEXT)
        for needle, kind in (("Mr Kim", "NAME"), ("2025-04-11", "DATE"), ("4/12/2025", "DATE")):
            i = self.TEXT.index(needle)
            spans.append({"start": i, "end": i + len(needle), "type": kind})
        replacer = Replacer(0, mode).fit([{"text": self.TEXT, "spans": spans}])
        return replacer.apply({"text": self.TEXT, "spans": spans, "patient_key": "p1"})

    def test_rule_types_are_rewritten(self):
        text, changes = self.run_mode("shift")
        self.assertIn("90+-year-old", text)
        self.assertIn("ZIP 50000,", text)
        self.assertIn("192.0.2.1 and 192.0.2.2", text)  # two different addresses, two different stand-ins
        self.assertIn("https://example.org,", text)
        self.assertIn("www.example.org.", text)
        for forbidden in ("50010", "10.20.30.40", "a.example.com", "b.org", "92-year"):
            self.assertNotIn(forbidden, text)
        rules = {c["type"]: c["rule"] for c in changes}
        self.assertEqual(rules["AGE"], "age-90-plus")
        self.assertEqual(rules["ZIP"], "zip-first-three")

    def test_same_ip_gets_the_same_stand_in(self):
        replacer = Replacer(0)
        self.assertEqual(replacer.replace_value("IP", "10.1.1.1", "k")[0], replacer.replace_value("IP", "10.1.1.1", "k")[0])
        self.assertNotEqual(replacer.replace_value("IP", "10.1.1.1", "k")[0], replacer.replace_value("IP", "10.1.1.2", "k")[0])

    def test_year_only_date_mode(self):
        text, changes = self.run_mode("year")
        self.assertIn("Seen 2025 and 2025.", text)
        self.assertEqual({c["rule"] for c in changes if c["type"] == "DATE"}, {"date-year-only"})

    def test_year_only_removes_a_date_with_no_year(self):
        replacer = Replacer(0, "year")
        self.assertEqual(replacer.replace_value("DATE", "Apr 21", "k")[0], "[DATE]")

    def test_state_round_trips_the_mode_and_the_ip_map(self):
        replacer = Replacer(3, "year")
        stand_in = replacer.replace_value("IP", "10.1.1.1", "k")[0]
        again = Replacer.from_state(json.loads(json.dumps(replacer.state())))
        self.assertEqual(again.date_mode, "year")
        self.assertEqual(again.replace_value("IP", "10.1.1.1", "k")[0], stand_in)

    def test_bad_mode_is_refused(self):
        with self.assertRaises(ValueError):
            Replacer(0, "week")


class InThePipeline(unittest.TestCase):
    def test_rule_spans_are_cleaned_and_audited_with_their_source(self):
        import tempfile
        text = "Patient: Dana Reyes, a 94-year-old, ZIP 50010. Portal https://p.example.com/q. Seen 2025-04-11."
        notes = [{"note_id": "N1", "patient_id": "P1", "text": text}]
        with tempfile.TemporaryDirectory() as tmp:
            client = OfflineModel()
            batch, _ = detect_and_verify(notes, client, Cache(Path(tmp) / "a"), Cache(Path(tmp) / "b"),
                                         Budget(10**9), 0.8, verify=False)
            outcomes, _, _ = review_and_clean(batch, client, Cache(Path(tmp) / "c"), Budget(10**9), 0, 0.8, 0,
                                              redteam=False)
        out = outcomes[0]
        for original in ("Dana", "Reyes", "94", "50010", "https://p.example.com/q"):
            self.assertNotIn(original, out.cleaned)
        by_type = {e["type"]: e for e in out.audit["entries"]}
        for kind in ("AGE", "ZIP", "URL"):
            self.assertEqual(by_type[kind]["detector"], "safe-harbor rules")
            self.assertEqual(by_type[kind]["confidence"], 1.0)
        self.assertEqual(by_type["NAME"]["detector"], client.model)
        self.assertTrue(render([out.audit], {"notes": 1, "changes": 0, "changes_needing_review": 0, "review_items": 0,
                                             "by_type": {}, "risk_levels": {}}).count("Safe Harbor coverage") >= 1)


class Coverage(unittest.TestCase):
    def test_all_eighteen_categories_with_a_known_status(self):
        self.assertEqual([r["number"] for r in coverage.rows()], list(range(1, 19)))
        self.assertTrue(all(r["status"] in coverage.STATUSES for r in coverage.rows()))

    def test_document_is_current(self):
        self.assertEqual((ROOT / "docs" / "COVERAGE.md").read_text(encoding="utf-8"), coverage.markdown())

    def test_every_rule_type_has_a_row_that_says_rule(self):
        text = coverage.markdown()
        for word in ("URLs", "IP addresses"):
            self.assertRegex(text, rf"\| {word}[^|]*\| rule \|" if word == "IP addresses" else r"\| Web addresses \(URLs\) \| rule \|")


if __name__ == "__main__":
    unittest.main()
