import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from deid.agent import verifier
from deid.agent.pipeline import detect_and_verify, review_and_clean
from deid.agent.run import main as run_main
from deid.agent.verifier import parse_verdicts, select_uncertain, verify_spans
from deid.audit.build import apply_verdict
from deid.detect.client import Budget, Completion
from deid.detect.detector import Cache, ParseError
from deid.synth import generate


def kind_of(messages):
    system = messages[0]["content"]
    if "find personal identifiers" in system:
        return "detect"
    if "double-check candidate" in system:
        return "verify"
    return "redteam"


def user_text(messages):
    content = messages[1]["content"]
    return content.split("<<<\n", 1)[1].rsplit("\n>>>", 1)[0] if "<<<" in content else content


class ScriptedModel:
    """Stands in for the hosted model. Detection returns the true identifiers except
    one withheld phone or ID, and gives the first date a low confidence; verification confirms
    everything except the first candidate; the reviewer reports the withheld string if it
    is still in the text. This checks the plumbing, not any model."""
    model, params = "scripted", {"max_tokens": 1}

    def __init__(self, notes, verify_reply=None):
        self.by_text = {n["text"]: n for n in notes}
        self.withheld = {}
        for n in notes:  # a phone or an ID no other string can cover
            options = [s for s in n["spans"] if s["type"] in ("PHONE", "ID")]
            pick = max(options, key=lambda s: len(s["text"]))
            self.withheld[n["note_id"]] = (pick["text"], pick["type"])
        self.calls = []
        self.verify_reply = verify_reply

    def complete(self, messages):
        kind = kind_of(messages)
        self.calls.append((kind, messages))
        return Completion(getattr(self, "_" + kind)(messages),
                          {"prompt_tokens": 100, "completion_tokens": 20}, 0.01, "stop")

    def _detect(self, messages):
        note = self.by_text[user_text(messages)]
        first_date, items = True, {}
        for s in note["spans"]:
            if s["text"] == self.withheld[note["note_id"]][0]:
                continue
            conf = 0.5 if (s["type"] == "DATE" and first_date) else 0.95
            first_date = first_date and s["type"] != "DATE"
            items[s["text"]] = {"text": s["text"], "type": s["type"], "confidence": conf}
        return json.dumps({"identifiers": list(items.values())})

    def _verify(self, messages):
        if self.verify_reply is not None:
            return self.verify_reply
        ids = [int(i) for i in re.findall(r"^(\d+)\. type=", messages[1]["content"], re.M)]
        return json.dumps({"verdicts": [
            {"id": i, "decision": "unsure" if i == 0 else "identifier", "why": "scripted"} for i in ids]})

    def _redteam(self, messages):
        text = user_text(messages)
        for string, kind in self.withheld.values():
            if string in text:
                return json.dumps({"risk": "low", "clues": [
                    {"text": string, "category": "LEFTOVER", "type": kind, "why": "plain identifier"}]})
        return json.dumps({"risk": "low", "clues": []})


class VerifierTests(unittest.TestCase):
    TEXT = "Seen on 4/5 by Dr. Wu. Cell 12. Lab WBC 14.2."

    def test_selection_takes_low_missing_and_odd_shaped_spans_only(self):
        def span(string, kind, confidence):
            i = self.TEXT.index(string)
            return {"start": i, "end": i + len(string), "type": kind, "confidence": confidence}
        spans = [span("4/5", "DATE", 0.99), span("Wu", "NAME", 0.5),
                 span("12", "PHONE", 0.99),   # too few digits
                 span("Seen", "NAME", None)]
        chosen = select_uncertain(self.TEXT, spans)
        self.assertEqual([self.TEXT[s["start"]:s["end"]] for s in chosen], ["Wu", "12", "Seen"])

    def test_parse_variants(self):
        reply = '```json\n{"verdicts": [{"id": 0, "decision": "Identifier", "why": "x"}, {"id": 1, "decision": "maybe"}]}\n```'
        self.assertEqual(parse_verdicts(reply)[0]["decision"], "identifier")
        self.assertEqual(parse_verdicts(reply)[1]["decision"], "unsure")
        with self.assertRaises(ParseError):
            parse_verdicts("nope")

    def test_silence_is_never_confirmation(self):
        class Silent:
            model, params = "m", {}
            def complete(self, messages):
                return Completion('{"verdicts": [{"id": 0, "decision": "identifier", "why": "ok"}]}', {}, 0, "stop")
        spans = [{"start": 8, "end": 11, "type": "DATE"}, {"start": 22, "end": 24, "type": "NAME"}]
        result = verify_spans(Silent(), self.TEXT, spans)
        self.assertEqual(result.verdicts[(8, 11)]["decision"], "identifier")
        self.assertEqual(result.verdicts[(22, 24)]["decision"], "unsure")

    def test_unreadable_reply_makes_everything_unsure(self):
        class Junk:
            model, params = "m", {}
            def complete(self, messages):
                return Completion("sorry", {}, 0, "stop")
        result = verify_spans(Junk(), self.TEXT, [{"start": 0, "end": 4, "type": "DATE"}])
        self.assertTrue(result.parse_error)
        self.assertEqual(result.verdicts[(0, 4)]["decision"], "unsure")

    def test_no_candidates_means_no_call(self):
        class Never:
            model, params = "m", {}
            def complete(self, messages):
                raise AssertionError("called")
        self.assertEqual(verify_spans(Never(), self.TEXT, []).asked, 0)

    def test_context_marks_the_candidate(self):
        i = self.TEXT.index("Wu")
        lines = verifier.candidate_lines(self.TEXT, [{"start": i, "end": i + 2, "type": "NAME"}])
        self.assertIn("by Dr. <<Wu>>. Cell", lines)

    def test_apply_verdict(self):
        base = {"decision": "review", "reasons": ["detector confidence 0.50 is below 0.80"]}
        confirmed = apply_verdict(base, {"decision": "identifier", "why": ""})
        self.assertEqual(confirmed, {"decision": "accept", "reasons": []})
        kept = apply_verdict({"decision": "review", "reasons": ["date has no year"]}, {"decision": "identifier", "why": ""})
        self.assertEqual(kept["decision"], "review")
        doubt = apply_verdict({"decision": "accept", "reasons": []}, {"decision": "not_identifier", "why": "a dose"})
        self.assertEqual(doubt["decision"], "review")
        self.assertIn("a dose", doubt["reasons"][0])


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.notes = generate.generate_notes(5, 4)[:3]
        self.model = ScriptedModel(self.notes)
        self.budget = Budget(0)
        self.batch, stopped = detect_and_verify(
            self.notes, self.model, Cache(None), Cache(None, "vf1"), self.budget, 0.8)
        self.assertFalse(stopped)
        self.outcomes, stopped, self.replacer = review_and_clean(
            self.batch, self.model, Cache(None, "rt1"), self.budget, 0, 0.8, 2)
        self.assertFalse(stopped)

    def count(self, kind):
        return sum(1 for k, _ in self.model.calls if k == kind)

    def test_call_counts(self):
        self.assertEqual(self.count("detect"), 3)
        self.assertEqual(self.count("verify"), 3)      # each note has a low-confidence date
        self.assertEqual(self.count("redteam"), 6)     # leftover found, then a clean second look

    def test_the_withheld_identifier_is_found_by_the_reviewer_and_removed(self):
        for o in self.outcomes:
            string = self.model.withheld[o.note_id][0]
            self.assertIn(string, o.detected.note["text"])
            self.assertNotIn(string, o.cleaned)
            self.assertEqual(o.risk_before, "high")
            self.assertEqual(o.risk_after, "low")
            self.assertTrue(o.added)

    def test_feedback_spans_are_labelled_and_sent_to_review(self):
        for o in self.outcomes:
            fed = [e for e in o.audit["entries"] if e["detector"] == "red-team feedback"]
            self.assertTrue(fed)
            self.assertTrue(all(e["status"] == "review" for e in fed))
            self.assertTrue(all("only by the red-team" in e["checks"]["reasons"][-1] for e in fed))

    def test_verifier_clears_confidence_but_unsure_goes_to_a_person(self):
        o = self.outcomes[0]
        asked = [e for e in o.audit["entries"] if e["verifier"]]
        self.assertTrue(asked)
        first = [e for e in asked if e["verifier"]["decision"] == "unsure"]
        confirmed = [e for e in asked if e["verifier"]["decision"] == "identifier"]
        self.assertTrue(first and all(e["status"] == "review" for e in first))
        for e in confirmed:
            self.assertFalse(any(r.startswith("detector confidence") for r in e["checks"]["reasons"]))

    def test_models_only_ever_see_note_text(self):
        for kind, messages in self.model.calls:
            sent = json.dumps(messages)
            for banned in ('"entity"', '"norm"', "patient_id", "gold"):
                self.assertNotIn(banned, sent)
        for kind, messages in self.model.calls:
            if kind == "redteam":
                text = user_text(messages)
                for n in self.notes:
                    for s in n["spans"]:
                        withheld = {w for w, _ in self.model.withheld.values()}
                        if s["type"] == "ID" and len(s["text"]) > 5 and s["text"] not in withheld:
                            self.assertNotIn(s["text"], text)

    def test_feedback_only_adds_spans_and_the_detectors_own_are_kept(self):
        for o in self.outcomes:
            detector = {(s["start"], s["end"]) for s in o.detected.spans}
            final = {(s["start"], s["end"]) for s in o.final_spans}
            self.assertTrue(detector < final)   # feedback only adds
            self.assertEqual(len(final) - len(detector), len(o.added))

    def test_token_cap_stops_between_notes(self):
        model = ScriptedModel(self.notes)
        budget = Budget(200)
        batch, stopped = detect_and_verify(self.notes, model, Cache(None), Cache(None, "vf1"), budget, 0.8)
        self.assertTrue(stopped)
        self.assertLess(len(batch), 3)


class RunTests(unittest.TestCase):
    def write_notes(self, tmp, notes):
        path = Path(tmp) / "notes.jsonl"
        path.write_text("".join(json.dumps(n) + "\n" for n in notes), encoding="utf-8")
        return path

    def test_dry_run_calls_nothing_and_test_split_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_notes(tmp, generate.generate_notes(3, 4))
            out = io.StringIO()
            with mock.patch("urllib.request.urlopen") as net, contextlib.redirect_stdout(out):
                self.assertEqual(run_main(["--notes", str(path), "--limit", "2"]), 0)
            net.assert_not_called()
            self.assertIn("DRY RUN", out.getvalue())
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                run_main(["--notes", str(path), "--split", "test"])

    def test_live_run_with_a_scripted_model_writes_everything(self):
        notes = generate.generate_notes(5, 4)[:2]
        model = ScriptedModel(notes)
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_notes(tmp, notes)
            argv = ["--live", "--notes", str(path), "--limit", "2", "--name", "t", "--out-dir", tmp,
                    "--cache-dir", tmp, "--results-dir", str(Path(tmp) / "res")]
            with mock.patch("deid.agent.run.ChatClient.from_env", return_value=model), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run_main(argv), 0)
            for suffix in ("notes.jsonl", "detector.jsonl", "final.jsonl", "key.json", "audit.json", "audit.html"):
                self.assertTrue((Path(tmp) / f"t.{suffix}").exists(), suffix)
            summary = json.loads((Path(tmp) / "res" / "t.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["notes_finished"], 2)
            self.assertEqual(summary["risk_before_feedback"], {"high": 2})
            self.assertEqual(summary["risk_after_feedback"], {"low": 2})
            det = json.loads((Path(tmp) / "res" / "t-detector-dev.json").read_text(encoding="utf-8"))
            fin = json.loads((Path(tmp) / "res" / "t-final-dev.json").read_text(encoding="utf-8"))
            recall = lambda r: r["metrics"]["overall"]["overlap"]["recall"] if "overall" in r["metrics"] else None
            self.assertEqual(det["notes"], 2)
            self.assertEqual(fin["notes"], 2)


if __name__ == "__main__":
    unittest.main()
