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


class ReplacementOnHardCasesTests(unittest.TestCase):
    """The replacement engine, given the true spans, on every adversarial note."""

    def test_no_crash_nothing_unchanged_and_only_known_formats_are_flagged(self):
        from deid.replace.engine import Replacer
        notes = adversarial.generate_notes(FROZEN["seed"], FROZEN["per_family"])
        replacer = Replacer(0).fit([{"text": n["text"], "spans": n["spans"]} for n in notes])
        flagged, unchanged = set(), []
        for n in notes:
            _, changes = replacer.apply({"text": n["text"], "spans": n["spans"], "patient_key": n["patient_id"]})
            for span, change in zip(n["spans"], changes):
                if change["flagged"]:
                    flagged.add(span["subtype"])
                elif change["replacement"] == span["text"]:
                    unchanged.append(span["text"])
        self.assertEqual(unchanged, [])
        self.assertEqual(flagged, {"double_slash", "no_commas"})


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


FROZEN_B = json.loads(Path("data/adversarial_b.json").read_text(encoding="utf-8"))


class SetBTests(unittest.TestCase):
    """The second set, written after the first one's errors were read, to judge the fixes made because of them."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.notes = adversarial.generate_notes(FROZEN_B["seed"], FROZEN_B["per_family"], "b")
        cls.manifest = adversarial.write_notes(cls.notes, cls.tmp.name, FROZEN_B["seed"], FROZEN_B["per_family"], "b")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_generator_still_produces_the_recorded_set(self):
        diff = {k: (FROZEN_B[k], self.manifest[k]) for k in FROZEN_B if FROZEN_B[k] != self.manifest[k]}
        self.assertEqual(diff, {}, "set B differs from data/adversarial_b.json")

    def test_it_has_its_own_ids_a_new_seed_and_one_more_family(self):
        self.assertNotEqual(FROZEN_B["seed"], FROZEN["seed"])
        self.assertEqual({n["family"] for n in self.notes}, set(adversarial.FAMILIES_B))
        self.assertEqual(len(adversarial.FAMILIES_B), len(adversarial.FAMILIES) + 1)
        self.assertTrue(all(n["note_id"].startswith("B") and n["patient_id"].startswith("P8") for n in self.notes))
        for note in self.notes:
            for s in note["spans"]:
                self.assertEqual(note["text"][s["start"]:s["end"]], s["text"])

    def test_the_default_set_is_unchanged_by_the_second_vocabulary(self):
        self.assertEqual(adversarial.FAMILIES, adversarial.FAMILIES_B[:9])
        self.assertEqual(adversarial.generate_notes(FROZEN["seed"], FROZEN["per_family"])[0]["note_id"], "A0001")

    def test_its_words_are_disjoint_from_set_a_and_from_the_examples_in_the_prompts(self):
        from deid.agent import nameuse
        from deid.detect import prompt
        a, b = adversarial.VOCAB_A, adversarial.VOCAB_B
        for key in ("first_words", "last_words", "eponyms"):
            self.assertEqual(set(a[key]) & set(b[key]), set(), key)
        self.assertEqual(set(a["international"]) & set(b["international"]), set())
        self.assertEqual(set(a["lookalikes"]) & set(b["lookalikes"]), set())
        self.assertEqual(set(a["firsts"]) & set(b["firsts"]), set())
        self.assertEqual(set(a["lasts"]) & set(b["lasts"]), set())
        prompt_words = set(("Hunter", "Marsh", "Cook"))
        for example in prompt_words:
            self.assertIn(example, prompt.SYSTEM + nameuse.SYSTEM)
        used = set(b["first_words"]) | set(b["last_words"]) | set(b["eponyms"]) | set(b["firsts"]) | set(b["lasts"])
        self.assertEqual(used & prompt_words, set())
        for word in a["last_words"]:      # the common-word surnames the fixes were written after seeing
            self.assertNotIn(word, prompt.SYSTEM + nameuse.SYSTEM)
        # (Wilson and Foley were already in the first prompt, written before set A existed; set B uses neither.)
        for word in ("Wilson", "Foley"):
            self.assertNotIn(word, set(b["eponyms"]) | set(b["lasts"]) | set(b["last_words"]))

    def test_relative_dates_notes_label_two_dates_and_a_name_only(self):
        for note in self.notes:
            if note["family"] == "relative_dates":
                self.assertEqual(sorted(s["type"] for s in note["spans"]), ["DATE", "DATE", "NAME"])

    def test_eponym_conditions_and_common_words_stay_unlabeled(self):
        for note in self.notes:
            if note["family"] == "eponym_names":
                for s in note["spans"]:
                    after = note["text"][s["end"]:s["end"] + 1]
                    self.assertNotIn(after, ("-",))
                self.assertEqual(sum(s["type"] == "NAME" for s in note["spans"]), 2)

    def test_replacement_runs_on_every_hard_note(self):
        from deid.replace.engine import Replacer
        replacer = Replacer(0).fit([{"text": n["text"], "spans": n["spans"]} for n in self.notes])
        for n in self.notes:
            _, changes = replacer.apply({"text": n["text"], "spans": n["spans"], "patient_key": n["patient_id"]})
            self.assertEqual(len(changes), len(n["spans"]))
