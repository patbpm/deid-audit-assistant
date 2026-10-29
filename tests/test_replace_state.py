"""A replacer that keeps its mapping between runs, for notes that arrive over time."""

import json
import unittest

from deid.replace.engine import Replacer


def note(text, names=(), dates=(), ids=(), key="P1", note_id="N1"):
    spans = []
    for kind, strings in (("NAME", names), ("DATE", dates), ("ID", ids)):
        for s in strings:
            i = text.index(s)
            spans.append({"start": i, "end": i + len(s), "type": kind})
    return {"text": text, "spans": sorted(spans, key=lambda s: s["start"]), "patient_key": key, "note_id": note_id}


FIRST = note("Patient: Kim Reyes seen 4/25/25. MRN 7788991.", ["Kim Reyes"], ["4/25/25"], ["7788991"])
SECOND = note("Follow-up for Kim Reyes on 5/30/25. MRN 7788991. Dr. Wu agrees.", ["Kim Reyes", "Wu"], ["5/30/25"], ["7788991"],
              note_id="N2")


class ExtendTests(unittest.TestCase):
    def test_a_name_gets_the_same_stand_in_in_a_later_note(self):
        r = Replacer("secret")
        r.extend([FIRST])
        one, _ = r.apply(FIRST)
        r.extend([SECOND])
        two, _ = r.apply(SECOND)
        stand_in = one.split("Patient: ")[1].split(" seen")[0]
        self.assertNotIn("Kim Reyes", one)
        self.assertIn(stand_in, two)
        self.assertEqual(one.split("MRN ")[1].rstrip("."), two.split("MRN ")[1].split(".")[0])

    def test_what_was_decided_does_not_change_when_more_notes_arrive(self):
        r = Replacer("secret")
        r.extend([FIRST])
        before = r.apply(FIRST)[0]
        r.extend([SECOND, note("Spoke with Reyes today.", ["Reyes"], note_id="N3")])
        self.assertEqual(r.apply(FIRST)[0], before)

    def test_save_and_load_gives_the_same_stand_ins(self):
        r = Replacer("secret")
        r.extend([FIRST])
        before = r.apply(FIRST)[0]
        saved = json.loads(json.dumps(r.state()))             # through JSON, as on disk
        again = Replacer.from_state(saved)
        self.assertEqual(again.apply(FIRST)[0], before)
        r.extend([SECOND])
        again.extend([SECOND])
        self.assertEqual(again.apply(SECOND)[0], r.apply(SECOND)[0])
        self.assertEqual(again.key_tables(), r.key_tables())

    def test_dates_move_by_the_same_days_for_one_patient_in_every_note(self):
        r = Replacer("secret")
        r.extend([FIRST, SECOND])
        _, a = r.apply(FIRST)
        _, b = r.apply(SECOND)
        from deid.replace import dates
        shift_a = dates.parse_date(a[1]["replacement"] if a[1]["type"] == "DATE" else a[0]["replacement"])
        self.assertIsNotNone(shift_a)
        self.assertEqual(r.date_offset("P1"), r.date_offset("P1"))
        self.assertNotEqual(Replacer("another secret").date_offset("P1"), r.date_offset("P1"))

    def test_the_seed_is_what_makes_the_mapping_hard_to_repeat(self):
        a, b = Replacer("one"), Replacer("two")
        a.extend([FIRST])
        b.extend([FIRST])
        self.assertNotEqual(a.apply(FIRST)[0], b.apply(FIRST)[0])

    def test_a_real_name_that_is_already_someone_elses_stand_in_is_reported(self):
        r = Replacer("secret")
        r.extend([FIRST])
        stand_in = r.apply(FIRST)[0].split("Patient: ")[1].split(" ")[0]
        taken = r.extend([note(f"Patient: {stand_in} Lopez", [f"{stand_in} Lopez"], note_id="N9", key="P9")])
        self.assertIn(stand_in.lower(), taken)

    def test_later_real_names_are_never_chosen_as_stand_ins(self):
        r = Replacer("secret")
        r.extend([FIRST])
        r.apply(FIRST)
        r.extend([note("Patient: Mei Chen", ["Mei Chen"], note_id="N5", key="P5")])
        for token in ("Mei", "Chen"):
            self.assertIn(token.lower(), r.surrogates.first.forbidden)

    def test_fit_still_works_as_before(self):
        r = Replacer(0).fit([FIRST, SECOND])
        self.assertNotIn("Kim", r.apply(FIRST)[0])


if __name__ == "__main__":
    unittest.main()
