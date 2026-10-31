import json
import unittest
from pathlib import Path

from deid.agent.pipeline import with_rules
from deid.detect import site
from deid.detect.client import Completion
from deid.detect.detector import Cache
from deid.detect.prompt import build_messages
from deid.eval import site as site_eval
from deid.replace.engine import Replacer, clean_spans
from deid.synth import generate
from deid.synth import site as site_synth

ROOT = Path(__file__).resolve().parents[1]
PROFILE = {"name": "Test", "facilities": ["Hartwell Regional Hospital", "HRH", "Birch Pavilion"],
           "id_patterns": [{"label": "Research ID", "regex": r"HRH-\d{5}", "example": "HRH-12345"}],
           "notes": "Wings are named after trees."}


class Parsing(unittest.TestCase):
    def test_the_shipped_profile_loads(self):
        profile = site.load(ROOT / "data" / "site" / "hartwell.json")
        self.assertIn("Birch Pavilion", profile.facilities)
        self.assertEqual(len(profile.id_patterns), 2)

    def test_bad_profiles_say_what_to_fix(self):
        for data, word in [([], "JSON object"), ({"colour": 1}, "unknown field"), ({"facilities": "HRH"}, "list"),
                           ({"facilities": [""]}, "non-empty"), ({"facilities": ["x" * 90]}, "longer"),
                           ({"id_patterns": [{"label": "a", "regex": "("}]}, "valid regular expression"),
                           ({"id_patterns": [{"label": "a", "regex": "x*"}]}, "empty string"),
                           ({"id_patterns": [{"label": "a"}]}, "non-empty"),
                           ({"id_patterns": [{"label": "a", "regex": "a", "extra": 1}]}, "label"),
                           ({"notes": "n" * 700}, "longer")]:
            with self.assertRaises(site.ProfileError, msg=data) as caught:
                site.parse(data)
            self.assertIn(word, str(caught.exception), data)

    def test_duplicates_are_dropped_and_names_kept_in_order(self):
        profile = site.parse({"facilities": ["Birch Pavilion", "birch pavilion", "HRH"]})
        self.assertEqual(profile.facilities, ["Birch Pavilion", "HRH"])

    def test_from_names_for_the_text_box(self):
        self.assertEqual(site.from_names("A Clinic\n\n  B Wing  \n").facilities, ["A Clinic", "B Wing"])
        self.assertTrue(site.from_names("").empty())

    def test_digest_changes_with_content(self):
        a, b = site.parse(PROFILE), site.parse({**PROFILE, "facilities": ["HRH"]})
        self.assertNotEqual(a.digest(), b.digest())
        self.assertEqual(a.digest(), site.parse(PROFILE).digest())


class Rules(unittest.TestCase):
    TEXT = "Seen at hartwell regional hospital, Birch Pavilion. HRH-12345 enrolled; HRH staff. Birchwood is not listed."

    def found(self, existing=()):
        return [(s["type"], self.TEXT[s["start"]:s["end"]]) for s in site.parse(PROFILE).rule_spans(self.TEXT, existing)]

    def test_listed_names_and_codes_are_found(self):
        self.assertEqual(self.found(), [("FACILITY", "hartwell regional hospital"), ("FACILITY", "Birch Pavilion"),
                                        ("ID", "HRH-12345"), ("FACILITY", "HRH")])

    def test_a_name_inside_a_longer_word_or_code_is_not_a_match(self):
        self.assertNotIn(("FACILITY", "Birch"), self.found())

    def test_existing_spans_win(self):
        i = self.TEXT.index("Birch Pavilion")
        self.assertNotIn(("FACILITY", "Birch Pavilion"), self.found([{"start": i, "end": i + 14}]))

    def test_with_rules_retypes_a_model_address_that_is_a_listed_name(self):
        text = "Seen at Birch Pavilion and Linden Annex."
        d = type("D", (), {"note": {"text": text}, "spans": [
            {"start": 8, "end": 22, "type": "ADDRESS", "confidence": 0.9},
            {"start": 27, "end": 39, "type": "ADDRESS", "confidence": 0.9}]})()
        spans = with_rules(d, site.parse(PROFILE))
        self.assertEqual([s["type"] for s in spans], ["FACILITY", "ADDRESS"])
        replacer = Replacer(0).fit([{"text": text, "spans": spans}])
        new, changes = replacer.apply({"text": text, "spans": clean_spans(text, spans), "patient_key": "p"})
        self.assertIn("Facility 1", new)
        self.assertNotIn("Birch Pavilion", new)
        self.assertNotIn("Linden Annex", new)

    def test_the_same_facility_gets_the_same_stand_in(self):
        r = Replacer(0)
        self.assertEqual(r.replace_value("FACILITY", "Birch Pavilion", "k")[0], r.replace_value("FACILITY", "BIRCH PAVILION", "k")[0])
        self.assertNotEqual(r.replace_value("FACILITY", "Birch Pavilion", "k")[0], r.replace_value("FACILITY", "HRH", "k")[0])
        again = Replacer.from_state(json.loads(json.dumps(r.state())))
        self.assertEqual(again.replace_value("FACILITY", "HRH", "k")[0], "Facility 2")


class Wrapped(unittest.TestCase):
    class Inner:
        model, params = "m", {"max_tokens": 1}

        def __init__(self):
            self.seen = []

        def complete(self, messages, **kwargs):
            self.seen.append((messages, kwargs))
            return Completion("{}", {}, 0.0, "stop")

    def test_only_the_detection_prompt_gets_the_local_rules(self):
        inner = self.Inner()
        client = site.wrap(inner, site.parse(PROFILE))
        client.complete(build_messages("a note"), max_output_tokens=9)
        client.complete([{"role": "system", "content": "You double-check candidate spans."}, {"role": "user", "content": "x"}])
        detect, other = inner.seen
        self.assertIn("Local rules for this site", detect[0][0]["content"])
        self.assertIn("Hartwell Regional Hospital", detect[0][0]["content"])
        self.assertIn("HRH-12345", detect[0][0]["content"])
        self.assertEqual(detect[1], {"max_output_tokens": 9})
        self.assertNotIn("Local rules", other[0][0]["content"])

    def test_cache_keys_differ_with_and_without_the_profile(self):
        inner = self.Inner()
        cache = Cache(None)
        plain = cache.key(inner, "a note")
        profiled = cache.key(site.wrap(inner, site.parse(PROFILE)), "a note")
        other = cache.key(site.wrap(inner, site.parse({**PROFILE, "facilities": ["HRH"]})), "a note")
        self.assertEqual(len({plain, profiled, other}), 3)

    def test_an_empty_profile_changes_nothing(self):
        inner = self.Inner()
        self.assertIs(site.wrap(inner, site.Profile()), inner)
        self.assertIs(site.wrap(inner, None), inner)


class InventedSite(unittest.TestCase):
    def test_the_set_is_deterministic_and_its_labels_are_exact(self):
        a, b = site_synth.build(20), site_synth.build(20)
        self.assertEqual(a, b)
        base = {n["note_id"]: n for n in generate.generate_notes(site_synth.SEED, 5)}
        for n in a:
            for s in n["spans"]:
                self.assertEqual(n["text"][s["start"]:s["end"]], s["text"])
            if n["note_id"] in base:  # the base labels did not move
                kept = [s for s in n["spans"] if "site" not in s]
                self.assertEqual(kept, base[n["note_id"]]["spans"])
        groups = {s["site"] for n in a for s in n["spans"] if "site" in s}
        self.assertEqual(groups, {"listed", "unlisted"})

    def test_the_profile_lists_what_the_set_calls_listed(self):
        profile = site.load(ROOT / "data" / "site" / "hartwell.json")
        for n in site_synth.build(60):
            spans = profile.rule_spans(n["text"], [s for s in n["spans"] if "site" not in s])
            hit = {(s["start"], s["end"]) for s in spans}
            for s in n["spans"]:
                if s.get("site") == "listed":
                    self.assertIn((s["start"], s["end"]), hit, s["text"])
                if s.get("site") == "unlisted":
                    self.assertNotIn((s["start"], s["end"]), hit, s["text"])


class Scoring(unittest.TestCase):
    def test_groups_and_false_positives(self):
        notes = site_synth.build(8)
        perfect = {n["note_id"]: [{"start": s["start"], "end": s["end"], "type": s["type"]} for s in n["spans"]] for n in notes}
        result = site_eval.score(notes, perfect)
        for group in result["groups"].values():
            self.assertEqual(group["hit"], group["gold"])
        self.assertEqual(result["false_positives"], 0)
        noisy = {k: v + [{"start": 0, "end": 1, "type": "NAME"}] for k, v in perfect.items()}
        expected = sum(not any(s["start"] < 1 and 0 < s["end"] for s in n["spans"]) for n in notes)
        self.assertEqual(site_eval.score(notes, noisy)["false_positives"], expected)

    def test_profile_rules_lift_listed_recall_from_a_detector_that_knows_nothing_local(self):
        notes = site_synth.build(30)
        base_only = {n["note_id"]: [s for s in n["spans"] if "site" not in s] for n in notes}
        before = site_eval.score(notes, base_only)["groups"]
        profile = site.load(ROOT / "data" / "site" / "hartwell.json")
        after = site_eval.score(notes, site_eval.merge_profile(notes, base_only, profile))["groups"]
        self.assertEqual(before["listed"]["hit"], 0)
        self.assertEqual(after["listed"]["hit"], after["listed"]["gold"])
        self.assertEqual(after["unlisted"]["hit"], 0)  # rules alone do not generalize


class InTheApp(unittest.TestCase):
    NOTE = b"Patient: Kim Reyes\nMRN: 7654321\nSeen at Birch Pavilion by Dr. Wu on 2025-03-04. Call 507-555-0142.\n"

    def run_job(self, options):
        import tempfile
        from deid.app.backend import offline_backend
        from deid.app.jobs import JobStore
        from tests.test_app import wait
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(tmp, offline_backend())
            job = store.create()
            store.add_file(job["id"], "note.txt", self.NOTE)
            store.start(job["id"], options)
            done = wait(store, job["id"], ("done", "failed"))
            audit = json.loads((Path(tmp) / job["id"] / "notes.audit.json").read_text(encoding="utf-8")) if done["state"] == "done" else None
            return done, audit

    def test_typed_local_names_are_replaced_even_with_the_offline_engine(self):
        done, audit = self.run_job({"site_names": "Birch Pavilion\nMICU-3"})
        self.assertEqual(done["state"], "done", done.get("error"))
        entries = audit["notes"][0]["entries"]
        facility = [e for e in entries if e["type"] == "FACILITY"]
        self.assertEqual([(e["original"], e["replacement"], e["detector"]) for e in facility],
                         [("Birch Pavilion", "Facility 1", "site profile")])

    def test_without_the_box_nothing_changes(self):
        done, audit = self.run_job({})
        self.assertFalse([e for e in audit["notes"][0]["entries"] if e["type"] == "FACILITY"])

    def test_a_bad_box_is_refused_with_the_reason(self):
        import tempfile
        from deid.app.backend import offline_backend
        from deid.app.jobs import JobStore
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(tmp, offline_backend())
            job = store.create()
            store.add_file(job["id"], "note.txt", self.NOTE)
            with self.assertRaises(ValueError) as caught:
                store.start(job["id"], {"site_names": "x" * 200})
            self.assertIn("local names", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
