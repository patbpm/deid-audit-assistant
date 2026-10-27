import unittest

from deid.eval import TYPES
from deid.eval.metrics import evaluate, score_note
from deid.eval.run import split_of


def span(start, end, type_="NAME"):
    return {"start": start, "end": end, "type": type_}


class ScoreNoteTests(unittest.TestCase):
    def test_exact_match(self):
        c = score_note([span(0, 5)], [span(0, 5)])["NAME"]
        self.assertEqual((c["exact_tp"], c["gold_hit"], c["pred_hit"]), (1, 1, 1))
        self.assertEqual(c["gold_chars_covered"], 5)

    def test_partial_overlap_counts_for_overlap_not_exact(self):
        c = score_note([span(0, 10)], [span(0, 4)])["NAME"]
        self.assertEqual(c["exact_tp"], 0)
        self.assertEqual((c["gold_hit"], c["pred_hit"]), (1, 1))
        self.assertEqual((c["gold_chars"], c["gold_chars_covered"]), (10, 4))

    def test_wrong_type_is_a_miss_and_a_false_positive(self):
        counts = score_note([span(0, 5, "NAME")], [span(0, 5, "DATE")])
        self.assertEqual(counts["NAME"]["gold_hit"], 0)
        self.assertEqual(counts["DATE"]["pred"], 1)
        self.assertEqual(counts["DATE"]["pred_hit"], 0)

    def test_false_positive_and_miss(self):
        c = score_note([span(0, 5)], [span(20, 25)])["NAME"]
        self.assertEqual((c["gold_hit"], c["pred_hit"], c["pred"]), (0, 0, 1))

    def test_two_predictions_on_one_gold_span(self):
        c = score_note([span(0, 10)], [span(0, 5), span(5, 10)])["NAME"]
        self.assertEqual(c["gold_hit"], 1)  # recall counts the gold span once
        self.assertEqual(c["pred_hit"], 2)
        self.assertEqual(c["gold_chars_covered"], 10)


class EvaluateTests(unittest.TestCase):
    def test_known_rates(self):
        notes = [
            score_note([span(0, 5), span(10, 15)], [span(0, 5), span(30, 35)]),
            score_note([span(0, 5, "DATE")], []),
        ]
        result = evaluate(notes, bootstrap=50)
        name = result["NAME"]
        self.assertEqual(name["gold"], 2)
        self.assertAlmostEqual(name["overlap"]["recall"], 0.5)
        self.assertAlmostEqual(name["overlap"]["precision"], 0.5)
        self.assertAlmostEqual(name["leaked_char_rate"], 0.5)
        self.assertEqual(result["DATE"]["overlap"]["recall"], 0.0)
        self.assertIsNone(result["EMAIL"]["overlap"]["recall"])  # no gold spans
        self.assertEqual(set(result), {*TYPES, "ALL"})
        self.assertAlmostEqual(result["ALL"]["overlap"]["recall"], 1 / 3)

    def test_bootstrap_is_seeded(self):
        notes = [score_note([span(0, 5)], [span(0, 5)]), score_note([span(0, 5)], [])] * 5
        a = evaluate(notes, bootstrap=100, seed=3)
        b = evaluate(notes, bootstrap=100, seed=3)
        self.assertEqual(a["ALL"]["ci95"], b["ALL"]["ci95"])
        lo, hi = a["ALL"]["ci95"]["recall"]
        self.assertLessEqual(lo, 0.5)
        self.assertGreaterEqual(hi, 0.5)


class SplitTests(unittest.TestCase):
    def test_split_boundary(self):
        self.assertEqual(split_of("P0001"), "dev")
        self.assertEqual(split_of("P0050"), "dev")
        self.assertEqual(split_of("P0051"), "test")
        self.assertEqual(split_of("P0150"), "test")


if __name__ == "__main__":
    unittest.main()
