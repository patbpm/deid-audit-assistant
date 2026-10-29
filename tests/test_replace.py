import random
import re
import unittest
from datetime import date

from deid.replace import dates, pools
from deid.replace.check import run_checks
from deid.replace.engine import Replacer, clean_spans
from deid.replace.surrogates import Registry, Surrogates
from deid.synth import formats, generate
from deid.synth import pools as synth_pools


def note(text, spans, key="P1"):
    return {"text": text, "spans": spans, "patient_key": key}


def span(text, whole, kind):
    start = whole.index(text)
    return {"start": start, "end": start + len(text), "type": kind}


class DateTests(unittest.TestCase):
    def test_every_generator_style_round_trips(self):
        rng = random.Random(1)
        for style in (*formats.FULL_DATE_STYLES, *formats.PARTIAL_DATE_STYLES):
            for _ in range(200):
                d = date(rng.randint(1950, 2026), rng.randint(1, 12), rng.randint(1, 28))
                text = formats.fmt_date(d, style)
                self.assertEqual(dates.render(dates.parse_date(text)), text, (style, text))

    def test_shift_keeps_intervals(self):
        a, b = date(2025, 4, 11), date(2025, 4, 18)
        pa, pb = dates.parse_date("04/11/2025"), dates.parse_date("04/18/2025")
        for days in (-355, -1, 40, 365):
            ma, mb = dates.shift(pa, days, 2025), dates.shift(pb, days, 2025)
            self.assertEqual((dates.to_date(mb, 0) - dates.to_date(ma, 0)).days, 7)

    def test_year_rollover_and_leap_day(self):
        moved = dates.shift(dates.parse_date("2025-12-30"), 5, 2025)
        self.assertEqual(dates.render(moved), "2026-01-04")
        moved = dates.shift(dates.parse_date("2024-02-28"), 1, 2024)
        self.assertEqual(dates.render(moved), "2024-02-29")

    def test_year_less_stays_year_less(self):
        self.assertEqual(dates.render(dates.shift(dates.parse_date("Apr 21"), 10, 2025)), "May 1")
        self.assertEqual(dates.render(dates.shift(dates.parse_date("4/21"), 10, 2025)), "5/1")

    def test_two_digit_years_and_day_first(self):
        self.assertEqual(dates.parse_date("08/17/80").year, 1980)
        self.assertEqual(dates.parse_date("04/13/25").year, 2025)
        p = dates.parse_date("17/08/1980")
        self.assertEqual((p.month, p.day, p.day_first), (8, 17, True))
        self.assertEqual(dates.render(p), "17/08/1980")

    def test_unreadable_dates_raise(self):
        for text in ("yesterday", "13/45/2020", "Foo 12", "2025-02-30", ""):
            with self.assertRaises(dates.DateError, msg=text):
                dates.parse_date(text)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.r = Replacer(3)

    def test_offsets_and_untouched_text(self):
        text = "Seen on 04/11/2025 by Dr. Kim, call 555-0100."
        spans = [span("04/11/2025", text, "DATE"), span("Kim", text, "NAME"), span("555-0100", text, "PHONE")]
        new, changes = self.r.fit([note(text, spans)]).apply(note(text, spans))
        self.assertTrue(new.startswith("Seen on ") and ", call " in new and "by Dr. " in new)
        for c in changes:
            self.assertEqual(new[c["new_start"]:c["new_end"]], c["replacement"])
            self.assertEqual(text[c["start"]:c["end"]], c["original"])
        self.assertNotIn("Kim", new)

    def test_only_start_end_type_are_used(self):
        text = "Patient Jane Doe, seen 04/11/2025."
        plain = [span("Jane Doe", text, "NAME"), span("04/11/2025", text, "DATE")]
        noisy = [{**s, "entity": "P9", "norm": "1999-01-01", "subtype": "X", "text": "junk"} for s in plain]
        a = Replacer(3).fit([note(text, plain)]).apply(note(text, plain))
        b = Replacer(3).fit([note(text, noisy)]).apply(note(text, noisy))
        self.assertEqual(a[0], b[0])

    def test_unparseable_values_are_tagged_and_flagged_never_kept(self):
        text = "Born around the spring of last year, lives at 12 Unknown Place."
        spans = [span("the spring of last year", text, "DATE"), span("12 Unknown Place", text, "ADDRESS")]
        new, changes = self.r.apply(note(text, spans))
        self.assertIn("[DATE]", new)
        self.assertIn("[ADDRESS]", new)
        self.assertNotIn("Unknown", new)
        self.assertTrue(all(c["flagged"] for c in changes))

    def test_overlapping_spans_keep_the_longer(self):
        text = "Kim, Susan arrived."
        spans = [{"start": 0, "end": 3, "type": "NAME"}, {"start": 0, "end": 10, "type": "NAME"}]
        self.assertEqual(clean_spans(text, spans), [{"start": 0, "end": 10, "type": "NAME"}])

    def test_bad_offsets_are_dropped(self):
        self.assertEqual(clean_spans("abc", [{"start": 2, "end": 9, "type": "NAME"},
                                             {"start": 1, "end": 1, "type": "NAME"},
                                             {"start": 0, "end": 2, "type": "SHOE"}]), [])

    def test_one_shift_per_patient_across_notes(self):
        r = Replacer(3)
        t1, t2 = "Admitted 04/11/2025.", "Discharged 04/18/2025."
        n1 = r.apply(note(t1, [span("04/11/2025", t1, "DATE")], "P1"))[0]
        n2 = r.apply(note(t2, [span("04/18/2025", t2, "DATE")], "P1"))[0]
        d1 = dates.to_date(dates.parse_date(n1.split()[1].rstrip(".")), 0)
        d2 = dates.to_date(dates.parse_date(n2.split()[1].rstrip(".")), 0)
        self.assertEqual((d2 - d1).days, 7)
        self.assertEqual(r.date_offset("P1"), r.date_offset("P1"))

    def test_name_forms_stay_linked_and_relatives_share_a_surname(self):
        text = ("Patient: Murphy, Patrick R. Patrick Murphy was seen. Spouse Colleen Murphy. "
                "Dr. Nash agrees. Nash, Beatriz MD signed. Patrick: stable.")
        names = ["Murphy, Patrick R", "Patrick Murphy", "Colleen Murphy", "Nash", "Nash, Beatriz", "Patrick"]
        spans, cursor = [], 0
        for n in names:
            start = text.index(n, cursor)
            spans.append({"start": start, "end": start + len(n), "type": "NAME"})
            cursor = start + len(n)
        r = Replacer(5).fit([note(text, spans)])
        new, ch = r.apply(note(text, spans))
        rep = [c["replacement"] for c in ch]
        fake_first = rep[1].split()[0]
        fake_last = rep[1].split()[1]
        self.assertEqual(rep[0].split(", ")[0], fake_last)
        self.assertTrue(rep[0].startswith(f"{fake_last}, {fake_first} "))
        self.assertEqual(rep[2].split()[1], fake_last)
        self.assertNotEqual(rep[2].split()[0], fake_first)
        self.assertEqual(rep[5], fake_first)
        self.assertEqual(rep[4].split(", ")[0], rep[3])
        self.assertIn("MD", new)
        self.assertIn("Dr. ", new)
        for real in ("Murphy", "Patrick", "Colleen", "Nash", "Beatriz"):
            self.assertNotRegex(new, rf"\b{real}\b")

    def test_name_case_hyphen_and_apostrophe(self):
        text = "PATIENT: O'BRIEN-SMYTH, J and Larsen-Hughes"
        spans = [span("O'BRIEN-SMYTH, J", text, "NAME"), span("Larsen-Hughes", text, "NAME")]
        new, ch = Replacer(2).fit([note(text, spans)]).apply(note(text, spans))
        self.assertTrue(ch[0]["replacement"].split(",")[0].isupper())
        self.assertIn("-", ch[1]["replacement"])
        self.assertNotRegex(new, r"BRIEN|SMYTH|Larsen|Hughes")

    def test_identifiers_keep_shape_and_are_stable(self):
        s = Surrogates(1)
        for original in ("6167853", "ACCT1068456722", "DWJ194963587", "RAD-25-004217", "MRN: 1234567"):
            new = s.identifier(original)
            self.assertNotEqual(new, original)
            self.assertEqual(re.sub(r"[A-Z]", "A", re.sub(r"\d", "9", new)),
                             re.sub(r"[A-Z]", "A", re.sub(r"\d", "9", original)))
            self.assertEqual(s.identifier(original), new)
        self.assertTrue(s.identifier("ACCT1068456722").startswith("ACCT"))
        self.assertTrue(s.identifier("RAD-25-004217").startswith("RAD-"))
        self.assertTrue(re.fullmatch(r"9\d\d-\d\d-\d{4}", s.identifier("923-45-6789")))

    def test_distinct_ids_get_distinct_surrogates(self):
        s = Surrogates(1)
        out = {s.identifier(f"{n:07d}") for n in range(1000, 3000)}
        self.assertEqual(len(out), 2000)

    def test_phones_are_fictional_and_keep_punctuation(self):
        s = Surrogates(1)
        for original, pattern in (("(319) 555-0142", r"\(\d{3}\) 555-01\d\d"), ("319-555-0142", r"\d{3}-555-01\d\d"),
                                  ("319.555.0142", r"\d{3}\.555\.01\d\d"), ("+1 319-555-0142", r"\+1 \d{3}-555-01\d\d")):
            self.assertRegex(s.phone(original), pattern)
            self.assertNotEqual(s.phone(original), original)
        self.assertEqual(re.sub(r"\D", "", s.phone("(319) 555-0142")), re.sub(r"\D", "", s.phone("319-555-0142")))

    def test_email_uses_reserved_domain(self):
        self.assertRegex(Surrogates(1).email("Jane.Doe@hospital.org"), r"^[a-z]+\.[a-z]+\d\d@example\.(com|org)$")

    def test_addresses(self):
        r = Replacer(4)
        text = "Home: 5338 Meadow Rd, Apt 5B, Eastvale, IL 54219. Clinic in Eastvale, IL. Town Eastvale."
        spans = [span("5338 Meadow Rd, Apt 5B, Eastvale, IL 54219", text, "ADDRESS"),
                 span("Eastvale, IL", text.replace("Eastvale, IL 54219", "-" * 18), "ADDRESS")]
        spans[1] = {"start": text.index("Clinic in ") + 10, "end": text.index("Clinic in ") + 22, "type": "ADDRESS"}
        spans.append(span("Eastvale", text[text.index("Town"):], "ADDRESS"))
        spans[2] = {"start": text.index("Town ") + 5, "end": text.index("Town ") + 13, "type": "ADDRESS"}
        new, ch = r.fit([note(text, spans)]).apply(note(text, spans))
        full, town, bare = (c["replacement"] for c in ch)
        self.assertRegex(full, r"^\d+ \w+ Rd, Apt \d\w, [\w ]+, IL \d{5}$")
        fake_town = town.split(",")[0]
        self.assertIn(f", {fake_town}, IL", full)
        self.assertEqual(bare, fake_town)
        self.assertNotRegex(new, r"Eastvale|Meadow")

    def test_deterministic_for_a_seed(self):
        notes = [{**n, "patient_key": n["patient_id"]} for n in generate.generate_notes(2, 6)]
        run = lambda seed: [Replacer(seed).fit(notes).apply(n)[0] for n in notes[:3]]
        self.assertEqual(run(1), run(1))
        self.assertNotEqual(run(1), run(2))


class RegistryTests(unittest.TestCase):
    def test_injective_and_avoids_forbidden(self):
        reg = Registry(1, "t", ["A", "B", "C"], forbidden=["b"])
        got = [reg.get(x) for x in "wxyz"]
        self.assertEqual(len(set(got)), 4)  # pool of 2 usable, then invented names
        self.assertNotIn("B", got)
        self.assertEqual(reg.get("W"), reg.get("w"))

    def test_pools_are_disjoint_from_the_generator(self):
        real = {n.lower() for n in (*synth_pools.FEMALE_FIRST, *synth_pools.MALE_FIRST, *synth_pools.LAST_NAMES)}
        real |= {s.lower() for s in synth_pools.STREET_NAMES} | {t.lower() for t, _ in synth_pools.TOWNS}
        mine = [*pools.FIRST, *pools.LAST, *pools.EITHER, *pools.STREETS, *pools.TOWNS]
        self.assertFalse(real & {m.lower() for m in mine})
        self.assertEqual(len(mine), len({m.lower() for m in mine}))


class CorpusCheckTests(unittest.TestCase):
    def test_true_spans_give_a_clean_report(self):
        report = run_checks(generate.generate_notes(9, 25), seed=1)
        self.assertEqual(report["flagged"], 0)
        self.assertEqual(report["leaked_strings_by_type"], {})
        self.assertEqual(report["dates"]["patients_with_inconsistent_shift"], 0)
        self.assertTrue(report["dates"]["shift_matches_offset"])
        names = report["names"]
        self.assertEqual((names["tokens_with_several_surrogates"], names["surrogates_shared_by_several_tokens"],
                          names["surrogates_equal_to_a_real_token"], names["people_with_inconsistent_tokens"]),
                         (0, 0, 0, 0))
        self.assertEqual(report["shapes_not_preserved"], 0)
        self.assertEqual(report["notes_with_changed_text_outside_spans"], 0)


if __name__ == "__main__":
    unittest.main()


class MoreFormatTests(unittest.TestCase):
    """Formats found by running the engine on the adversarial set."""

    def shifted(self, text, days=100, ref_year=2025):
        return dates.render(dates.shift(dates.parse_date(text), days, ref_year))

    def test_new_date_styles_keep_their_shape_and_the_interval(self):
        for text in ("2025-3-4", "2025.12.19", "1-Apr-25", "16-Aug-2025", "17Feb2025", "6th of February 2024",
                     "21st of March", "30.04.2025", "11-10"):
            moved = self.shifted(text)
            self.assertEqual(re.sub(r"[A-Za-z]+", "a", re.sub(r"\d+", "9", moved)).count("a"),
                             re.sub(r"[A-Za-z]+", "a", re.sub(r"\d+", "9", text)).count("a"), text)
            self.assertNotEqual(moved, text)
            back = dates.shift(dates.parse_date(moved), -100, 2025)
            self.assertEqual((back.month, back.day), (dates.parse_date(text).month, dates.parse_date(text).day), text)

    def test_unpadded_iso_stays_unpadded_and_padded_stays_padded(self):
        self.assertEqual(self.shifted("2025-3-4", 0), "2025-3-4")
        self.assertEqual(self.shifted("2025-03-04", 0), "2025-03-04")

    def test_ordinal_suffix_follows_the_new_day(self):
        self.assertEqual(self.shifted("1st of May 2025", 1), "2nd of May 2025")
        self.assertEqual(self.shifted("1st of May 2025", 10), "11th of May 2025")
        self.assertEqual(self.shifted("1st of May 2025", 21), "22nd of May 2025")

    def test_dotted_dates_are_day_first_and_ambiguous_ones_are_marked(self):
        self.assertEqual(self.shifted("30.04.2025", 1), "01.05.2025")
        self.assertTrue(dates.parse_date("04.05.2025").assumed_day_first)
        self.assertFalse(dates.parse_date("30.04.2025").assumed_day_first)
        self.assertEqual(dates.parse_date("04.05.2025").day, 4)

    def test_garbage_dates_still_raise(self):
        for text in ("7/7//2025", "31.02.2025", "2025-13-01", "hello"):
            with self.assertRaises(dates.DateError, msg=text):
                dates.parse_date(text)

    def test_engine_flags_ambiguous_dotted_dates_by_rule_name(self):
        text = "Seen 04.05.2025."
        out, changes = Replacer(0).fit([note(text, [span("04.05.2025", text, "DATE")])]).apply(
            note(text, [span("04.05.2025", text, "DATE")]))
        self.assertIn("assumed-day-first", changes[0]["rule"])
        self.assertNotIn("04.05.2025", out)

    def test_po_box_and_spelled_out_state_and_unit_first_addresses(self):
        cases = {"PO Box 8437, Larkspur, NE 71472": "address-po-box",
                 "739 Elm Street, Fox Hollow, Illinois 59298": "address-structured",
                 "Unit 33, 694 Orchard Ave, Stillwater Bay, MN 43409": "address-structured",
                 "P.O. Box 12, Westmoor, IA": "address-po-box"}
        for text, rule in cases.items():
            n = note("Lives at " + text + ".", [span(text, "Lives at " + text + ".", "ADDRESS")])
            out, changes = Replacer(0).fit([n]).apply(n)
            self.assertEqual(changes[0]["rule"], rule, text)
            self.assertFalse(changes[0]["flagged"], text)
            for piece in re.findall(r"\d{3,}|Larkspur|Fox Hollow|Elm|Orchard|Stillwater Bay|Westmoor", text):
                self.assertNotIn(piece, changes[0]["replacement"], (text, piece))
            self.assertEqual(re.findall(r"\b[A-Z]{2}\b|Illinois", text)[-1:], re.findall(r"\b[A-Z]{2}\b|Illinois", changes[0]["replacement"])[-1:])

    def test_address_without_commas_is_still_flagged_not_guessed(self):
        text = "92 Forest St Apt 5B Larkspur NE 71472"
        n = note(text, [span(text, text, "ADDRESS")])
        _, changes = Replacer(0).fit([n]).apply(n)
        self.assertTrue(changes[0]["flagged"])
        self.assertEqual(changes[0]["replacement"], "[ADDRESS]")

    def test_a_phone_that_is_already_fictional_still_changes(self):
        s = Surrogates(0)
        for text in ("555 0109", "555-0142", "(312) 555-0100", "1-312-555-0145"):
            self.assertNotEqual(s.phone(text), text)
            self.assertEqual(len(s.phone(text)), len(text))
