import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from deid.detect.client import Budget, Completion
from deid.detect.detector import ParseError
from deid.tables import columns, model_typing as mt
from deid.tables.run import column_typer, main as run_main, write_table


def reply(*items):
    return Completion(json.dumps({"columns": [{"name": n, "type": t, "why": "test"} for n, t in items]}),
                      {"prompt_tokens": 50, "completion_tokens": 20}, 0.1, "stop")


class Model:
    model, params = "m", {"max_tokens": 1}

    def __init__(self, completion):
        self.completion, self.calls = completion, []

    def complete(self, messages):
        self.calls.append(messages)
        return self.completion


TOWNS = ["Larkspur", "Ashgrove", "Quail Run", "Larkspur", "Ironwood"]
AMOUNTS = ["27701.51", "11046.75", "38377.88", "1500.00", "902.10"]
YEARS = ["27", "60", "58", "91", "44"]
NAMES = ["Holland, Beatriz D", "Garcia, Harriet T", "Ortega, Michael", "Reyes, Kim", "Frost, Ada"]
CODES = ["AB123456", "CD654321", "EF111222", "GH333444", "IJ555666"]


class VerifyTests(unittest.TestCase):
    def test_types_are_accepted_only_if_the_values_fit(self):
        self.assertTrue(mt.verify("TOWN", TOWNS))
        self.assertTrue(mt.verify("AGE", YEARS))
        self.assertTrue(mt.verify("SAFE", AMOUNTS))
        self.assertTrue(mt.verify("SAFE", ["F", "M", "F", "M", "F"]))
        self.assertFalse(mt.verify("AGE", TOWNS))
        self.assertFalse(mt.verify("DATE", TOWNS))
        self.assertFalse(mt.verify("EMAIL", AMOUNTS))

    def test_a_model_cannot_wave_an_identifier_column_through_as_safe(self):
        self.assertFalse(mt.verify("SAFE", NAMES))
        self.assertFalse(mt.verify("SAFE", CODES))
        self.assertFalse(mt.verify("SAFE", ["a@example.com", "b@example.org"]))
        self.assertFalse(mt.verify("SAFE", ["921-98-8010", "969-63-4931"]))
        self.assertFalse(mt.verify("SAFE", ["2025-01-02", "2025-02-03"]))
        self.assertFalse(mt.verify("SAFE", ["209-555-0125", "312-555-0100"]))
        self.assertFalse(mt.verify("SAFE", [f"free text number {i}" for i in range(40)]))      # too many distinct values
        self.assertFalse(mt.verify("SAFE", []))

    def test_parsing(self):
        out = mt.parse_types('```json\n{"columns": [{"name": "a", "type": "town", "why": "x"}, {"name": "b", "type": "wizard"}]}\n```')
        self.assertEqual(out, {"a": ("TOWN", "x"), "b": ("UNKNOWN", "")})
        with self.assertRaises(ParseError):
            mt.parse_types("no idea")

    def test_only_headers_and_a_few_distinct_values_are_sent(self):
        messages = mt.build_messages([("Billed", AMOUNTS * 20), ("Locality", TOWNS)])
        text = messages[1]["content"]
        self.assertIn('"Billed"', text)
        self.assertLessEqual(text.count("27701.51"), 1)
        self.assertNotIn("Reyes", text)


class ApplyTests(unittest.TestCase):
    def plan_and_rows(self):
        rows = [[a, b, c, d] for a, b, c, d in zip(TOWNS, AMOUNTS, NAMES, ["x"] * 5)]
        return columns.build_plan("t", ["Locality", "Billed", "Member", "Odd"], rows), rows

    def test_unknown_columns_are_placed_when_the_rules_confirm(self):
        plan, rows = self.plan_and_rows()
        types = {c["column"]: c["type"] for c in plan["columns"]}
        self.assertEqual((types["Locality"], types["Billed"]), ("UNKNOWN", "UNKNOWN"))
        placed = mt.apply_suggestions(plan, rows, {"Locality": ("TOWN", "city names"), "Billed": ("SAFE", "amounts"),
                                                   "Member": ("SAFE", "wrongly claims safe"), "Odd": ("UNKNOWN", "")})
        by = {c["column"]: c for c in plan["columns"]}
        self.assertEqual(placed, 2)
        self.assertEqual((by["Locality"]["type"], by["Locality"]["action"]), ("TOWN", "replace"))
        self.assertEqual((by["Billed"]["type"], by["Billed"]["action"]), ("SAFE", "keep"))
        self.assertEqual(by["Locality"]["decided_by"], "model, confirmed by the rules")
        self.assertEqual(by["Member"]["type"], "NAME")          # already placed by the rules: untouched
        self.assertEqual(by["Odd"]["type"], "UNKNOWN")
        self.assertIn("could not tell", by["Odd"]["reason"])

    def test_a_refused_suggestion_leaves_the_column_withheld_and_says_why(self):
        plan, rows = self.plan_and_rows()
        mt.apply_suggestions(plan, rows, {"Locality": ("AGE", "wrong")})
        c = next(c for c in plan["columns"] if c["column"] == "Locality")
        self.assertEqual((c["type"], c["action"]), ("UNKNOWN", "withhold"))
        self.assertIn("did not confirm", c["reason"])

    def test_the_typer_makes_one_call_per_table_caches_and_counts_tokens(self):
        plan, rows = self.plan_and_rows()
        model = Model(reply(("Locality", "TOWN"), ("Billed", "SAFE"), ("Odd", "UNKNOWN")))
        budget = Budget(0)
        with tempfile.TemporaryDirectory() as tmp:
            typer = column_typer(model, tmp, budget)
            self.assertEqual(typer("t", plan, rows), 2)
            self.assertEqual(len(model.calls), 1)
            self.assertEqual(budget.total, 70)
            plan2, rows2 = self.plan_and_rows()
            column_typer(model, tmp, Budget(0))("t", plan2, rows2)
            self.assertEqual(len(model.calls), 1)               # the same request came from the cache

    def test_an_unreadable_reply_places_nothing(self):
        plan, rows = self.plan_and_rows()
        model = Model(Completion("sorry", {}, 0.1, "stop"))
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(column_typer(model, tmp, Budget(0))("t", plan, rows), 0)

    def test_no_call_when_nothing_is_unplaced(self):
        rows = [["P0001", "30"], ["P0002", "40"]]
        plan = columns.build_plan("t", ["patient_id", "Age"], rows)
        model = Model(reply())
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(column_typer(model, tmp, Budget(0))("t", plan, rows), 0)
        self.assertEqual(model.calls, [])


class RunTests(unittest.TestCase):
    def test_model_typing_flag_places_columns_in_the_real_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            rows = [["P0001", "Larkspur", "27701.51"], ["P0002", "Ashgrove", "11046.75"], ["P0003", "Ironwood", "902.10"]]
            write_table(tmp / "t.csv", ["patient_id", "Locality", "Billed"], rows)
            model = Model(reply(("Locality", "TOWN"), ("Billed", "SAFE")))
            argv = ["--in", str(tmp / "t.csv"), "--cache-dir", str(tmp)]
            with contextlib.redirect_stdout(io.StringIO()):
                run_main(argv + ["--out-dir", str(tmp / "plain")])
                with mock.patch("deid.detect.client.ChatClient.from_env", return_value=model):
                    run_main(argv + ["--out-dir", str(tmp / "typed"), "--model-typing"])
            plain = (tmp / "plain" / "t.csv").read_text(encoding="utf-8").splitlines()[0]
            typed = (tmp / "typed" / "t.csv").read_text(encoding="utf-8").splitlines()
            self.assertEqual(plain, "patient_id")                                  # both columns withheld without the model
            self.assertEqual(typed[0], "patient_id,Locality,Billed")
            self.assertNotIn("Larkspur", "\n".join(typed))                         # the town was replaced
            self.assertIn("27701.51", "\n".join(typed))                            # the amount kept as is
            plan = json.loads((tmp / "typed" / "plan.json").read_text(encoding="utf-8"))
            self.assertEqual(plan["plans"]["t"]["columns"][1]["decided_by"], "model, confirmed by the rules")


if __name__ == "__main__":
    unittest.main()
