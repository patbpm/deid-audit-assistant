import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from deid.detect.client import Completion
from deid.synth import tables as synth
from deid.tables import columns
from deid.tables.apply import FREETEXT_MASK, WITHHELD_MASK, TableDeidentifier
from deid.tables.check import evaluate_style
from deid.tables.run import deidentify_tables, main as run_main, read_table, write_table


class ColumnTests(unittest.TestCase):
    def test_header_hints(self):
        cases = {"patient_id": "KEY", "PT_ID": "KEY", "Pt Name": "NAME", "DOB": "DATE", "Admitted": "DATE",
                 "e-mail": "EMAIL", "Tel": "PHONE", "Zip": "ZIP", "Addr": "STREET", "City": "TOWN", "MRN#": "ID",
                 "Ins ID": "ID", "Dx Code": "SAFE", "Remarks": "FREETEXT", "Age": "AGE", "patientName": "NAME",
                 "Provider": "NAME", "Zebra": None}
        for header, kind in cases.items():
            self.assertEqual(columns.header_hint(header), kind, header)

    def test_value_only_types(self):
        self.assertEqual(columns.value_type(["a@example.com", "b@example.org"]), "EMAIL")
        self.assertEqual(columns.value_type(["209-555-0125", "(312) 555-0100"]), "PHONE")
        self.assertEqual(columns.value_type(["8776341", "2434230", "7877252"]), "ID")      # bare digits are not phones
        self.assertIsNone(columns.value_type(["27701.51", "11046.75", "38377.88"]))        # amounts are not phones either
        self.assertEqual(columns.value_type(["921-98-8010", "969-63-4931"]), "ID")          # nor are SSNs
        self.assertEqual(columns.value_type(["1995-01-05", "2001-12-31"]), "DATE")
        self.assertEqual(columns.value_type(["NE", "IA", "IL", "NE"]), "STATE")
        self.assertEqual(columns.value_type(["7837 Ridge Blvd", "507 Summit St, Apt 4B"]), "STREET")
        self.assertEqual(columns.value_type(["Holland, Beatriz D", "Garcia, Harriet T"]), "NAME")
        self.assertIsNone(columns.value_type(["27", "60", "58"]))                           # ages are not guessed

    def test_a_header_the_values_contradict_is_unknown_not_trusted(self):
        kind, how, reason, _ = columns.classify("Birth Date", ["hello", "world", "again"])
        self.assertEqual((kind, how), ("UNKNOWN", "conflict"))
        self.assertIn("DATE", reason)

    def test_key_choice(self):
        rows = [["E00001", "P0001", "1000100"], ["E00002", "P0001", "1000100"], ["E00003", "P0002", "2000200"]]
        plan = columns.build_plan("t", None, rows)
        self.assertEqual(plan["key_column"], "col2")        # the first ID column whose values repeat
        self.assertIn("guessed", plan["key_reason"])
        plan = columns.build_plan("t", ["Enc", "patient_id", "MRN"], rows)
        self.assertEqual(plan["key_column"], "patient_id")
        self.assertIsNone(columns.build_plan("t", ["x"], [["hello world"]])["key_column"])

    def test_overrides_win_and_are_marked(self):
        plan = columns.build_plan("t", ["Zebra"], [["abc"], ["def"]], {"Zebra": "NAME"})
        c = plan["columns"][0]
        self.assertEqual((c["type"], c["decided_by"], c["action"]), ("NAME", "set by hand", "replace"))

    def test_unknown_columns_are_withheld_by_default(self):
        plan = columns.build_plan("t", ["Zebra", "Age"], [["abc", "30"], ["def", "40"]])
        self.assertEqual([c["action"] for c in plan["columns"]], ["withhold", "age"])


PATIENTS = [["patient_id", "full_name", "dob", "phone", "age", "state", "notes_free"],
            ["P1", "Reyes, Kim", "1980-03-02", "312-555-0100", "44", "IL", "Spoke with Kim Reyes about the plan."],
            ["P2", "Frost, Ada", "1931-07-04", "312-555-0101", "93", "IA", ""]]
ENCOUNTERS = [["enc", "patient_id", "admit", "discharge", "attending"],
              ["E1", "P1", "2025-01-10", "2025-01-14", "Dr. Reyes"],
              ["E2", "P1", "2025-03-01", "2025-03-05", "Dr. Okafor"],
              ["E3", "P2", "2025-02-01", "2025-02-03", "Dr. Okafor"]]


def clean_tables(**kw):
    tables = {"patients": (PATIENTS[0], PATIENTS[1:]), "encounters": (ENCOUNTERS[0], ENCOUNTERS[1:])}
    return deidentify_tables(tables, **kw)


class ApplyTests(unittest.TestCase):
    def test_dates_move_together_per_patient_across_tables(self):
        outputs, _, _, _ = clean_tables()
        from datetime import date
        d = lambda s: date.fromisoformat(s)
        (_, p_rows), (_, e_rows) = outputs["patients"], outputs["encounters"]
        shift = lambda a, b: (d(a) - d(b)).days
        s1 = shift(e_rows[0][2], "2025-01-10")
        self.assertEqual(shift(e_rows[0][3], "2025-01-14"), s1)
        self.assertEqual(shift(e_rows[1][2], "2025-03-01"), s1)                     # the patient's other encounter
        self.assertEqual(shift(p_rows[0][2], "1980-03-02"), s1)                     # and the birth date in the other table
        self.assertNotEqual(s1, shift(e_rows[2][2], "2025-02-01"))                 # a different patient moves differently
        self.assertTrue(30 <= abs(s1) <= 365)

    def test_keys_and_names_are_the_same_in_every_table(self):
        outputs, _, _, _ = clean_tables()
        (_, p_rows), (_, e_rows) = outputs["patients"], outputs["encounters"]
        self.assertEqual(p_rows[0][0], e_rows[0][1])
        self.assertEqual(e_rows[0][1], e_rows[1][1])
        self.assertNotEqual(p_rows[0][0], "P1")
        self.assertEqual(p_rows[0][0][0].isalpha(), True)
        # "Dr. Reyes" and "Reyes, Kim" share a surname, so they share its surrogate
        self.assertEqual(e_rows[0][4].split()[-1], p_rows[0][1].split(",")[0])
        self.assertTrue(e_rows[0][4].startswith("Dr. "))

    def test_ages_90_and_over_are_aggregated_and_empty_cells_stay_empty(self):
        outputs, _, report, _ = clean_tables()
        rows = outputs["patients"][1]
        self.assertEqual([r[4] for r in rows], ["44", "90+"])
        self.assertEqual(rows[1][-1] if False else report["tables"]["patients"]["per_column"]["notes_free"]["empty"], 1)

    def test_free_text_is_masked_and_flagged_unless_a_cleaner_is_given(self):
        outputs, changes, _, _ = clean_tables()
        self.assertEqual(outputs["patients"][1][0][-1], FREETEXT_MASK)
        self.assertTrue(any(c["rule"] == "freetext-withheld" and c["flagged"] for c in changes))
        outputs, _, _, _ = clean_tables(clean_text=lambda value, key: (value.replace("Kim Reyes", "X"), False))
        self.assertEqual(outputs["patients"][1][0][-1], "Spoke with X about the plan.")

    def test_unknown_column_policies(self):
        tables = {"t": (["Zebra", "patient_id"], [["** 7 **", "P1"], ["## 9 ##", "P2"]])}
        out, _, report, _ = deidentify_tables(tables)
        self.assertEqual(out["t"][0], ["patient_id"])
        self.assertEqual(report["tables"]["t"]["columns_withheld"], ["Zebra"])
        out, _, _, _ = deidentify_tables(tables, unknown="mask")
        self.assertEqual([r[0] for r in out["t"][1]], [WITHHELD_MASK] * 2)
        out, _, _, _ = deidentify_tables(tables, unknown="keep")
        self.assertEqual([r[0] for r in out["t"][1]], ["** 7 **", "## 9 ##"])
        with self.assertRaises(ValueError):
            TableDeidentifier(0, unknown="shrug")

    def test_street_structure_and_an_unparseable_date_is_flagged_not_guessed(self):
        td = TableDeidentifier(0)
        out, rule, flagged = td.cell("STREET", "7837 Ridge Blvd, Apt 4B", "k")
        self.assertEqual((rule, flagged), ("street-structured", False))
        self.assertTrue(out.endswith("Blvd, Apt " + out.split("Apt ")[1]) and "7837" not in out and "Ridge" not in out)
        self.assertEqual(td.cell("STREET", "somewhere over the hill", "k"), ("[ADDRESS]", "fallback-tag", True))
        self.assertEqual(td.cell("DATE", "7/7//2025", "k"), ("[DATE]", "fallback-tag", True))
        self.assertEqual(td.cell("AGE", "unknown", "k"), ("[AGE]", "fallback-tag", True))

    def test_inputs_are_not_modified(self):
        before = json.dumps([PATIENTS, ENCOUNTERS])
        clean_tables()
        self.assertEqual(json.dumps([PATIENTS, ENCOUNTERS]), before)

    def test_a_table_without_a_key_still_keeps_a_rows_own_dates_together(self):
        tables = {"t": (["admit", "discharge"], [["2025-01-10", "2025-01-14"]])}
        out, _, _, _ = deidentify_tables(tables)
        from datetime import date
        a, b = (date.fromisoformat(x) for x in out["t"][1][0])
        self.assertEqual((b - a).days, 4)


class SyntheticTableTests(unittest.TestCase):
    def test_generator_is_deterministic_and_has_the_planned_features(self):
        p1, e1, c1 = synth.make_tables(5, 30)
        p2, e2, c2 = synth.make_tables(5, 30)
        self.assertEqual((p1, e1, c1), (p2, e2, c2))
        self.assertGreaterEqual(sum(int(r["age"]) >= 90 for r in p1), 3)
        self.assertTrue({r["patient_id"] for r in e1} <= {r["patient_id"] for r in p1})
        self.assertTrue(all(re.search(r"555-01\d\d", r["phone"]) for r in p1))
        self.assertTrue(any(c.get("inside_text") for c in c1))

    def test_truth_covers_every_column_in_every_style(self):
        with tempfile.TemporaryDirectory() as tmp:
            p, e, _ = synth.make_tables(5, 10)
            for style in synth.STYLES:
                truth = synth.write_style(tmp, style, p, e)
                for t, meta in truth.items():
                    header, rows = read_table(Path(tmp) / meta["file"])
                    self.assertEqual(len(meta["order"]), len(rows[0]))
                    self.assertEqual(header is not None, meta["has_header"])


class CheckTests(unittest.TestCase):
    def test_no_leaks_broken_links_or_changed_stays_in_any_style(self):
        for style in synth.STYLES:
            r = evaluate_style(style, 20, 11)
            self.assertEqual(r["leaks"]["still_present_somewhere"], 0, style)
            self.assertEqual(r["consistency"]["rows_whose_links_broke"], 0, style)
            self.assertEqual(r["dates"]["patients_with_more_than_one_shift"], 0, style)
            self.assertEqual(r["dates"]["stays_changed"], 0, style)
            self.assertEqual(r["typing"]["identifier_columns_kept_as_is"], 0, style)
            self.assertEqual(r["utility"]["safe_cells_changed"], 0, style)

    def test_clean_headers_are_all_placed(self):
        r = evaluate_style("clean", 20, 11)
        self.assertEqual((r["typing"]["right"], r["typing"]["unplaced"], r["typing"]["wrong_type"]), (24, 0, 0))
        self.assertEqual(r["utility"]["ages_wrong"], 0)


class RunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        write_table(self.dir / "patients.csv", PATIENTS[0], PATIENTS[1:])
        write_table(self.dir / "encounters.csv", ENCOUNTERS[0], ENCOUNTERS[1:])
        self.argv = ["--in", str(self.dir / "patients.csv"), str(self.dir / "encounters.csv"), "--out-dir", str(self.dir / "out")]

    def run_cli(self, *extra):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = run_main(self.argv + list(extra))
        return code, out.getvalue()

    def test_full_run_writes_tables_and_audit_files(self):
        code, out = self.run_cli()
        self.assertEqual(code, 0)
        out_dir = self.dir / "out"
        for name in ("patients.csv", "encounters.csv", "changes.jsonl", "key.json", "plan.json", "report.json"):
            self.assertTrue((out_dir / name).exists(), name)
        header, rows = read_table(out_dir / "patients.csv")
        self.assertEqual(header[0], "patient_id")
        self.assertNotIn("Kim Reyes", (out_dir / "patients.csv").read_text(encoding="utf-8"))
        self.assertNotIn("1980-03-02", (out_dir / "encounters.csv").read_text(encoding="utf-8"))
        self.assertIn("do not share", out)
        self.assertNotIn("Reyes", (out_dir / "report.json").read_text(encoding="utf-8"))      # the report holds no values

    def test_plan_only_writes_just_the_plan_and_an_edited_plan_is_obeyed(self):
        self.run_cli("--plan-only")
        out_dir = self.dir / "out"
        self.assertTrue((out_dir / "plan.json").exists())
        self.assertFalse((out_dir / "patients.csv").exists())
        plan = json.loads((out_dir / "plan.json").read_text(encoding="utf-8"))
        for c in plan["plans"]["patients"]["columns"]:
            if c["column"] == "state":
                c["type"] = "TOWN"                       # deliberately change the treatment of one column
        (self.dir / "edited.json").write_text(json.dumps(plan), encoding="utf-8")
        self.run_cli("--plan", str(self.dir / "edited.json"))
        _, rows = read_table(out_dir / "patients.csv")
        self.assertNotEqual(rows[0][5], "IL")            # now treated as a town and replaced
        bad = json.loads(json.dumps(plan))
        bad["plans"]["patients"]["columns"][0]["type"] = "WIZARD"
        (self.dir / "bad.json").write_text(json.dumps(bad), encoding="utf-8")
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self.run_cli("--plan", str(self.dir / "bad.json"))

    def test_header_detection(self):
        write_table(self.dir / "nohead.csv", None, [["E1", "P1", "100"], ["E2", "P1", "100"]])   # short codes and numbers are data
        self.assertIsNone(read_table(self.dir / "nohead.csv")[0])
        self.assertIsNotNone(read_table(self.dir / "patients.csv")[0])
        self.assertIsNone(read_table(self.dir / "patients.csv", "no")[0])

    def test_free_text_cleaner_uses_the_detector_and_fails_closed(self):
        from deid.tables import run as run_module

        class Model:
            model, params, max_output_tokens = "m", {"max_tokens": 1}, 100

            def __init__(self, reply):
                self.reply = reply

            def complete(self, messages):
                return self.reply

        good = Completion(json.dumps({"identifiers": [{"text": "Kim Reyes", "type": "NAME", "confidence": 0.9}]}),
                          {"prompt_tokens": 5, "completion_tokens": 5}, 0.1, "stop")
        cut = Completion("", {}, 0.1, "length")
        args = mock.Mock(max_total_tokens=1000, cache_dir=str(self.dir))
        box = [None]
        for n, (reply, expect_masked) in enumerate(((good, False), (cut, True))):
            args.cache_dir = str(self.dir / f"cache{n}")        # a fresh cache, or the first reply would be reused
            with mock.patch("deid.detect.client.ChatClient.from_env", return_value=Model(reply)):
                clean = run_module.freetext_cleaner(args, box)
            tables = {"patients": (PATIENTS[0], PATIENTS[1:])}
            _, _, _, td = deidentify_tables(tables)
            box[0] = td
            text, flagged = clean("Spoke with Kim Reyes about the plan.", "P1")
            if expect_masked:
                self.assertEqual((text, flagged), (FREETEXT_MASK, True))
            else:
                self.assertNotIn("Kim Reyes", text)


from deid.tables import risk  # noqa: E402


def rows_of(*groups):
    """groups: (count, age, zip, sex) -> rows [key, age, zip, sex]"""
    out = []
    for count, age, zip_code, sex in groups:
        out += [[f"K{len(out) + i:04d}", str(age), zip_code, sex] for i in range(count)]
    return out


HEADER = ["patient_id", "age", "zip", "sex"]
TYPES = {"patient_id": "KEY", "age": "AGE", "zip": "ZIP", "sex": "SAFE"}


def one_table(rows, k=5, override=None):
    return risk.analyse({"t": {"header": HEADER, "rows": rows, "types": TYPES, "key": "patient_id"}}, k, override)["views"][0]


class RiskTests(unittest.TestCase):
    ROWS = rows_of((10, 40, "55501", "F"), (3, 41, "55501", "F"), (1, "90+", "55502", "M"), (6, 49, "55503", "F"))

    def test_planted_small_groups_are_found_exactly(self):
        view = one_table(self.ROWS)
        self.assertEqual(view["quasi_identifiers"], ["age", "zip", "sex"])      # the key is not a quasi-identifier
        self.assertEqual((view["rows_total"], view["rows_below_k"], view["rows_unique"], view["smallest_group"]), (20, 4, 1, 1))
        flagged = {r["row"]: r["group_size"] for r in view["flagged_rows"]}
        self.assertEqual(flagged, {10: 3, 11: 3, 12: 3, 13: 1})
        self.assertEqual(view["flagged_rows"][-1]["key"], "K0013")
        self.assertEqual(view["flagged_rows"][-1]["quasi_identifiers"], {"age": "90+", "zip": "55502", "sex": "M"})

    def test_k_changes_the_answer(self):
        self.assertEqual(one_table(self.ROWS, k=2)["rows_below_k"], 1)
        self.assertEqual(one_table(self.ROWS, k=7)["rows_below_k"], 4 + 6)
        self.assertEqual(one_table(self.ROWS, k=1)["rows_below_k"], 0)

    def test_generalizing_age_and_zip_merges_groups(self):
        view = one_table(self.ROWS)
        # ages 40 and 41 share the 40-49 band and the same ZIP prefix, and so does 49 with ZIP 555**: all of F merge
        after = view["after_generalizing"]
        self.assertEqual(after["rows_below_k"], 1)                     # only the lone 90+ / 555** / M row remains
        self.assertIn("ZIP to its first 3 digits", after["generalized"].values())

    def test_riskiest_column_sets_and_rare_values(self):
        view = one_table(self.ROWS)
        top = view["riskiest_column_sets"][0]
        self.assertEqual(top["rows_in_groups_below_k"], 4)
        self.assertEqual(view["rare_values_by_column"]["age"]["rows"], 4)
        self.assertIn("90+", view["rare_values_by_column"]["age"]["examples"])

    def test_empty_quasi_identifier_rows_are_not_flagged_and_override_works(self):
        rows = self.ROWS + [["K9999", "", "", ""]]
        self.assertEqual(one_table(rows)["rows_below_k"], 4)
        view = one_table(self.ROWS, override=["sex"])
        self.assertEqual(view["quasi_identifiers"], ["sex"])
        self.assertEqual(view["rows_below_k"], 1)                      # only the single M

    def test_a_table_with_nothing_to_group_on_says_so(self):
        view = risk.analyse({"t": {"header": ["a"], "rows": [["x"]], "types": {"a": "NAME"}, "key": None}})["views"][0]
        self.assertIn("no quasi-identifier columns", view["note"])

    def test_joined_view_combines_tables_on_the_key(self):
        tables = {
            "patients": {"header": HEADER, "rows": rows_of((6, 40, "55501", "F"), (1, 71, "55502", "M")),
                         "types": TYPES, "key": "patient_id"},
            "visits": {"header": ["visit", "patient_id", "dx"],
                       "rows": [["V1", "K0000", "A"], ["V2", "K0001", "A"], ["V3", "K0002", "A"], ["V4", "K0003", "A"],
                                ["V5", "K0004", "A"], ["V6", "K0005", "A"], ["V7", "K0006", "RARE"]],
                       "types": {"visit": "ID", "patient_id": "KEY", "dx": "SAFE"}, "key": "patient_id"}}
        report = risk.analyse(tables, k=5)
        names = [v["view"] for v in report["views"]]
        self.assertEqual(names, ["patients", "visits", "visits joined to patients"])
        joined = report["views"][2]
        self.assertEqual(joined["rows_total"], 7)
        self.assertEqual(joined["rows_below_k"], 1)                    # the rare diagnosis on the one 71-year-old
        self.assertEqual(joined["flagged_rows"][0]["quasi_identifiers"]["visits.dx"], "RARE")

    def test_report_files_hold_cleaned_values_only_and_no_row_detail_in_the_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = risk.analyse({"t": {"header": HEADER, "rows": self.ROWS, "types": TYPES, "key": "patient_id"}})
            risk.write_report(report, tmp)
            data = json.loads((Path(tmp) / "risk.json").read_text(encoding="utf-8"))
            self.assertNotIn("flagged_rows", data["views"][0])
            lines = (Path(tmp) / "risk-rows.csv").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1 + 4)
            self.assertIn("55502", lines[-1])
        self.assertIn("4 of 20 rows in groups under 5", risk.summary_line(report))

    def test_the_standalone_command_and_the_run_integration(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            write_table(tmp / "patients.csv", PATIENTS[0], PATIENTS[1:])
            write_table(tmp / "encounters.csv", ENCOUNTERS[0], ENCOUNTERS[1:])
            argv = ["--in", str(tmp / "patients.csv"), str(tmp / "encounters.csv"), "--out-dir", str(tmp / "out")]
            with contextlib.redirect_stdout(io.StringIO()) as out:
                run_main(argv)
            self.assertIn("small groups", out.getvalue())
            self.assertTrue((tmp / "out" / "risk.json").exists())
            self.assertTrue((tmp / "out" / "risk-rows.csv").exists())
            with contextlib.redirect_stdout(io.StringIO()):
                run_main(argv[:-1] + [str(tmp / "out2"), "--no-risk"])
            self.assertFalse((tmp / "out2" / "risk.json").exists())
            with contextlib.redirect_stdout(io.StringIO()) as out:
                risk.main(["--in", str(tmp / "out" / "patients.csv"), str(tmp / "out" / "encounters.csv"),
                           "--plan", str(tmp / "out" / "plan.json"), "--k", "3", "--out-dir", str(tmp / "again")])
            self.assertIn("rows in groups under 3", out.getvalue())
            self.assertTrue((tmp / "again" / "risk.json").exists())


if __name__ == "__main__":
    unittest.main()
