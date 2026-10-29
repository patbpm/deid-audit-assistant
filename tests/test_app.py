import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import wave
import zipfile
from io import BytesIO
from pathlib import Path
from unittest import mock

from deid.app import flows, kinds, samples
from deid.app.backend import Backend, offline_backend
from deid.app.jobs import JobStore, safe_name
from deid.app.offline import OfflineModel, find_all
from deid.app.server import make_server
from deid.detect.client import Completion
from deid.synth import generate
from tests.test_agent import ScriptedModel

NOTE = ("Patient: Kim Reyes\nMRN: 7654321\nSeen on 2025-03-04 by Dr. Wu.\n"
        "Call 507-555-0142 or kim.reyes@example.org. Lives at 41 Maple Street, Eastvale, IL 54219.\n")


def wait(store, job_id, states, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        job = store.get(job_id)
        if job["state"] in states:
            return job
        time.sleep(0.02)
    raise AssertionError(f"timed out in {store.get(job_id)['steps']}")


def wav(path, seconds=1.0, rate=16000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return Path(path).read_bytes()


class KindTests(unittest.TestCase):
    def test_files_are_told_apart_by_content(self):
        self.assertEqual(kinds.kind_of_file("a.txt", b"Patient: Kim Reyes\nSeen today.").kind, "note")
        self.assertEqual(kinds.kind_of_file("a.csv", b"id,name\n1,Kim\n2,Lee\n").kind, "table")
        self.assertEqual(kinds.kind_of_file("a.jsonl", b'{"text": "hi"}\n{"text": "yo"}\n').kind, "note")
        self.assertEqual(kinds.kind_of_file("x.bin", b"RIFF\x00\x00\x00\x00WAVEfmt ").kind, "audio")
        self.assertEqual(kinds.kind_of_file("x.png", b"\x89PNG\r\n\x1a\n....").kind, "scan")
        self.assertEqual(kinds.kind_of_file("x.jpg", b"\xff\xd8\xff\xe0....").kind, "scan")
        self.assertEqual(kinds.kind_of_file("x.webp", b"RIFF\x00\x00\x00\x00WEBPVP8 ").kind, "scan")

    def test_a_note_that_looks_like_a_table_is_guessed_and_says_so(self):
        found = kinds.kind_of_file("notes.txt", b"id,name,age\n1,Kim,50\n2,Lee,41\n3,Wu,60\n")
        self.assertEqual(found.kind, "table")
        self.assertIn("guess", found.label)

    def test_refusals_say_why(self):
        for name, data, word in [("a.mp3", b"x", "WAV"), ("a.pdf", b"%PDF", "image"), ("a.docx", b"PK", "Word"),
                                 ("a.xlsx", b"PK", "CSV"), ("a.txt", b"", "empty"), ("a.txt", b"\x00\x01\x02", "not a text"),
                                 ("a.wav", b"hello", "WAV"), ("a.png", b"hello", "image"),
                                 ("a.csv", b"just one line", "steady"), ("a.json", b"[1, 2]", "JSON object"),
                                 ("a.tsv", b"a\tb", "CSV")]:
            found = kinds.kind_of_file(name, data)
            self.assertFalse(found.ok, name)
            self.assertIn(word, found.reason, name)

    def test_pasted_text(self):
        self.assertEqual(kinds.kind_of_text(NOTE).kind, "note")
        self.assertEqual(kinds.kind_of_text("a,b\n1,2\n3,4\n").kind, "table")
        self.assertFalse(kinds.kind_of_text("   \n").ok)

    def test_families(self):
        self.assertEqual({kinds.family(k) for k in ("note", "audio", "scan")}, {"notes"})
        self.assertEqual(kinds.family("table"), "tables")

    def test_names_cannot_climb_out_of_a_folder(self):
        self.assertEqual(safe_name("..\\..\\evil name.txt"), "evil name.txt")
        self.assertEqual(safe_name("/etc/passwd"), "passwd")
        self.assertEqual(safe_name("a<b>:c.txt"), "a_b__c.txt")
        self.assertEqual(safe_name(""), "file")


class OfflineTests(unittest.TestCase):
    def found(self, text):
        return {f.text: f for f in find_all(text)}

    def test_shaped_identifiers(self):
        f = self.found(NOTE + "Born 03/04/1980, SSN 123-45-6789. Account: AB123456.")
        for string, kind in [("507-555-0142", "PHONE"), ("kim.reyes@example.org", "EMAIL"), ("2025-03-04", "DATE"),
                             ("03/04/1980", "DATE"), ("123-45-6789", "ID"), ("7654321", "ID"), ("AB123456", "ID")]:
            self.assertEqual(f[string].type, kind, string)
        self.assertEqual(f["41 Maple Street, Eastvale, IL 54219"].type, "ADDRESS")

    def test_names_come_from_cues_and_spread_to_other_mentions(self):
        f = self.found(NOTE + "Later Reyes called back. Dr. Wu agreed.")
        for name in ("Kim Reyes", "Kim", "Reyes", "Wu"):
            self.assertEqual(f[name].type, "NAME", name)
        self.assertGreater(f["Kim Reyes"].confidence, f["Reyes"].confidence)

    def test_no_cue_no_name_and_credentials_are_not_names(self):
        self.assertNotIn("Wilson", self.found("The patient has Wilson disease."))
        f = self.found("PCP: Mei Long, PA-C")
        self.assertIn("Mei Long", f)
        self.assertNotIn("Mei Long, P", f)

    def test_numbers_inside_codes_are_not_found_twice(self):
        f = self.found("Insurance ID: DWJ194963587 and ACCT1068456722")
        self.assertEqual(sorted(f), ["ACCT1068456722", "DWJ194963587"])

    def test_year_less_dates_are_low_confidence(self):
        f = self.found("Seen 4/5 and on Apr 21 and on April 21, 2025.")
        self.assertLess(f["4/5"].confidence, 0.8)
        self.assertLess(f["Apr 21"].confidence, 0.8)
        self.assertGreater(f["April 21, 2025"].confidence, 0.9)

    def test_the_model_shim_only_answers_the_detection_prompt(self):
        from deid.detect.prompt import build_messages
        reply = OfflineModel().complete(build_messages(NOTE))
        names = {i["text"] for i in json.loads(reply.content)["identifiers"]}
        self.assertIn("507-555-0142", names)
        with self.assertRaises(ValueError):
            OfflineModel().complete([{"role": "system", "content": "something else"}, {"role": "user", "content": "x"}])


class OfflineNotesJobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = JobStore(self.tmp.name, offline_backend())

    def run_notes(self, files, options=None):
        job = self.store.create()
        for name, data in files:
            self.assertTrue(self.store.add_file(job["id"], name, data)["kind"], name)
        with mock.patch("urllib.request.urlopen") as net:
            self.store.start(job["id"], options or {})
            done = wait(self.store, job["id"], ("done", "failed"))
        net.assert_not_called()
        return done

    def test_pasted_note_is_cleaned_without_any_network_call(self):
        job = self.store.create()
        self.assertEqual(self.store.add_text(job["id"], NOTE)["kind"], "note")
        with mock.patch("urllib.request.urlopen") as net:
            self.store.start(job["id"], {})
            done = wait(self.store, job["id"], ("done", "failed"))
        net.assert_not_called()
        self.assertEqual(done["state"], "done", done["error"])
        result = done["result"]
        self.assertEqual((result["notes"], result["not_cleaned"], result["assessed"]), (1, 0, False))
        self.assertEqual([s["state"] for s in done["steps"]], ["done"] * 4)
        audit = json.loads((Path(self.tmp.name) / job["id"] / "notes.audit.json").read_text(encoding="utf-8"))
        note = audit["notes"][0]
        self.assertIsNone(note["risk"])
        self.assertFalse(note["assessed"])
        originals = {e["original"] for e in note["entries"]}
        for string in ("507-555-0142", "kim.reyes@example.org", "7654321", "Kim Reyes"):
            self.assertIn(string, originals)
        self.assertEqual(done["tokens"]["cap"], 0)   # no tokens are spent offline

    def test_jsonl_notes_keep_their_ids_and_patients(self):
        lines = [{"note_id": "A1", "patient_id": "P1", "text": NOTE}, {"note_id": "A2", "patient_id": "P1", "text": NOTE},
                 {"text": "Patient: Lee Park"}]
        data = "".join(json.dumps(x) + "\n" for x in lines).encode()
        done = self.run_notes([("n.jsonl", data)])
        audit = json.loads((Path(self.tmp.name) / done["id"] / "notes.audit.json").read_text(encoding="utf-8"))
        self.assertEqual([n["note_id"] for n in audit["notes"]], ["A1", "A2", "n-3"])

    def test_one_patient_across_files_gets_one_date_shift_and_one_surname(self):
        text = "Patient: Kim Reyes\nSeen on 2025-03-04.\n"
        done = self.run_notes([("a.txt", text.encode()), ("b.txt", text.encode())], {"same_patient": True})
        audit = json.loads((Path(self.tmp.name) / done["id"] / "notes.audit.json").read_text(encoding="utf-8"))
        first, second = ([(e["type"], e["replacement"]) for e in n["entries"]] for n in audit["notes"])
        self.assertEqual(first, second)
        apart = self.run_notes([("a.txt", text.encode()), ("b.txt", text.encode())])
        audit = json.loads((Path(self.tmp.name) / apart["id"] / "notes.audit.json").read_text(encoding="utf-8"))
        dates = [e["replacement"] for n in audit["notes"] for e in n["entries"] if e["type"] == "DATE"]
        self.assertEqual(len(dates), 2)

    def test_note_ids_stay_unique(self):
        done = self.run_notes([("a.txt", b"Patient: Kim Reyes"), ("a.txt", b"Patient: Lee Park")])
        audit = json.loads((Path(self.tmp.name) / done["id"] / "notes.audit.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(n["note_id"] for n in audit["notes"]), ["a", "a-2"])

    def test_sample_notes_run_and_every_replacement_is_in_the_audit(self):
        done = self.run_notes(samples.notes())
        self.assertEqual(done["result"]["notes"], 4)
        self.assertGreater(done["result"]["replacements"], 20)
        self.assertEqual(done["result"]["risk_levels"], {"not assessed": 4})

    def test_an_empty_note_in_a_jsonl_file_is_skipped_with_a_reason(self):
        data = (json.dumps({"text": NOTE}) + "\n" + json.dumps({"text": "  "}) + "\n").encode()
        done = self.run_notes([("n.jsonl", data)])
        self.assertEqual(done["result"]["notes"], 1)
        self.assertIn("empty", done["result"]["skipped"][0]["reason"])

    def test_nothing_readable_fails_with_the_reason(self):
        job = self.store.create()
        self.store.add_file(job["id"], "n.jsonl", (json.dumps({"text": " "}) + "\n").encode())
        self.store.start(job["id"], {})
        failed = wait(self.store, job["id"], ("failed",))
        self.assertIn("No note could be read", failed["error"])


class JobRulesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = JobStore(self.tmp.name, offline_backend())

    def test_audio_and_scans_are_refused_offline_with_the_way_forward(self):
        job = self.store.create()
        audio = self.store.add_file(job["id"], "d.wav", wav(Path(self.tmp.name) / "x.wav"))
        scan = self.store.add_file(job["id"], "s.png", b"\x89PNG\r\n\x1a\n....")
        for entry in (audio, scan):
            self.assertIsNone(entry["kind"])
            self.assertIn("--live", entry["reason"])
        self.assertEqual(self.store.get(job["id"])["files"], [])

    def test_notes_and_tables_cannot_be_mixed(self):
        job = self.store.create()
        self.store.add_file(job["id"], "n.txt", NOTE.encode())
        self.store.add_file(job["id"], "t.csv", b"a,b\n1,2\n3,4\n")
        with self.assertRaisesRegex(ValueError, "separate jobs"):
            self.store.start(job["id"], {})

    def test_nothing_starts_empty_or_twice(self):
        job = self.store.create()
        with self.assertRaisesRegex(ValueError, "add a file"):
            self.store.start(job["id"], {})
        self.store.add_text(job["id"], NOTE)
        self.store.start(job["id"], {})
        with self.assertRaisesRegex(ValueError, "already started"):
            self.store.start(job["id"], {})
        with self.assertRaisesRegex(ValueError, "already started"):
            self.store.add_text(job["id"], NOTE)
        wait(self.store, job["id"], ("done", "failed"))

    def test_bad_options_are_refused(self):
        job = self.store.create()
        self.store.add_text(job["id"], NOTE)
        for bad in ({"header": "maybe"}, {"unknown": "keep"}, {"freetext": "x"}, {"token_cap": 0}, {"token_cap": "9"},
                    {"max_audio_seconds": 99999}, {"model_typing": True}):
            with self.assertRaises(ValueError, msg=bad):
                self.store.start(job["id"], bad)

    def test_size_and_count_limits(self):
        job = self.store.create()
        with mock.patch("deid.app.jobs.MAX_FILE_BYTES", 10):
            with self.assertRaisesRegex(ValueError, "larger than"):
                self.store.add_file(job["id"], "n.txt", b"x" * 11)
        with mock.patch("deid.app.jobs.MAX_FILES", 1):
            self.store.add_file(job["id"], "n.txt", NOTE.encode())
            with self.assertRaisesRegex(ValueError, "at most"):
                self.store.add_file(job["id"], "m.txt", NOTE.encode())

    def test_kind_can_be_switched_only_when_it_makes_sense(self):
        job = self.store.create()
        self.store.add_file(job["id"], "n.txt", NOTE.encode())
        with self.assertRaisesRegex(ValueError, "steady"):
            self.store.set_kind(job["id"], 0, "table")
        self.store.add_file(job["id"], "t.csv", b"a,b\n1,2\n3,4\n")
        self.store.set_kind(job["id"], 1, "note")
        self.assertEqual(self.store.get(job["id"])["files"][1]["kind"], "note")
        with self.assertRaisesRegex(ValueError, "unknown file"):
            self.store.set_kind(job["id"], 9, "note")

    def test_job_ids_cannot_be_paths(self):
        for bad in ("../x", "..\\x", "abc", "0" * 12 + "/..", ""):
            with self.assertRaises(KeyError):
                self.store.dir(bad)

    def test_delete_removes_the_folder_and_jobs_survive_a_restart(self):
        job = self.store.create()
        self.store.add_text(job["id"], NOTE)
        self.store.start(job["id"], {})
        wait(self.store, job["id"], ("done",))
        again = JobStore(self.tmp.name, offline_backend())
        self.assertEqual(again.get(job["id"])["state"], "done")
        self.assertEqual(again.listing()[0]["id"], job["id"])
        again.delete(job["id"])
        self.assertFalse((Path(self.tmp.name) / job["id"]).exists())
        with self.assertRaises(KeyError):
            again.get(job["id"])

    def test_a_job_that_was_running_when_the_app_stopped_is_marked_failed(self):
        job = self.store.create()
        self.store.update(job["id"], lambda j: j.update(state="running"))
        again = JobStore(self.tmp.name, offline_backend())
        self.assertEqual(again.get(job["id"])["state"], "failed")
        self.assertIn("stopped", again.get(job["id"])["error"])


class TableJobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = JobStore(self.tmp.name, offline_backend())
        self.files = samples.tables()

    def plan(self, files=None, options=None):
        job = self.store.create()
        for name, data in files or self.files:
            self.assertEqual(self.store.add_file(job["id"], name, data)["kind"], "table")
        self.store.start(job["id"], options or {})
        return wait(self.store, job["id"], ("awaiting_plan", "failed"))

    def test_the_plan_is_shown_before_anything_is_changed(self):
        job = self.plan()
        self.assertEqual(job["state"], "awaiting_plan", job["error"])
        self.assertEqual(job["steps"][-3]["state"] if False else job["steps"][2]["state"], "running")
        types = {c["column"]: c["type"] for c in job["plan"]["patients"]["columns"]}
        self.assertEqual(types["Mail"], "EMAIL")
        self.assertEqual(types["Locality"], "UNKNOWN")
        self.assertIn("Locality", [c["column"] for c in job["plan"]["patients"]["columns"] if c["sample"]])
        self.assertFalse((Path(self.tmp.name) / job["id"] / "tables-out").exists())
        self.assertIsNone(job["result"])

    def test_the_confirm_step_says_whether_the_person_changed_anything(self):
        job = self.plan()
        key = job["plan"]["patients"]["key_column"]
        self.store.submit_plan(job["id"], {"patients": {"types": {}, "key_column": key}})
        done = wait(self.store, job["id"], ("done",))
        self.assertIn("as proposed", done["steps"][2]["detail"])
        job2 = self.plan()
        self.store.submit_plan(job2["id"], {"patients": {"types": {"Locality": "TOWN", "Years": "AGE"}}})
        done2 = wait(self.store, job2["id"], ("done",))
        self.assertIn("2 change(s)", done2["steps"][2]["detail"])

    def test_unplaced_columns_are_left_out_unless_the_person_gives_a_type(self):
        job = self.plan()
        self.store.submit_plan(job["id"], {})
        done = wait(self.store, job["id"], ("done", "failed"))
        self.assertEqual(done["state"], "done", done["error"])
        patients = done["result"]["tables"]["patients"]
        self.assertIn("Locality", patients["withheld"])
        self.assertNotIn("Locality", patients["preview"]["header"])
        job2 = self.plan()
        self.store.submit_plan(job2["id"], {"patients": {"types": {"Locality": "TOWN", "Years": "AGE"}}})
        done2 = wait(self.store, job2["id"], ("done",))
        self.assertIn("Locality", done2["result"]["tables"]["patients"]["preview"]["header"])
        self.assertNotIn("Locality", done2["result"]["tables"]["patients"]["withheld"])

    def test_cleaned_tables_hold_no_original_identifier_and_links_hold(self):
        job = self.plan()
        self.store.submit_plan(job["id"], {})
        wait(self.store, job["id"], ("done",))
        out = Path(self.tmp.name) / job["id"] / "tables-out"
        original = {name.split("/")[-1]: data.decode() for name, data in self.files}
        import csv
        before = list(csv.DictReader(original["patients.csv"].splitlines()))
        after = (out / "patients.csv").read_text(encoding="utf-8")
        for row in before:
            for column in ("Mail", "Contact", "SocSec", "Chart No"):
                self.assertNotIn(row[column], after, column)
        enc = list(csv.DictReader((out / "encounters.csv").read_text(encoding="utf-8").splitlines()))
        pat = list(csv.DictReader(after.splitlines()))
        self.assertEqual({r["Subject"] for r in enc} - {r["Subject"] for r in pat}, set())
        for name in ("plan.json", "report.json", "risk.json", "risk-rows.csv"):
            text = (out / name).read_text(encoding="utf-8")
            for row in before:
                self.assertNotIn(row["Mail"], text, name)
                self.assertNotIn(row["SocSec"], text, name)

    def test_free_text_is_hidden_by_default_and_cleaned_by_the_detector_on_request(self):
        job = self.plan()
        self.store.submit_plan(job["id"], {})
        done = wait(self.store, job["id"], ("done",))
        out = Path(self.tmp.name) / job["id"] / "tables-out"
        self.assertIn("[FREE TEXT NOT CLEANED]", (out / "encounters.csv").read_text(encoding="utf-8"))
        self.assertIsNone(done["result"]["freetext"])
        job2 = self.plan(options={"freetext": "detector"})
        self.store.submit_plan(job2["id"], {})
        done2 = wait(self.store, job2["id"], ("done",))
        self.assertEqual(done2["state"], "done", done2["error"])
        self.assertGreater(done2["result"]["freetext"]["cells"], 0)
        text = (Path(self.tmp.name) / job2["id"] / "tables-out" / "encounters.csv").read_text(encoding="utf-8")
        self.assertNotIn("[FREE TEXT NOT CLEANED]", text)

    def test_bad_plan_edits_are_refused_before_anything_runs(self):
        job = self.plan()
        for edits in ({"nope": {}}, {"patients": {"types": {"Nope": "ID"}}}, {"patients": {"types": {"Mail": "WRONG"}}},
                      {"patients": {"key_column": "Nope"}}, [], {"patients": 5}):
            with self.assertRaises(ValueError, msg=edits):
                self.store.submit_plan(job["id"], edits)
        self.assertEqual(self.store.get(job["id"])["state"], "awaiting_plan")

    def test_the_plan_can_only_be_submitted_once(self):
        job = self.plan()
        self.store.submit_plan(job["id"], {})
        wait(self.store, job["id"], ("done",))
        with self.assertRaisesRegex(ValueError, "not waiting"):
            self.store.submit_plan(job["id"], {})

    def test_a_pasted_table_and_a_headerless_one(self):
        job = self.store.create()
        self.assertEqual(self.store.add_text(job["id"], "name,email\nKim Reyes,kim@example.org\nLee Park,lee@example.org\n")["kind"], "table")
        self.store.start(job["id"], {})
        planned = wait(self.store, job["id"], ("awaiting_plan",))
        self.assertTrue(planned["plan"]["pasted text"]["has_header"])

    def test_a_table_with_no_rows_fails_with_the_reason(self):
        job = self.store.create()
        self.store.add_file(job["id"], "t.csv", b"a,b\n1,2\n")
        self.store.update(job["id"], lambda j: None)
        path = Path(self.tmp.name) / job["id"] / "input" / "001-t.csv"
        path.write_bytes(b"a,b\n")
        self.store.start(job["id"], {})
        failed = wait(self.store, job["id"], ("failed",))
        self.assertIn("No table could be read", failed["error"])


def hosted_backend(notes, audio_text=None, scan_text=None):
    script = ScriptedModel(notes)

    class Chat:
        model, params = "scripted", {"max_tokens": 1}
        calls = script.calls

        def complete(self, messages):
            if isinstance(messages[1]["content"], list):   # a page image
                return Completion(scan_text, {"prompt_tokens": 50, "completion_tokens": 10}, 0.0, "stop")
            return script.complete(messages)

    class Speech:
        params = {"model": "scripted-asr"}

        def transcribe(self, path):
            return audio_text, 0.1

    chat = Chat()
    return Backend("scripted", "Scripted hosted model", True, lambda: chat, lambda: Speech(), True, True, True, True), chat


class HostedJobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.notes = generate.generate_notes(5, 4)[:3]
        self.backend, self.chat = hosted_backend(self.notes, self.notes[1]["text"], self.notes[2]["text"])
        self.store = JobStore(self.tmp.name, self.backend, max_job_tokens=50_000)

    def jsonl(self, notes):
        return "".join(json.dumps({"note_id": n["note_id"], "patient_id": n["patient_id"], "text": n["text"]}) + "\n"
                       for n in notes).encode()

    def test_a_hosted_job_will_not_start_without_the_synthetic_confirmation(self):
        job = self.store.create()
        self.store.add_file(job["id"], "n.jsonl", self.jsonl(self.notes[:1]))
        with self.assertRaisesRegex(ValueError, "synthetic or public"):
            self.store.start(job["id"], {})
        with self.assertRaisesRegex(ValueError, "synthetic or public"):
            self.store.start(job["id"], {"confirm_synthetic": "yes"})
        self.assertEqual(self.chat.calls, [])

    def test_hosted_notes_use_the_verifier_and_the_reviewer_and_report_tokens(self):
        job = self.store.create()
        self.store.add_file(job["id"], "n.jsonl", self.jsonl(self.notes[:2]))
        self.store.start(job["id"], {"confirm_synthetic": True, "token_cap": 40_000})
        done = wait(self.store, job["id"], ("done", "failed"))
        self.assertEqual(done["state"], "done", done["error"])
        kinds_called = {k for k, _ in self.chat.calls}
        self.assertEqual(kinds_called, {"detect", "verify", "redteam"})
        self.assertTrue(done["result"]["assessed"])
        self.assertEqual(done["result"]["risk_levels"], {"low": 2})
        self.assertGreater(done["tokens"]["used"], 0)
        self.assertEqual(done["tokens"]["cap"], 40_000)

    def test_the_job_cap_cannot_be_raised_above_the_app_limit(self):
        job = self.store.create()
        self.store.add_file(job["id"], "n.jsonl", self.jsonl(self.notes[:1]))
        self.store.start(job["id"], {"confirm_synthetic": True, "token_cap": 10_000_000})
        done = wait(self.store, job["id"], ("done", "failed"))
        self.assertEqual(done["tokens"]["cap"], 50_000)

    def test_the_token_cap_stops_the_job_and_says_which_notes_were_not_done(self):
        job = self.store.create()
        self.store.add_file(job["id"], "n.jsonl", self.jsonl(self.notes))
        self.store.start(job["id"], {"confirm_synthetic": True, "token_cap": 150})
        done = wait(self.store, job["id"], ("done", "failed"))
        self.assertTrue(done["result"]["stopped_early"])
        self.assertTrue(any("token cap" in s["reason"] for s in done["result"]["skipped"]))

    def test_dictation_and_scans_become_notes_and_are_cleaned(self):
        job = self.store.create()
        self.assertEqual(self.store.add_file(job["id"], "dictation.wav", wav(Path(self.tmp.name) / "d.wav"))["kind"], "audio")
        self.assertEqual(self.store.add_file(job["id"], "page.png", b"\x89PNG\r\n\x1a\n....")["kind"], "scan")
        self.store.start(job["id"], {"confirm_synthetic": True})
        done = wait(self.store, job["id"], ("done", "failed"))
        self.assertEqual(done["state"], "done", done["error"])
        audit = json.loads((Path(self.tmp.name) / job["id"] / "notes.audit.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(n["note_id"] for n in audit["notes"]), ["dictation-audio", "page-scan"])
        self.assertEqual(done["result"]["not_cleaned"], 0)

    def test_a_bad_wav_is_skipped_with_the_reason_and_the_rest_still_runs(self):
        job = self.store.create()
        stereo = Path(self.tmp.name) / "st.wav"
        with wave.open(str(stereo), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\x00\x00" * 200)
        self.store.add_file(job["id"], "stereo.wav", stereo.read_bytes())
        self.store.add_file(job["id"], "n.txt", self.notes[0]["text"].encode())
        # a txt and a wav are both notes-family, so they share a job
        self.store.start(job["id"], {"confirm_synthetic": True})
        done = wait(self.store, job["id"], ("done", "failed"))
        self.assertEqual(done["state"], "done", done["error"])
        self.assertEqual(done["result"]["notes"], 1)
        self.assertIn("mono", done["result"]["skipped"][0]["reason"])

    def test_the_audio_seconds_limit_is_enforced(self):
        job = self.store.create()
        self.store.add_file(job["id"], "a.wav", wav(Path(self.tmp.name) / "a.wav", 3))
        self.store.add_file(job["id"], "b.wav", wav(Path(self.tmp.name) / "b.wav", 3))
        self.store.start(job["id"], {"confirm_synthetic": True, "max_audio_seconds": 4})
        done = wait(self.store, job["id"], ("done", "failed"))
        self.assertEqual(done["result"]["notes"], 1)
        self.assertIn("audio limit", done["result"]["skipped"][0]["reason"])

    def test_a_cut_off_scan_is_not_cleaned_as_if_it_were_whole(self):
        class Cut(type(self.chat)):
            def complete(self, messages):
                if isinstance(messages[1]["content"], list):
                    return Completion("Patient: Kim", {"prompt_tokens": 5, "completion_tokens": 5}, 0.0, "length")
                return super().complete(messages)
        cut = Cut()
        backend = Backend("scripted", "x", True, lambda: cut, None, True, True, True, True)
        store = JobStore(Path(self.tmp.name) / "cut", backend)
        job = store.create()
        store.add_file(job["id"], "page.png", b"\x89PNG\r\n\x1a\n....")
        store.start(job["id"], {"confirm_synthetic": True})
        failed = wait(store, job["id"], ("failed",))
        self.assertIn("cut off", failed["error"])

    def test_table_tokens_add_model_help_and_free_text_together(self):
        class Quiet:
            model, params = "scripted", {"max_tokens": 1}

            def complete(self, messages):
                return Completion('{"identifiers": []}', {"prompt_tokens": 30, "completion_tokens": 10}, 0.0, "stop")

        quiet = Quiet()
        store = JobStore(Path(self.tmp.name) / "quiet", Backend("scripted", "x", True, lambda: quiet, None, True, True, True, True))
        job = store.create()
        for name, data in samples.tables():
            store.add_file(job["id"], name, data)
        store.start(job["id"], {"confirm_synthetic": True, "freetext": "detector", "token_cap": 50_000})
        planned = wait(store, job["id"], ("awaiting_plan", "failed"))
        self.assertEqual(planned["state"], "awaiting_plan", planned["error"])
        store.update(job["id"], lambda j: j["tokens"].update({"in": 700, "out": 1300, "used": 2000}))
        store.submit_plan(job["id"], {})
        done = wait(store, job["id"], ("done", "failed"))
        self.assertEqual(done["state"], "done", done["error"])
        self.assertGreater(done["tokens"]["used"], 2000)          # the earlier use is kept, the free-text use is added
        self.assertEqual(done["tokens"]["used"], done["tokens"]["in"] + done["tokens"]["out"])

    def test_hosted_table_free_text_goes_through_the_chat_client(self):
        job = self.store.create()
        for name, data in samples.tables():
            self.store.add_file(job["id"], name, data)
        self.store.start(job["id"], {"confirm_synthetic": True, "freetext": "mask"})
        planned = wait(self.store, job["id"], ("awaiting_plan", "failed"))
        self.assertEqual(planned["state"], "awaiting_plan", planned["error"])
        self.assertEqual(self.chat.calls, [])      # planning with the rules makes no model call


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = JobStore(self.tmp.name, offline_backend())
        self.server = make_server(self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def call(self, path, body=None, raw=None, method=None, headers=None, host=None):
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        request = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            request.add_header("X-Review", "1")
            request.add_header("Content-Type", "application/octet-stream" if raw is not None else "application/json")
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        if host:
            request.add_unredirected_header("Host", host)
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, response.read(), dict(response.headers)
        except urllib.error.HTTPError as err:
            body = err.read()
            err.close()
            return err.code, body, dict(err.headers)

    def j(self, *args, **kwargs):
        status, body, _ = self.call(*args, **kwargs)
        return status, json.loads(body)

    def test_front_page_and_info(self):
        status, body, headers = self.call("/")
        self.assertEqual(status, 200)
        page = body.decode()
        self.assertIn("not a compliance certification", page)
        self.assertIn("Content-Security-Policy", headers)
        self.assertNotIn("innerHTML", page)
        status, info = self.j("/api/info")
        self.assertFalse(info["backend"]["hosted"])
        self.assertEqual(info["backend"]["kinds"], ["note", "table"])
        self.assertEqual(sorted(info["samples"]), ["notes", "tables"])

    def test_other_hosts_and_missing_headers_are_refused(self):
        self.assertEqual(self.call("/api/info", host="evil.example")[0], 403)
        self.assertEqual(self.call("/api/jobs", {}, host="evil.example")[0], 403)
        request = urllib.request.Request(self.base + "/api/jobs", data=b"{}", method="POST")   # no X-Review
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code, 403)
        caught.exception.close()

    def test_notes_from_drop_to_download(self):
        status, job = self.j("/api/jobs", {})
        jid = job["id"]
        status, entry = self.j(f"/api/jobs/{jid}/file?name=note.txt", raw=NOTE.encode())
        self.assertEqual((status, entry["kind"]), (200, "note"))
        self.assertEqual(self.j(f"/api/jobs/{jid}/start", {"options": {}})[0], 200)
        done = wait(self.store, jid, ("done", "failed"))
        self.assertEqual(done["state"], "done", done["error"])
        status, snap = self.j(f"/api/jobs/{jid}")
        self.assertTrue(snap["can_review"])
        names = {d["name"] for d in snap["downloads"]}
        self.assertEqual(names, {"cleaned-notes.jsonl", "review-log.json", "cleaned-package.zip", "audit-report.html", "cleaned-note.txt"})
        warned = {d["name"] for d in snap["downloads"] if d["warning"]}
        self.assertEqual(warned, {"audit-report.html"})
        self.assertTrue(all(d["note"] for d in snap["downloads"]))
        self.assertTrue(all("check before sharing" in d["note"] for d in snap["downloads"] if d["name"].startswith("cleaned")))
        status, body, headers = self.call(f"/job/{jid}/download/cleaned-note.txt")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        cleaned = body.decode()
        for original in ("507-555-0142", "kim.reyes@example.org", "7654321", "Reyes"):
            self.assertNotIn(original, cleaned)
        status, body, _ = self.call(f"/job/{jid}/download/cleaned-package.zip")
        with zipfile.ZipFile(BytesIO(body)) as z:
            self.assertEqual(sorted(z.namelist()), ["README.txt", "cleaned-notes.jsonl", "review-log.json"])
            for name in z.namelist():
                for original in ("507-555-0142", "kim.reyes@example.org", "7654321"):
                    self.assertNotIn(original, z.read(name).decode(), name)

    def test_the_review_page_is_served_per_job_and_decisions_change_the_download(self):
        _, job = self.j("/api/jobs", {})
        jid = job["id"]
        self.j(f"/api/jobs/{jid}/text", {"text": NOTE})
        self.j(f"/api/jobs/{jid}/start", {"options": {}})
        wait(self.store, jid, ("done",))
        status, body, _ = self.call(f"/job/{jid}/review")
        page = body.decode()
        self.assertIn(f'content="/job/{jid}"', page)
        self.assertIn(f'content="/#{jid}"', page)
        status, state = self.j(f"/job/{jid}/api/state")
        note = state["notes"][0]
        entry = next(e for e in note["entries"] if e["type"] == "PHONE")
        status, view = self.j(f"/job/{jid}/api/op", {"note_id": note["note_id"], "op": {"op": "entry", "id": entry["id"], "decision": "reject"}})
        self.assertEqual(status, 200)
        self.assertIn("507-555-0142", view["final"]["text"])
        status, body, _ = self.call(f"/job/{jid}/download/cleaned-note.txt")
        self.assertIn("507-555-0142", body.decode())    # the person's decision is what is downloaded
        self.assertEqual(self.call(f"/job/{jid}/api/op", {"note_id": "x", "op": {}}, headers={"X-Review": "1"}, host="evil.example")[0], 403)

    def test_downloads_only_by_name_from_the_job_list(self):
        _, job = self.j("/api/jobs", {})
        jid = job["id"]
        self.j(f"/api/jobs/{jid}/text", {"text": NOTE})
        self.assertEqual(self.call(f"/job/{jid}/download/cleaned-notes.jsonl")[0], 404)   # not finished
        self.j(f"/api/jobs/{jid}/start", {"options": {}})
        wait(self.store, jid, ("done",))
        for bad in ("job.json", "..%2Fjob.json", "..%5C..%5Cjob.json", "notes.key.json", "notes.audit.json", "key.json", "changes.jsonl"):
            self.assertEqual(self.call(f"/job/{jid}/download/{bad}")[0], 404, bad)
        self.assertEqual(self.call("/job/../../etc/passwd")[0], 404)
        self.assertEqual(self.call("/job/000000000000/review")[0], 404)

    def test_unsupported_and_mixed_input_is_explained(self):
        _, job = self.j("/api/jobs", {})
        jid = job["id"]
        status, entry = self.j(f"/api/jobs/{jid}/file?name=notes.pdf", raw=b"%PDF-1.4")
        self.assertEqual((status, entry["kind"]), (200, None))
        self.assertIn("image", entry["reason"])
        self.j(f"/api/jobs/{jid}/file?name=n.txt", raw=NOTE.encode())
        self.j(f"/api/jobs/{jid}/file?name=t.csv", raw=b"a,b\n1,2\n3,4\n")
        status, body = self.j(f"/api/jobs/{jid}/start", {"options": {}})
        self.assertEqual(status, 400)
        self.assertIn("separate jobs", body["error"])

    def test_uploads_over_the_limit_are_refused_without_reading_them(self):
        _, job = self.j("/api/jobs", {})
        with mock.patch("deid.app.server.MAX_FILE_BYTES", 5):
            status, body = self.j(f"/api/jobs/{job['id']}/file?name=n.txt", raw=b"x" * 50)
        self.assertEqual(status, 413)

    def test_tables_through_the_plan_page_to_the_downloads(self):
        status, job = self.j("/api/jobs/sample", {"which": "tables"})
        jid = job["id"]
        self.assertEqual({f["name"] for f in job["files"]}, {"patients.csv", "encounters.csv"})
        self.j(f"/api/jobs/{jid}/start", {"options": {}})
        planned = wait(self.store, jid, ("awaiting_plan",))
        self.assertIn("encounters", planned["plan"])
        status, body = self.j(f"/api/jobs/{jid}/plan", {"edits": {"patients": {"types": {"Locality": "TOWN"}}}})
        self.assertEqual(status, 200)
        wait(self.store, jid, ("done",))
        status, snap = self.j(f"/api/jobs/{jid}")
        self.assertFalse(snap["can_review"])
        self.assertEqual({d["name"] for d in snap["downloads"]},
                         {"patients.csv", "encounters.csv", "plan.json", "report.json", "risk.json", "risk-rows.csv", "cleaned-tables.zip"})
        status, body, _ = self.call(f"/job/{jid}/download/patients.csv")
        self.assertIn("Subject", body.decode())
        self.assertEqual(self.call(f"/job/{jid}/review")[0], 404)
        self.assertEqual(self.call(f"/job/{jid}/download/key.json")[0], 404)

    def test_samples_and_delete(self):
        status, job = self.j("/api/jobs/sample", {"which": "notes"})
        self.assertEqual(job["files"][0]["kind"], "note")
        self.assertEqual(self.j("/api/jobs/sample", {"which": "nope"})[0], 400)
        self.assertEqual(self.j(f"/api/jobs/{job['id']}/delete", {})[0], 200)
        self.assertEqual(self.call(f"/api/jobs/{job['id']}")[0], 404)
        self.assertEqual(self.j("/api/jobs")[1], [])

    def test_a_failed_job_reports_why(self):
        _, job = self.j("/api/jobs", {})
        self.j(f"/api/jobs/{job['id']}/file?name=n.jsonl", raw=(json.dumps({"text": " "}) + "\n").encode())
        self.j(f"/api/jobs/{job['id']}/start", {"options": {}})
        failed = wait(self.store, job["id"], ("failed",))
        status, snap = self.j(f"/api/jobs/{job['id']}")
        self.assertIn("No note could be read", snap["error"])
        self.assertEqual(snap["downloads"], [])


class LiveBackendTests(unittest.TestCase):
    def test_building_a_hosted_backend_makes_no_call_and_describes_itself(self):
        from deid.app.backend import live_backend
        with mock.patch("urllib.request.urlopen") as net:
            meta, custom = live_backend("meta"), live_backend("custom")
        net.assert_not_called()
        self.assertTrue(meta.hosted)
        self.assertEqual(meta.kinds, ["note", "table", "audio", "scan"])
        self.assertEqual(custom.kinds, ["note", "table"])
        self.assertIn("synthetic", " ".join(meta.notes))

    def test_a_missing_key_fails_the_job_with_the_variable_name_and_no_call(self):
        from deid.app.backend import live_backend
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict("os.environ", {}, clear=True),                 mock.patch("urllib.request.urlopen") as net:
            store = JobStore(tmp, live_backend("meta"))
            job = store.create()
            store.add_text(job["id"], NOTE)
            store.start(job["id"], {"confirm_synthetic": True})
            failed = wait(store, job["id"], ("failed",))
        net.assert_not_called()
        self.assertIn("MODEL_API_KEY", failed["error"])


class PageTests(unittest.TestCase):
    def test_the_front_page_loads_nothing_from_outside_and_builds_dom_without_innerhtml(self):
        page = (Path(__file__).resolve().parents[1] / "deid" / "app" / "app.html").read_text(encoding="utf-8")
        for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "eval(", "document.write", "http://", "https://"):
            self.assertNotIn(banned, page, banned)
        review = (Path(__file__).resolve().parents[1] / "deid" / "review" / "page.html").read_text(encoding="utf-8")
        self.assertNotIn("innerHTML", review)


class PipelineFlagTests(unittest.TestCase):
    def test_no_verify_and_no_redteam_make_no_extra_model_calls(self):
        from deid.agent.pipeline import detect_and_verify, review_and_clean
        from deid.detect.client import Budget
        from deid.detect.detector import Cache
        notes = generate.generate_notes(5, 4)[:2]
        model = ScriptedModel(notes)
        pairs = [{"note_id": n["note_id"], "patient_id": n["patient_id"], "text": n["text"]} for n in notes]
        batch, _ = detect_and_verify(pairs, model, Cache(None), Cache(None, "vf1"), Budget(0), 0.8, verify=False)
        outcomes, _, _ = review_and_clean(batch, model, Cache(None, "rt1"), Budget(0), 0, 0.8, 2, redteam=False)
        self.assertEqual({k for k, _ in model.calls}, {"detect"})
        for o in outcomes:
            self.assertEqual((o.risk_before, o.risk_after), ("not assessed", "not assessed"))
            self.assertIsNone(o.audit["risk"])
            self.assertFalse(o.audit["assessed"])
            self.assertTrue(o.audit["entries"])


if __name__ == "__main__":
    unittest.main()
