import json
import tempfile
import unittest
from pathlib import Path

from deid.baselines import regex_baseline
from deid.baselines.common import write_predictions
from deid.eval.run import run
from deid.synth import generate


class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.notes = generate.generate_notes(11, 60)
        cls.gold = cls.dir / "notes.jsonl"
        cls.gold.write_text("".join(json.dumps(n) + "\n" for n in cls.notes), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def score(self, name, predictions, split="all"):
        pred = self.dir / f"{name}.jsonl"
        write_predictions(predictions, pred)
        return run(self.gold, pred, name, split, self.dir / "results", bootstrap=20)["metrics"]

    def test_oracle_scores_perfectly(self):
        oracle = {n["note_id"]: [{k: s[k] for k in ("start", "end", "type")} for s in n["spans"]]
                  for n in self.notes}
        all_ = self.score("oracle", oracle)["ALL"]
        self.assertEqual(all_["overlap"]["recall"], 1.0)
        self.assertEqual(all_["exact"]["precision"], 1.0)
        self.assertEqual(all_["leaked_char_rate"], 0.0)

    def test_empty_predictions_score_zero_recall(self):
        all_ = self.score("empty", {})["ALL"]
        self.assertEqual(all_["overlap"]["recall"], 0.0)
        self.assertEqual(all_["leaked_char_rate"], 1.0)
        self.assertIsNone(all_["overlap"]["precision"])

    def test_unknown_note_is_rejected(self):
        with self.assertRaises(ValueError):
            self.score("bogus", {"N9999": []})

    def test_unknown_type_is_rejected(self):
        with self.assertRaises(ValueError):
            self.score("badtype", {"N0001": [{"start": 0, "end": 3, "type": "SHOE"}]})

    def test_regex_baseline_finds_fixed_format_ids_without_false_positives(self):
        preds = {n["note_id"]: regex_baseline.detect(n["text"]) for n in self.notes}
        m = self.score("regex", preds)
        for t in ("PHONE", "EMAIL"):
            self.assertEqual(m[t]["overlap"]["recall"], 1.0, t)
        self.assertEqual(m["ALL"]["overlap"]["precision"], 1.0)
        self.assertEqual(m["NAME"]["overlap"]["recall"], 0.0)


if __name__ == "__main__":
    unittest.main()
