import json
import re
import tempfile
import unittest
from collections import defaultdict
from datetime import date
from pathlib import Path

from deid.synth import generate
from deid.synth.builder import validate_spans

REQUIRED_TYPES = {"NAME", "DATE", "ID", "PHONE", "EMAIL", "ADDRESS"}
# Surnames that legitimately appear unlabeled as eponyms ("Wilson disease").
EPONYM_CONTEXT = re.compile(r"^(?:'s|\s(?:disease|syndrome|phenomenon|thyroiditis|esophagus|palsy))")


class GeneratedNotesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.notes = generate.generate_notes()

    def test_note_count_meets_target(self):
        self.assertGreaterEqual(len(self.notes), 500)

    def test_all_required_types_present(self):
        found = {s["type"] for n in self.notes for s in n["spans"]}
        self.assertEqual(found, REQUIRED_TYPES)

    def test_every_span_validates(self):
        for note in self.notes:
            validate_spans(note["text"], note["spans"])

    def test_note_ids_unique(self):
        ids = [n["note_id"] for n in self.notes]
        self.assertEqual(len(ids), len(set(ids)))

    def test_date_norms_are_iso_and_consistent_per_patient(self):
        seen = defaultdict(set)
        for note in self.notes:
            for span in note["spans"]:
                if span["type"] != "DATE":
                    continue
                date.fromisoformat(span["norm"])
                if span["subtype"] in ("DOB", "ADMIT", "DC", "PRIOR", "FOLLOWUP"):
                    seen[(note["patient_id"], span["subtype"])].add(span["norm"])
        self.assertTrue(all(len(v) == 1 for v in seen.values()))

    def test_entities_are_consistent_across_notes(self):
        names = defaultdict(set)
        for note in self.notes:
            for span in note["spans"]:
                if span["type"] == "NAME" and span["subtype"] == "PATIENT":
                    self.assertEqual(span["entity"], note["patient_id"])
                    names[span["entity"]].add(span["text"])
        self.assertTrue(any(len(v) > 1 for v in names.values()))  # varied surface forms

    def test_no_unlabeled_copy_of_a_labeled_value(self):
        problems = []
        for note in self.notes:
            text, spans = note["text"], note["spans"]
            for value in {s["text"] for s in spans}:
                for match in re.finditer(r"(?<![\w-])" + re.escape(value) + r"(?![\w-])", text):
                    if any(s["start"] <= match.start() and match.end() <= s["end"] for s in spans):
                        continue
                    if EPONYM_CONTEXT.match(text[match.end():]):
                        continue
                    problems.append((note["note_id"], value))
        self.assertEqual(problems, [])

    def test_phone_like_strings_are_all_fictional(self):
        pattern = re.compile(r"\b\d{3}[-.]\d{3}[-.]\d{4}\b|\(\d{3}\) \d{3}-\d{4}")
        for note in self.notes:
            for match in pattern.finditer(note["text"]):
                digits = re.sub(r"\D", "", match.group())
                self.assertTrue(digits[3:8] == "55501", match.group())

    def test_lookalikes_present_and_unlabeled(self):
        text = "\n".join(n["text"] for n in self.notes)
        for lookalike in (r"BP \d+/\d+", r"\d/\d\d\d mg", r"Pain \d/10"):
            self.assertRegex(text, lookalike)
        for note in self.notes:
            for span in note["spans"]:
                before = note["text"][max(0, span["start"] - 5):span["start"]]
                self.assertNotRegex(before, r"(BP|Pain) $", note["note_id"])


class DeterminismTests(unittest.TestCase):
    def test_same_seed_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            ma = generate.write_notes(generate.generate_notes(5, 30), a, 5, 30)
            mb = generate.write_notes(generate.generate_notes(5, 30), b, 5, 30)
            self.assertEqual((Path(a) / "notes.jsonl").read_bytes(), (Path(b) / "notes.jsonl").read_bytes())
            self.assertEqual(ma["notes_sha256"], mb["notes_sha256"])

    def test_different_seed_differs(self):
        self.assertNotEqual(generate.generate_notes(1, 5), generate.generate_notes(2, 5))

    def test_manifest_counts_match_file(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = generate.write_notes(generate.generate_notes(3, 20), d, 3, 20)
            lines = (Path(d) / "notes.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(manifest["notes"], len(lines))
            self.assertEqual(manifest["spans"], sum(len(json.loads(l)["spans"]) for l in lines))


if __name__ == "__main__":
    unittest.main()
