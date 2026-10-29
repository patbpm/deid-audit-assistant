import tempfile
import unittest
from pathlib import Path

from deid.eval import adversarial as scorer
from deid.eval.stress import stress
from deid.synth import adversarial


class StressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.notes = adversarial.generate_notes(20261030, 20, "b")

    def score(self, answer):
        records = stress(self.notes, answer)
        with tempfile.TemporaryDirectory() as tmp:
            notes_path, pred_path = Path(tmp) / "n.jsonl", Path(tmp) / "p.jsonl"
            import json
            notes_path.write_text("".join(json.dumps(n) + "\n" for n in self.notes), encoding="utf-8")
            pred_path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
            return scorer.run(notes_path, pred_path, "t", Path(tmp) / "out", bootstrap=10)

    def test_a_check_that_always_releases_loses_real_surnames_and_the_set_can_see_it(self):
        worst = self.score("ordinary_word")
        self.assertLess(worst["overall"]["recall"], 0.98)
        self.assertEqual(worst["overall"]["false_positives"], 0)

    def test_a_check_that_never_releases_loses_nothing_and_keeps_the_ordinary_uses_replaced(self):
        for answer in ("name", "unsure"):
            safe = self.score(answer)
            self.assertEqual(safe["overall"]["recall"], 1.0)
            self.assertGreater(safe["overall"]["false_positives"], 0)


if __name__ == "__main__":
    unittest.main()
