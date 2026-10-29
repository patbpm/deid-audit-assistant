"""Watch mode: notes that arrive, change and disappear, held until reviewed. Scripted model; plumbing, not accuracy."""

import contextlib
import io
import json
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from deid.app.backend import Backend
from deid.detect.client import ApiError, Completion
from deid.review.decisions import Store
from deid.watch.__main__ import main as watch_main
from deid.watch.sources import FolderSource, SqliteSource, clean_id, parse_source
from deid.watch.watcher import Watcher

NOTE_A = "Patient: Kim Reyes\nSeen 4/25/25 by Dr. Wu.\nMRN: 7788991\nCall 555-0142.\n"
NOTE_B = "Follow-up for Kim Reyes on 5/30/25.\nMRN: 7788991\n"


def items_for(text, date_confidence=0.95):
    found = []
    for string, kind, conf in (("Kim Reyes", "NAME", 0.95), ("Wu", "NAME", 0.95), ("4/25/25", "DATE", date_confidence),
                               ("5/30/25", "DATE", date_confidence), ("7788991", "ID", 0.95), ("555-0142", "PHONE", 0.95)):
        if string in text:
            found.append({"text": string, "type": kind, "confidence": conf})
    return found


class Client:
    """Detects by looking strings up in the note; the verifier answers `verdict`; the reviewer finds nothing."""
    model, params = "scripted", {"max_tokens": 1}

    def __init__(self, date_confidence=0.95, verdict="identifier", fail=None, garble=False):
        self.date_confidence, self.verdict, self.fail, self.garble = date_confidence, verdict, fail, garble
        self.detect_calls = 0

    def complete(self, messages):
        system, usage = messages[0]["content"], {"prompt_tokens": 50, "completion_tokens": 10}
        if "find personal identifiers" in system:
            self.detect_calls += 1
            if self.fail:
                raise ApiError(self.fail)
            if self.garble:
                return Completion("sorry", usage, 0.0, "stop")
            text = messages[1]["content"].split("<<<\n", 1)[1].rsplit("\n>>>", 1)[0]
            return Completion(json.dumps({"identifiers": items_for(text, self.date_confidence)}), usage, 0.0, "stop")
        if "double-check candidate" in system:
            import re
            ids = [int(i) for i in re.findall(r"^(\d+)\. type=", messages[1]["content"], re.M)]
            return Completion(json.dumps({"verdicts": [{"id": i, "decision": self.verdict, "why": "scripted"} for i in ids]}),
                              usage, 0.0, "stop")
        return Completion(json.dumps({"risk": "low", "clues": []}), usage, 0.0, "stop")


class WatchTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.feed, self.state = Path(self.tmp.name) / "feed", Path(self.tmp.name) / "state"
        self.feed.mkdir()
        self.clock = [1_000_000.0]

    def write(self, name, text):
        path = self.feed / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        os.utime(path, (self.clock[0] - 100, self.clock[0] - 100))      # old enough to be settled
        return path

    def edit(self, path, text):
        path.write_text(text, encoding="utf-8")
        os.utime(path, (self.clock[0] - 100, self.clock[0] - 100))

    def watcher(self, client=None, token_cap=1_000_000):
        client = client or Client()
        backend = Backend("scripted", "Scripted model", False, lambda: client)
        self.client = client
        return Watcher(FolderSource(self.feed), backend, self.state, token_cap=token_cap, log=lambda *a: None,
                       now=lambda: self.clock[0])

    def released(self, note_id):
        path = self.state / "released" / f"{note_id}.txt"
        return path.read_text(encoding="utf-8") if path.exists() else None

    def status(self, w, note_id):
        return w.state["notes"][note_id]["status"]

    def decisions(self):
        return json.loads((self.state / "audit.decisions.json").read_text(encoding="utf-8"))


class FlowTests(WatchTestCase):
    def test_a_new_note_is_cleaned_and_released_when_nothing_needs_review(self):
        self.write("P1__N1.txt", NOTE_A)
        w = self.watcher()
        self.assertEqual(w.step()["new"], 1)
        text = self.released("P1__N1")
        self.assertEqual(self.status(w, "P1__N1"), "released")
        for original in ("Kim Reyes", "Wu", "7788991", "555-0142", "4/25/25"):
            self.assertNotIn(original, text)
        self.assertIn("MRN:", text)

    def test_a_note_with_something_to_review_is_held_until_it_is_decided(self):
        self.write("P1__N1.txt", NOTE_A)
        w = self.watcher(Client(date_confidence=0.5, verdict="unsure"))
        w.step()
        self.assertEqual(self.status(w, "P1__N1"), "pending")
        self.assertIsNone(self.released("P1__N1"))
        store = Store(self.state / "audit.json", "pat")
        audit = store.notes["P1__N1"]
        index = next(i for i, r in enumerate(audit["review"]) if r["kind"] == "span")
        store.apply("P1__N1", {"op": "entry", "id": audit["review"][index]["ref"], "decision": "accept"})
        w.step()
        self.assertEqual(self.status(w, "P1__N1"), "released")
        self.assertIsNotNone(self.released("P1__N1"))

    def test_an_edited_note_is_cleaned_again_its_old_copy_withdrawn_and_its_decisions_dropped(self):
        path = self.write("P1__N1.txt", NOTE_A)
        w = self.watcher(Client(date_confidence=0.5, verdict="unsure"))
        w.step()
        store = Store(self.state / "audit.json", "pat")
        ref = next(r["ref"] for r in store.notes["P1__N1"]["review"] if r["kind"] == "span")
        store.apply("P1__N1", {"op": "entry", "id": ref, "decision": "accept"})
        w.step()
        old = self.released("P1__N1")
        self.assertIsNotNone(old)
        self.edit(path, NOTE_A.replace("4/25/25", "5/30/25"))
        counts = w.step()
        self.assertEqual(counts["changed"], 1)
        self.assertEqual(w.state["notes"]["P1__N1"]["version"], 2)
        self.assertEqual(self.status(w, "P1__N1"), "pending")
        self.assertIsNone(self.released("P1__N1"))                                  # the old copy is gone
        self.assertEqual(self.decisions()["notes"].get("P1__N1"), None)             # and so is the old decision

    def test_an_unchanged_note_is_not_sent_to_the_model_again(self):
        self.write("P1__N1.txt", NOTE_A)
        w = self.watcher()
        w.step()
        calls = self.client.detect_calls
        self.assertEqual(w.step(), {"new": 0, "changed": 0, "removed": 0, "retried": 0})
        self.assertEqual(self.client.detect_calls, calls)

    def test_a_removed_note_leaves_nothing_behind(self):
        path = self.write("P1__N1.txt", NOTE_A)
        self.write("P2__N2.txt", NOTE_B)
        w = self.watcher()
        w.step()
        path.unlink()
        self.assertEqual(w.step()["removed"], 1)
        self.assertNotIn("P1__N1", w.state["notes"])
        self.assertIsNone(self.released("P1__N1"))
        self.assertFalse((self.state / "audits" / "P1__N1.json").exists())
        self.assertNotIn("P1__N1", [n["note_id"] for n in json.loads((self.state / "audit.json").read_text(encoding="utf-8"))["notes"]])
        self.assertIsNotNone(self.released("P2__N2"))

    def test_a_file_still_being_written_is_not_read_and_does_not_look_like_a_deletion(self):
        path = self.write("P1__N1.txt", NOTE_A)
        w = self.watcher()
        w.step()
        os.utime(path, (self.clock[0], self.clock[0]))                  # touched right now
        import deid.watch.sources as sources
        real = sources.time.time
        sources.time.time = lambda: self.clock[0]
        try:
            self.assertEqual(w.step()["removed"], 0)
        finally:
            sources.time.time = real
        self.assertIn("P1__N1", w.state["notes"])


class MappingTests(WatchTestCase):
    def stand_in(self, text):
        return text.split("Patient: ")[1].split("\n")[0] if "Patient: " in text else text.split("Follow-up for ")[1].split(" on")[0]

    def test_one_patient_gets_the_same_stand_ins_in_notes_that_arrive_later_and_after_a_restart(self):
        self.write("P1__N1.txt", NOTE_A)
        w = self.watcher()
        w.step()
        first = self.released("P1__N1")
        self.write("P1__N2.txt", NOTE_B)
        w = self.watcher()                                              # a fresh process, same state folder
        w.step()
        second = self.released("P1__N2")
        self.assertEqual(self.stand_in(first), self.stand_in(second))
        self.assertEqual(first.split("MRN: ")[1].split("\n")[0], second.split("MRN: ")[1].split("\n")[0])
        self.assertNotIn("Kim Reyes", second)

    def test_the_secret_seed_is_kept_in_the_state_folder_and_differs_between_folders(self):
        self.write("P1__N1.txt", NOTE_A)
        self.watcher().step()
        first = json.loads((self.state / "mapping.json").read_text(encoding="utf-8"))["seed"]
        self.state = Path(self.tmp.name) / "state2"
        self.watcher().step()
        self.assertNotEqual(first, json.loads((self.state / "mapping.json").read_text(encoding="utf-8"))["seed"])


class FailureTests(WatchTestCase):
    def test_a_note_that_could_not_be_cleaned_is_never_released(self):
        self.write("P1__N1.txt", NOTE_A)
        w = self.watcher(Client(garble=True))
        w.step()
        self.assertEqual(self.status(w, "P1__N1"), "failed")
        self.assertIsNone(self.released("P1__N1"))
        self.assertIn("NOT CLEANED", json.dumps(json.loads((self.state / "audit.json").read_text(encoding="utf-8"))))

    def test_a_model_error_is_retried_a_few_times_then_waits_for_the_note_to_change(self):
        path = self.write("P1__N1.txt", NOTE_A)
        w = self.watcher(Client(fail="rate limited"))
        for _ in range(6):
            w.step()
        self.assertEqual(self.client.detect_calls, 3)
        self.assertEqual(self.status(w, "P1__N1"), "error")
        self.assertIsNone(self.released("P1__N1"))
        w.backend.chat = lambda: Client()
        w.client = Client()
        self.edit(path, NOTE_A + "Extra line.\n")
        w.step()
        self.assertEqual(self.status(w, "P1__N1"), "released")

    def test_the_token_cap_pauses_and_a_later_run_with_more_room_goes_on(self):
        for i in range(4):
            self.write(f"P{i}__N{i}.txt", NOTE_A)
        w = self.watcher(token_cap=100)
        w.step()
        self.assertTrue(w.paused)
        self.assertTrue(any(n["status"] == "queued" for n in w.state["notes"].values()) or len(w.state["notes"]) < 4)
        w2 = self.watcher(token_cap=1_000_000)
        w2.step()
        w2.step()
        self.assertEqual({n["status"] for n in w2.state["notes"].values()}, {"released"})
        self.assertEqual(len(w2.state["notes"]), 4)


class StatusAndReviewTests(WatchTestCase):
    def test_the_status_page_lists_states_and_never_note_text(self):
        self.write("P1__N1.txt", NOTE_A)
        w = self.watcher()
        w.step()
        page = (self.state / "status.html").read_text(encoding="utf-8")
        self.assertIn("P1__N1", page)
        self.assertNotIn("Kim Reyes", page)
        from deid.watch.status import render_status
        hostile = {"notes": {"<script>x</script>": {"status": "error", "patient_id": "<i>", "version": 1, "error": "<b>bad</b>"}}}
        html = render_status(hostile, False, "<engine>", 0)
        self.assertNotIn("<script>x", html)
        self.assertNotIn("<b>bad", html)
        self.assertIn("&lt;script&gt;", html)

    def test_the_review_store_follows_the_rewritten_audit_and_keeps_decisions_for_unchanged_notes(self):
        self.write("P1__N1.txt", NOTE_A)
        w = self.watcher(Client(date_confidence=0.5, verdict="unsure"))
        w.step()
        store = Store(self.state / "audit.json", "pat")
        ref = next(r["ref"] for r in store.notes["P1__N1"]["review"] if r["kind"] == "span")
        store.apply("P1__N1", {"op": "entry", "id": ref, "decision": "accept"})
        self.assertFalse(store.refresh())
        self.write("P2__N2.txt", NOTE_B)
        w.step()
        self.assertTrue(store.refresh())
        self.assertEqual(set(store.notes), {"P1__N1", "P2__N2"})
        self.assertEqual(store.state["notes"]["P1__N1"]["entries"][ref]["decision"], "accept")
        store.apply("P2__N2", {"op": "item", "index": 0, "decision": "dismiss"}) if store.notes["P2__N2"]["review"][0]["kind"] != "span" else None

    def test_a_store_does_not_load_an_audit_whose_decisions_are_not_there_yet(self):
        self.write("P1__N1.txt", NOTE_A)
        w = self.watcher()
        w.step()
        store = Store(self.state / "audit.json", "pat")
        audit_path = self.state / "audit.json"
        data = json.loads(audit_path.read_text(encoding="utf-8"))
        data["summary"]["changes"] += 1
        audit_path.write_text(json.dumps(data), encoding="utf-8")        # new audit, decisions still under the old hash
        self.assertFalse(store.refresh())


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_folder_patients_come_from_the_folder_or_the_name_and_ids_are_safe(self):
        (self.root / "P7").mkdir()
        (self.root / "P7" / "visit one.txt").write_text("a", encoding="utf-8")
        (self.root / "P8__N9.txt").write_text("b", encoding="utf-8")
        (self.root / "lonely.txt").write_text("c", encoding="utf-8")
        (self.root / "ignored.pdf").write_text("d", encoding="utf-8")
        snap = FolderSource(self.root, settle=0).snapshot()
        self.assertEqual({k: v["patient_id"] for k, v in snap.items()}, {"P7__visit_one": "P7", "P8__N9": "P8", "lonely": "lonely"})

    def test_jsonl_lines_are_notes_the_last_one_wins_and_bad_lines_are_reported(self):
        (self.root / "n.jsonl").write_text(
            '{"note_id": "a", "patient_id": "p", "text": "one"}\n{"note_id": "a", "patient_id": "p", "text": "two"}\n'
            'not json\n{"note_id": "b"}\n', encoding="utf-8")
        source = FolderSource(self.root, settle=0)
        snap = source.snapshot()
        self.assertEqual(snap["a"]["text"], "two")
        self.assertEqual(len(source.skipped), 2)

    def test_sqlite_is_read_only_and_names_are_checked(self):
        db = self.root / "n.db"
        with contextlib.closing(sqlite3.connect(db)) as con:
            con.execute("create table notes (note_id text, patient_id text, text text)")
            con.execute("insert into notes values ('n1', 'p1', 'hello')")
            con.commit()
        source = SqliteSource(db, "notes")
        self.assertEqual(source.snapshot(), {"n1": {"patient_id": "p1", "text": "hello"}})
        with self.assertRaises(ValueError):
            SqliteSource(db, "notes; drop table notes")
        with contextlib.closing(sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)) as ro:
            with self.assertRaises(sqlite3.OperationalError):
                ro.execute("insert into notes values ('x', 'y', 'z')")

    def test_source_specs(self):
        self.assertIsInstance(parse_source(f"folder:{self.root}"), FolderSource)
        s = parse_source("sqlite:x.db#notes:id:body:who")
        self.assertEqual((s.table, s.id_col, s.text_col, s.patient_col), ("notes", "id", "body", "who"))
        for bad in ("folder:", "sqlite:x.db", "ftp:x"):
            with self.assertRaises(ValueError):
                parse_source(bad)
        self.assertEqual(clean_id("../../etc/passwd"), "etc_passwd")


class CommandTests(unittest.TestCase):
    def test_live_needs_the_synthetic_only_confirmation(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            watch_main(["--source", "folder:x", "--state", "y", "--live"])

    def test_the_offline_command_runs_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            feed = Path(tmp) / "feed"
            feed.mkdir()
            note = feed / "P1__N1.txt"
            note.write_text("Patient: Kim Reyes\nSeen 4/25/25.\n", encoding="utf-8")
            os.utime(note, (time.time() - 100, time.time() - 100))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(watch_main(["--source", f"folder:{feed}", "--state", str(Path(tmp) / "s"), "--once"]), 0)
            self.assertTrue((Path(tmp) / "s" / "status.html").exists())
            self.assertTrue((Path(tmp) / "s" / "mapping.json").exists())


if __name__ == "__main__":
    unittest.main()


class FeedTests(WatchTestCase):
    def test_the_demo_feed_adds_edits_and_deletes_and_the_watcher_follows_it(self):
        from deid.synth import generate
        from deid.watch.feed import feed
        notes = generate.generate_notes(5, 8)[:8]
        w = self.watcher(Client())
        seen = []

        def pause(_):
            for f in self.feed.glob("*.txt"):
                os.utime(f, (self.clock[0] - 100, self.clock[0] - 100))
            seen.append(w.step())
        feed(notes, self.feed, 8, 0, log=lambda *a: None, sleep=pause)
        self.assertEqual(sum(c["new"] for c in seen), 8)
        self.assertEqual(sum(c["changed"] for c in seen), 1)
        self.assertEqual(sum(c["removed"] for c in seen), 1)
        self.assertEqual(len(w.state["notes"]), 7)


class OfflineEngineTests(WatchTestCase):
    def test_a_note_cleaned_without_a_second_reader_is_always_held_for_a_person(self):
        self.write("P1__N1.txt", NOTE_A)
        client = Client()
        backend = Backend("scripted", "Rules only", False, lambda: client, verify=False, redteam=False)
        w = Watcher(FolderSource(self.feed), backend, self.state, log=lambda *a: None, now=lambda: self.clock[0])
        w.step()
        self.assertEqual(self.status(w, "P1__N1"), "pending")
        self.assertIsNone(self.released("P1__N1"))
        store = Store(self.state / "audit.json", "pat")
        notice = [i for i, r in enumerate(store.notes["P1__N1"]["review"]) if r["kind"] == "notice"]
        self.assertEqual(len(notice), 1)
        store.apply("P1__N1", {"op": "item", "index": notice[0], "decision": "dismiss"})
        for i, r in enumerate(store.notes["P1__N1"]["review"]):
            if r["kind"] == "span":
                store.apply("P1__N1", {"op": "entry", "id": r["ref"], "decision": "accept"})
        w.step()
        self.assertEqual(self.status(w, "P1__N1"), "released")
