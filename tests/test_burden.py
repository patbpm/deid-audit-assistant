import contextlib
import io
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from deid.eval import burden


def note(note_id, patient, gold_spans):
    return {"note_id": note_id, "patient_id": patient,
            "spans": [{"start": a, "end": b, "type": "NAME"} for a, b in gold_spans]}


def pred(a, b, conf=None):
    s = {"start": a, "end": b, "type": "NAME"}
    if conf is not None:
        s["confidence"] = conf
    return s


# One note, four true identifiers at 0-5, 10-15, 20-25, 30-35.
NOTES = [note("N1", "P0001", [(0, 5), (10, 15), (20, 25), (30, 35)])]


class CurveTests(unittest.TestCase):
    def analyse(self, spans, hi=0.8, shuffles=50):
        return burden.analyse(NOTES, {"N1": spans}, hi, shuffles)

    def test_no_confidence_means_everything_is_unreviewed_and_there_is_no_band(self):
        r = self.analyse([pred(0, 5), pred(10, 15)])
        self.assertEqual(r["band_candidates"], 0)
        self.assertEqual(r["recall_without_review"], 0.5)
        self.assertEqual(r["curves"]["ranked"], [0.5])

    def test_review_buys_recall_in_confidence_order(self):
        spans = [pred(0, 5, 0.95), pred(10, 15, 0.7), pred(20, 25, 0.6), pred(50, 55, 0.5)]  # last is a false positive
        r = self.analyse(spans)
        self.assertEqual(r["recall_without_review"], 0.25)
        self.assertEqual(r["curves"]["ranked"], [0.25, 0.5, 0.75, 0.75])
        self.assertEqual(r["recall_ceiling"], 0.75)
        self.assertEqual(r["unreachable_by_review"], 0.25)       # the identifier at 30-35 has no candidate
        self.assertEqual((r["band_candidates"], r["band_candidates_that_are_true"]), (3, 2))

    def test_oracle_is_never_worse_than_ranked_or_random(self):
        spans = [pred(0, 5, 0.95), pred(60, 65, 0.7), pred(70, 75, 0.65), pred(10, 15, 0.6), pred(20, 25, 0.5)]
        r = self.analyse(spans, shuffles=200)
        for k in range(r["band_candidates"] + 1):
            self.assertGreaterEqual(r["curves"]["oracle"][k] + 1e-9, r["curves"]["ranked"][k])
            self.assertGreaterEqual(r["curves"]["oracle"][k] + 1e-9, r["curves"]["random"][k])
        self.assertEqual(r["curves"]["oracle"][1:3], [0.5, 0.75])   # true ones first
        self.assertGreater(r["spans_to_reach"]["ranked"]["100%"], r["spans_to_reach"]["oracle"]["100%"])

    def test_good_confidence_scores_beat_random_order(self):
        spans = [pred(0, 5, 0.79), pred(10, 15, 0.78), pred(20, 25, 0.77)] + [pred(100 + 10 * i, 105 + 10 * i, 0.1 + i / 100) for i in range(6)]
        r = self.analyse(spans, shuffles=300)
        self.assertEqual(r["spans_to_reach"]["ranked"]["100%"], 3)
        self.assertGreater(r["spans_to_reach"]["random"]["100%"], 3)

    def test_threshold_at_or_above_moves_a_span_out_of_the_band(self):
        spans = [pred(0, 5, 0.8), pred(10, 15, 0.79)]
        r = self.analyse(spans)
        self.assertEqual(r["band_candidates"], 1)
        self.assertEqual(r["recall_without_review"], 0.25)

    def test_overlapping_candidates_do_not_double_count(self):
        r = self.analyse([pred(0, 5, 0.5), pred(1, 4, 0.4)])
        self.assertEqual(r["curves"]["ranked"], [0.0, 0.25, 0.25])

    def test_type_labels_are_ignored(self):
        wrong_type = {"start": 0, "end": 5, "type": "DATE", "confidence": 0.5}
        self.assertEqual(self.analyse([wrong_type])["recall_ceiling"], 0.25)

    def test_empty_gold_does_not_divide_by_zero(self):
        r = burden.analyse([note("N2", "P0002", [])], {"N2": [pred(0, 3, 0.5)]}, 0.8, 5)
        self.assertIsNone(r["recall_without_review"])


class OutputTests(unittest.TestCase):
    def test_svg_is_well_formed_and_cli_writes_files_and_guards_the_test_split(self):
        notes = [note("N1", "P0001", [(0, 5), (10, 15)]), note("N2", "P0060", [(0, 5)])]
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "gold.jsonl").write_text("".join(json.dumps(n) + "\n" for n in notes), encoding="utf-8")
            preds = [{"note_id": "N1", "spans": [pred(0, 5, 0.9), pred(10, 15, 0.6), pred(30, 33, 0.5)]},
                     {"note_id": "N2", "spans": [pred(0, 5, 0.9)]}]
            (tmp / "pred.jsonl").write_text("".join(json.dumps(p) + "\n" for p in preds), encoding="utf-8")
            argv = ["--pred", str(tmp / "pred.jsonl"), "--gold", str(tmp / "gold.jsonl"), "--name", "t", "--out", str(tmp / "o")]
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(burden.main(argv), 0)
            result = json.loads((tmp / "o" / "burden-t.json").read_text(encoding="utf-8"))
            self.assertEqual(result["notes"], 1)          # N2 is a test-split patient
            ET.fromstring((tmp / "o" / "burden-t.svg").read_text(encoding="utf-8"))
            self.assertIn("review band", out.getvalue())
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                burden.main(argv + ["--split", "test"])

    def test_markdown_without_a_band_says_so(self):
        r = burden.analyse(NOTES, {"N1": [pred(0, 5)]}, 0.8, 5)
        self.assertIn("nothing to review", burden.markdown(r, "x"))


if __name__ == "__main__":
    unittest.main()
