import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from deid.eval import compare
from deid.synth import generate


def spans_of(note, keep=1.0):
    spans = note["spans"]
    return [{"start": s["start"], "end": s["end"], "type": s["type"]} for s in spans[: int(len(spans) * keep)]]


def log_of(note_ids, cached=(), tokens=(100, 50), latency=2.0, model="m"):
    notes = [{"note_id": i, "cached": i in cached, "parse_error": False, "truncated": False, "unmatched": [],
              "latency_s": latency, "usage": {} if i in cached else
              {"prompt_tokens": tokens[0], "completion_tokens": tokens[1]}} for i in note_ids]
    return {"summary": {"model": model, "provider": "meta"}, "notes": notes}


class CompareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.notes = generate.generate_notes(5, 6)[:8]
        self.gold = self.dir / "gold.jsonl"
        self.gold.write_text("".join(json.dumps(n) + "\n" for n in self.notes), encoding="utf-8")

    def preds(self, name, keep, only=None):
        path = self.dir / f"{name}.jsonl"
        rows = [{"note_id": n["note_id"], "spans": spans_of(n, keep)} for n in self.notes
                if only is None or n["note_id"] in only]
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        return path

    def log(self, name, ids, **kw):
        path = self.dir / f"{name}.log.json"
        path.write_text(json.dumps(log_of(ids, **kw)), encoding="utf-8")
        return path

    def run_compare(self, systems, **kw):
        return compare.compare(self.gold, systems, "dev", "t", resamples=50, out_dir=self.dir / "out", **kw)

    def test_better_system_has_a_positive_paired_difference(self):
        ids = [n["note_id"] for n in self.notes]
        result = self.run_compare([("ref", self.preds("a", 0.5), None), ("better", self.preds("b", 1.0), None)])
        self.assertGreater(result["systems"]["better"]["recall"], result["systems"]["ref"]["recall"])
        low, high = result["recall_difference_vs_reference_ci95"]["better"]
        self.assertGreater(low, 0)
        self.assertEqual(result["systems"]["better"]["recall"], 1.0)
        self.assertEqual(result["notes_compared"], len(ids))

    def test_identical_systems_have_a_zero_difference(self):
        result = self.run_compare([("a", self.preds("a", 0.7), None), ("b", self.preds("b", 0.7), None)])
        self.assertEqual(result["recall_difference_vs_reference_ci95"]["b"], [0.0, 0.0])

    def test_only_notes_every_system_predicted_are_scored(self):
        ids = [n["note_id"] for n in self.notes]
        result = self.run_compare([("a", self.preds("a", 1.0), None), ("b", self.preds("b", 1.0, only=ids[:3]), None)])
        self.assertEqual(result["notes_compared"], 3)

    def test_cost_needs_a_price_and_skips_cached_notes(self):
        ids = [n["note_id"] for n in self.notes]
        log = self.log("a", ids, cached=set(ids[:2]), tokens=(1000, 500))
        none = self.run_compare([("a", self.preds("a", 1.0), log), ("b", self.preds("b", 1.0), None)])
        self.assertIsNone(none["systems"]["a"]["cost_usd"])
        priced = self.run_compare([("a", self.preds("a", 1.0), log), ("b", self.preds("b", 1.0), None)],
                                  price={"a": (2.0, 10.0)})
        a = priced["systems"]["a"]
        live = len(ids) - 2
        self.assertEqual((a["tokens_in"], a["tokens_out"], a["notes_from_cache"]), (1000 * live, 500 * live, 2))
        self.assertAlmostEqual(a["cost_usd"], (1000 * live * 2.0 + 500 * live * 10.0) / 1e6)
        self.assertAlmostEqual(a["cost_usd_per_1000_notes"], a["cost_usd"] / live * 1000)
        self.assertEqual(a["tokens_per_live_note"], 1500)

    def test_latency_percentiles_and_missing_log(self):
        ids = [n["note_id"] for n in self.notes]
        result = self.run_compare([("a", self.preds("a", 1.0), self.log("a", ids, latency=3.0)),
                                   ("b", self.preds("b", 1.0), None)])
        self.assertEqual(result["systems"]["a"]["latency_s_median"], 3.0)
        self.assertEqual(result["systems"]["b"]["log"], None)

    def test_markdown_shows_na_not_zero_for_unknowns(self):
        text = compare.markdown(self.run_compare([("a", self.preds("a", 1.0), None), ("b", self.preds("b", 0.5), None)]))
        self.assertIn("n/a", text)
        self.assertIn("reference", text)
        self.assertIn("Cost is n/a unless a price was supplied", text)

    def test_no_common_notes_is_an_error(self):
        ids = [n["note_id"] for n in self.notes]
        with self.assertRaises(ValueError):
            self.run_compare([("a", self.preds("a", 1.0, only=ids[:2]), None), ("b", self.preds("b", 1.0, only=ids[2:4]), None)])

    def test_argument_parsing_and_test_split_guard(self):
        self.assertEqual(compare.parse_price("a=1.5,6"), ("a", (1.5, 6.0)))
        with self.assertRaises(argparse.ArgumentTypeError):
            compare.parse_price("a=1.5")
        with self.assertRaises(argparse.ArgumentTypeError):
            compare.parse_pair("nopath")
        argv = ["--name", "t", "--gold", str(self.gold), "--system", f"a={self.preds('a', 1.0)}",
                "--system", f"b={self.preds('b', 1.0)}", "--out", str(self.dir / "o")]
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            compare.main(argv + ["--split", "test"])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(compare.main(argv), 0)
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            compare.main(["--name", "t", "--system", f"a={self.preds('a', 1.0)}"])


if __name__ == "__main__":
    unittest.main()
