import json
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from deid.review import decisions
from deid.review.decisions import Store, apply_decisions, empty_note, record
from deid.review.server import PAGE, make_server

TEXT = "Patient: Kim Reyes seen 4/5/25. Works as the only blacksmith in town. Call 555-0100."


def entry(i, start, end, kind, original, replacement, status="accept"):
    return {"id": f"N1:{i}", "type": kind, "start": start, "end": end, "original": original,
            "replacement": replacement, "rule": "x", "detector": "m", "confidence": 0.5,
            "also_found_by": [], "verifier": None, "checks": {"decision": status, "reasons": []}, "status": status}


def make_note():
    i = TEXT.index("blacksmith")
    return {
        "note_id": "N1", "text": TEXT, "risk": "medium", "assessed": True,
        "entries": [entry(0, 9, 18, "NAME", "Kim Reyes", "Ada Frost", "review"),
                    entry(1, 24, 28, "DATE", "4/5/", "9/9/", "review")],
        "review": [
            {"kind": "span", "ref": "N1:0", "reasons": ["low confidence"]},
            {"kind": "span", "ref": "N1:1", "reasons": ["month-first"]},
            {"kind": "clue", "ref": None, "category": "OCCUPATION", "text": "only blacksmith",
             "ranges": [[i - 9, i + 6]], "reasons": ["rare"]},
            {"kind": "unmatched", "ref": None, "reasons": ["not found"]},
        ]}


def clock():
    return "2026-10-29T12:00:00+00:00"


class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.note = make_note()
        self.state = empty_note()

    def do(self, **op):
        self.state = record(self.note, self.state, op, "pat", clock)
        return apply_decisions(self.note, self.state)

    def test_undecided_stays_replaced(self):
        final = apply_decisions(self.note, self.state)
        self.assertIn("Ada Frost", final["text"])
        self.assertNotIn("Kim Reyes", final["text"])
        self.assertEqual((final["review_items"], final["decided"], final["undecided"]), (4, 0, 4))

    def test_accept_keeps_and_reject_restores(self):
        self.assertIn("Ada Frost", self.do(op="entry", id="N1:0", decision="accept")["text"])
        final = self.do(op="entry", id="N1:0", decision="reject")
        self.assertIn("Kim Reyes", final["text"])
        self.assertEqual(final["counts"]["restored"], 1)
        self.assertIn("Ada Frost", self.do(op="entry", id="N1:0", decision="clear")["text"])

    def test_clue_redaction_and_dismissal(self):
        final = self.do(op="item", index=2, decision="redact")
        self.assertIn("[REDACTED]", final["text"])
        self.assertNotIn("only blacksmith", final["text"])
        final = self.do(op="item", index=3, decision="dismiss")
        self.assertEqual(final["decided"], 2)

    def test_marks_point_at_the_final_text(self):
        self.do(op="entry", id="N1:0", decision="reject")
        final = self.do(op="item", index=2, decision="redact")
        for m in final["marks"]:
            self.assertTrue(final["text"][m["start"]:m["end"]])
        kinds = {m["kind"]: final["text"][m["start"]:m["end"]] for m in final["marks"]}
        self.assertEqual(kinds["restored"], "Kim Reyes")
        self.assertEqual(kinds["redacted"], "[REDACTED]")

    def test_manual_redaction_uses_a_tag_and_can_be_removed(self):
        a = TEXT.index("555-0100")
        final = self.do(op="manual-add", start=a, end=a + 8, type="PHONE")
        self.assertIn("[PHONE]", final["text"])
        self.assertNotIn("555-0100", final["text"])
        final = self.do(op="manual-remove", id=self.state["manual"][0]["id"])
        self.assertIn("555-0100", final["text"])

    def test_invalid_actions_change_nothing(self):
        before = json.dumps(self.state, sort_keys=True)
        bad = [dict(op="entry", id="nope", decision="accept"),
               dict(op="entry", id="N1:0", decision="maybe"),
               dict(op="item", index=0, decision="dismiss"),        # span items use accept/reject
               dict(op="item", index=3, decision="redact"),         # unmatched cannot be redacted
               dict(op="item", index=99, decision="dismiss"),
               dict(op="item", index=True, decision="dismiss"),
               dict(op="manual-add", start=5, end=5, type="NAME"),
               dict(op="manual-add", start=0, end=10_000, type="NAME"),
               dict(op="manual-add", start="1", end=3, type="NAME"),
               dict(op="manual-add", start=0, end=3, type="PERSON"),
               dict(op="manual-remove", id="N1:m9"),
               dict(op="sneaky")]
        for op in bad:
            with self.assertRaises(ValueError, msg=str(op)):
                record(self.note, self.state, op, "pat", clock)
        self.assertEqual(json.dumps(self.state, sort_keys=True), before)

    def test_overlapping_edits_are_refused(self):
        with self.assertRaises(ValueError):
            record(self.note, self.state, dict(op="manual-add", start=9, end=14, type="NAME"), "pat", clock)
        i = TEXT.index("blacksmith")
        self.do(op="manual-add", start=i, end=i + 5, type="OTHER")
        with self.assertRaises(ValueError):
            record(self.note, self.state, dict(op="item", index=2, decision="redact"), "pat", clock)

    def test_decisions_record_who_and_when(self):
        self.do(op="entry", id="N1:0", decision="accept")
        self.assertEqual(self.state["entries"]["N1:0"], {"decision": "accept", "by": "pat", "at": clock()})


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.audit = Path(self.tmp.name) / "run.audit.json"
        self.audit.write_text(json.dumps({"summary": {}, "notes": [make_note()]}), encoding="utf-8")

    def test_decisions_survive_a_restart_and_the_audit_is_untouched(self):
        before = self.audit.read_bytes()
        store = Store(self.audit, "pat", clock)
        store.apply("N1", dict(op="entry", id="N1:0", decision="reject"))
        again = Store(self.audit, "pat", clock)
        self.assertEqual(again.view("N1")["state"]["entries"]["N1:0"]["decision"], "reject")
        self.assertEqual(self.audit.read_bytes(), before)
        self.assertTrue(store.path.name.endswith("run.audit.decisions.json"))

    def test_decisions_for_a_different_audit_file_are_refused(self):
        Store(self.audit, "pat", clock).apply("N1", dict(op="entry", id="N1:0", decision="accept"))
        data = json.loads(self.audit.read_text(encoding="utf-8"))
        data["notes"][0]["risk"] = "high"
        self.audit.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(ValueError):
            Store(self.audit, "pat", clock)

    def test_unknown_note_is_refused(self):
        with self.assertRaises(ValueError):
            Store(self.audit, "pat", clock).apply("N9", dict(op="entry", id="N1:0", decision="accept"))

    def test_export_writes_reviewed_notes_and_a_log(self):
        store = Store(self.audit, "pat", clock)
        store.apply("N1", dict(op="entry", id="N1:0", decision="reject"))
        store.apply("N1", dict(op="item", index=3, decision="dismiss"))
        summary = store.export()
        self.assertEqual((summary["rejected"], summary["dismissed"], summary["undecided"]), (1, 1, 2))
        self.assertEqual(summary["notes_fully_reviewed"], 0)
        notes = [json.loads(line) for line in (Path(self.tmp.name) / "run.reviewed.notes.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertIn("Kim Reyes", notes[0]["text"])
        log = json.loads((Path(self.tmp.name) / "run.review-log.json").read_text(encoding="utf-8"))
        self.assertEqual(log["summary"]["audit_sha256"], store.sha)


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        audit = Path(self.tmp.name) / "run.audit.json"
        audit.write_text(json.dumps({"summary": {"notes": 1}, "notes": [make_note()]}), encoding="utf-8")
        self.server = make_server(Store(audit, "pat", clock), 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"

    def call(self, path, body=None, headers=None):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data, headers=headers or {})
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, response.read(), dict(response.headers)
        except urllib.error.HTTPError as error:
            self.addCleanup(error.close)
            return error.code, error.read(), dict(error.headers)

    def test_listens_on_localhost_only(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_page_and_state(self):
        status, body, headers = self.call("/")
        self.assertEqual(status, 200)
        self.assertIn(b"De-identification review", body)
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        status, body, _ = self.call("/api/state")
        state = json.loads(body)
        self.assertEqual(state["notes"][0]["note_id"], "N1")
        self.assertIn("N1", state["views"])

    def test_change_requires_the_custom_header(self):
        status, _, _ = self.call("/api/op", {"note_id": "N1", "op": {"op": "entry", "id": "N1:0", "decision": "reject"}})
        self.assertEqual(status, 403)
        status, body, _ = self.call("/api/op", {"note_id": "N1", "op": {"op": "entry", "id": "N1:0", "decision": "reject"}},
                                    {"X-Review": "1", "Content-Type": "application/json"})
        self.assertEqual(status, 200)
        self.assertIn("Kim Reyes", json.loads(body)["final"]["text"])

    def test_wrong_host_header_is_refused(self):
        status, _, _ = self.call("/api/state", headers={"Host": "evil.example"})
        self.assertEqual(status, 403)

    def test_bad_input_is_a_400_not_a_crash(self):
        headers = {"X-Review": "1"}
        status, body, _ = self.call("/api/op", {"note_id": "N1", "op": {"op": "entry", "id": "zzz", "decision": "accept"}}, headers)
        self.assertEqual(status, 400)
        status, _, _ = self.call("/api/op", {"note_id": "N9", "op": {"op": "entry", "id": "N1:0", "decision": "accept"}}, headers)
        self.assertEqual(status, 400)
        status, _, _ = self.call("/api/op", {"note_id": "N1", "op": "nope"}, headers)
        self.assertEqual(status, 404)

    def test_export_endpoint(self):
        status, body, _ = self.call("/api/export", {}, {"X-Review": "1"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["notes"], 1)


class PageTests(unittest.TestCase):
    def test_page_never_builds_markup_from_note_text(self):
        page = PAGE.read_text(encoding="utf-8")
        for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
            self.assertNotIn(banned, page)

    def test_page_loads_nothing_from_outside(self):
        page = PAGE.read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"(src|href)=[\"']?https?://", page))
        self.assertNotIn("@import", page)


if __name__ == "__main__":
    unittest.main()
