import json
import re
import tempfile
import unittest
from pathlib import Path

from deid.eval import adversarial as scorer
from deid.eval.run import split_of
from deid.synth import adversarial

FROZEN = json.loads(Path("data/adversarial.json").read_text(encoding="utf-8"))


class AdversarialSetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.notes = adversarial.generate_notes(FROZEN["seed"], FROZEN["per_family"])
        cls.manifest = adversarial.write_notes(cls.notes, cls.tmp.name, FROZEN["seed"], FROZEN["per_family"])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_generator_still_produces_the_recorded_set(self):
        diff = {k: (FROZEN[k], self.manifest[k]) for k in FROZEN if FROZEN[k] != self.manifest[k]}
        self.assertEqual(diff, {}, "adversarial set differs from data/adversarial.json; if intended, "
                                   "copy the new manifest there and re-run every score on it")

    def test_spans_are_valid_and_every_family_is_present(self):
        self.assertEqual({n["family"] for n in self.notes}, set(adversarial.FAMILIES))
        for note in self.notes:
            for s in note["spans"]:
                self.assertEqual(note["text"][s["start"]:s["end"]], s["text"])
        for family in adversarial.FAMILIES:
            self.assertEqual(sum(n["family"] == family for n in self.notes), FROZEN["per_family"])

    def test_notes_are_kept_out_of_the_main_dataset_ids(self):
        ids = {n["note_id"] for n in self.notes}
        self.assertTrue(all(i.startswith("A") for i in ids))
        self.assertTrue(all(n["patient_id"].startswith("P9") for n in self.notes))
        self.assertEqual({split_of(n["patient_id"]) for n in self.notes}, {"test"})

    def test_values_come_from_reserved_or_fictional_ranges(self):
        for note in self.notes:
            for s in note["spans"]:
                if s["type"] == "PHONE":
                    self.assertRegex(s["text"], r"555[-. ]01\d\d")
                if s["type"] == "EMAIL":
                    self.assertRegex(s["text"].lower(), r"@(mail\.)?example\.(com|org)$")
                if s["subtype"].startswith("ssn"):
                    self.assertTrue(re.sub(r"\D", "", s["text"]).startswith("9"))

    def test_lookalike_notes_only_label_a_name_and_a_phone(self):
        for note in self.notes:
            if note["family"] == "lookalikes":
                self.assertEqual(sorted(s["type"] for s in note["spans"]), ["NAME", "PHONE"])

    def test_common_words_are_labeled_only_where_they_are_names(self):
        for note in self.notes:
            if note["family"] != "common_word_names":
                continue
            labeled = [(s["start"], s["end"]) for s in note["spans"]]
            first_word = note["text"].split("\n")[1].split()[0]
            first_line_start = note["text"].index("\n") + 1
            self.assertFalse(any(a <= first_line_start < b for a, b in labeled), first_word)


class ScoringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.notes = adversarial.generate_notes(1, 2)
        self.notes_path = Path(self.tmp.name) / "notes.jsonl"
        self.notes_path.write_text("".join(json.dumps(n) + "\n" for n in self.notes), encoding="utf-8")

    def predictions(self, name, spans_of):
        path = Path(self.tmp.name) / f"{name}.jsonl"
        path.write_text("".join(json.dumps({"note_id": n["note_id"], "spans": spans_of(n)}) + "\n"
                                for n in self.notes), encoding="utf-8")
        return path

    def test_an_oracle_scores_perfectly_and_an_empty_system_scores_zero(self):
        oracle = self.predictions("oracle", lambda n: [{"start": s["start"], "end": s["end"], "type": s["type"]}
                                                       for s in n["spans"]])
        empty = self.predictions("empty", lambda n: [])
        out = Path(self.tmp.name) / "out"
        good = scorer.run(self.notes_path, oracle, "oracle", out, bootstrap=20)
        bad = scorer.run(self.notes_path, empty, "empty", out, bootstrap=20)
        self.assertEqual(good["overall"]["recall"], 1.0)
        self.assertEqual(good["overall"]["false_positives"], 0)
        self.assertEqual(bad["overall"]["recall"], 0.0)
        self.assertEqual(set(good["families"]), set(adversarial.FAMILIES))

    def test_a_prediction_that_hits_nothing_is_counted_as_a_false_positive(self):
        noisy = self.predictions("noisy", lambda n: [{"start": 0, "end": 1, "type": "NAME"}] if n["family"] == "lookalikes" else [])
        # offset 0 is the start of "Patient:" in lookalike notes, which is not a labeled span
        result = scorer.run(self.notes_path, noisy, "noisy", Path(self.tmp.name) / "out", bootstrap=20)
        self.assertEqual(result["families"]["lookalikes"]["false_positives"], 2)

    def test_table_has_a_row_per_family(self):
        empty = self.predictions("empty", lambda n: [])
        result = scorer.run(self.notes_path, empty, "empty", Path(self.tmp.name) / "out", bootstrap=20)
        table = scorer.table([result])
        for family in adversarial.FAMILIES:
            self.assertIn(f"| {family} |", table)


if __name__ == "__main__":
    unittest.main()
