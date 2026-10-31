import json
import unittest

from deid.eval import spanish as spanish_eval
from deid.replace import dates, pools
from deid.replace.engine import Replacer
from deid.synth import spanish


class SpanishDates(unittest.TestCase):
    def test_long_form_with_de_and_del(self):
        for text, month, day, year, of in [("12 de abril de 2025", 4, 12, 2025, "de"), ("5 de Marzo del 2024", 3, 5, 2024, "del"),
                                           ("1 de septiembre de 2019", 9, 1, 2019, "de")]:
            p = dates.parse_date(text)
            self.assertEqual((p.month, p.day, p.year, p.of), (month, day, year, of), text)

    def test_shifting_keeps_the_style_and_the_spanish_month(self):
        p = dates.parse_date("12 de abril de 2025")
        self.assertEqual(dates.render(dates.shift(p, 30, 2025)), "12 de mayo de 2025")
        self.assertEqual(dates.render(dates.shift(dates.parse_date("5 de marzo del 2024"), 1, 2024)), "6 de marzo del 2024")
        self.assertEqual(dates.render(dates.shift(dates.parse_date("03 de enero"), 10, 2025)), "13 de enero")

    def test_a_word_that_is_not_a_month_is_not_a_date(self):
        with self.assertRaises(dates.DateError):
            dates.parse_date("12 de nadie de 2025")

    def test_numeric_dates_can_be_read_day_first(self):
        month_first = dates.parse_date("04/05/2025")
        day_first = dates.parse_date("04/05/2025", True)
        self.assertEqual((month_first.month, month_first.day), (4, 5))
        self.assertEqual((day_first.month, day_first.day), (5, 4))
        self.assertTrue(day_first.assumed_day_first and not day_first.assumed_month_first)
        self.assertEqual(dates.render(dates.shift(day_first, 0, 2025)), "04/05/2025")

    def test_english_dates_are_untouched(self):
        p = dates.parse_date("Apr 11, 2025")
        self.assertEqual(dates.render(p), "Apr 11, 2025")


class Engine(unittest.TestCase):
    TEXT = "Paciente: Sra. María Guadalupe Hernández López, vive en Calle Los Pinos 1423, Apto 2B, Valle Sereno, TX 79316. Consulta 12 de abril de 2025 y 13/04/2025."

    def run_es(self, **kw):
        spans = []
        for needle, kind in [("María Guadalupe Hernández López", "NAME"), ("Calle Los Pinos 1423, Apto 2B, Valle Sereno, TX 79316", "ADDRESS"),
                             ("12 de abril de 2025", "DATE"), ("13/04/2025", "DATE")]:
            i = self.TEXT.index(needle)
            spans.append({"start": i, "end": i + len(needle), "type": kind})
        r = Replacer(0, lang="es", **kw).fit([{"text": self.TEXT, "spans": spans}])
        return r.apply({"text": self.TEXT, "spans": spans, "patient_key": "p"})

    def test_spanish_notes_get_spanish_stand_ins_and_nothing_falls_back(self):
        new, changes = self.run_es()
        self.assertTrue(all(not c["flagged"] and c["rule"] != "fallback-tag" for c in changes))
        self.assertIn("Sra. ", new)
        for original in ("María", "Guadalupe", "Hernández", "López", "Los Pinos", "Valle Sereno", "1423", "79316"):
            self.assertNotIn(original, new)
        name = next(c["replacement"] for c in changes if c["type"] == "NAME")
        allowed = {w.lower() for w in pools.FIRST_ES + pools.LAST_ES + pools.EITHER_ES}
        self.assertTrue(all(w.lower() in allowed for w in name.split()), name)
        self.assertIn(" de ", next(c["replacement"] for c in changes if c["original"].startswith("12 de")))

    def test_the_two_dates_of_one_patient_move_together(self):
        _, changes = self.run_es()
        a, b = [c for c in changes if c["type"] == "DATE"]
        d1 = dates.to_date(dates.parse_date(a["replacement"], True), None) - dates.to_date(dates.parse_date(a["original"], True), None)
        d2 = dates.to_date(dates.parse_date(b["replacement"], True), None) - dates.to_date(dates.parse_date(b["original"], True), None)
        self.assertEqual(d1, d2)

    def test_defaults_and_validation(self):
        self.assertEqual(Replacer(0, lang="es").numeric_dates, "day-first")
        self.assertEqual(Replacer(0).numeric_dates, "month-first")
        self.assertEqual(Replacer(0, lang="es", numeric_dates="month-first").numeric_dates, "month-first")
        for bad in ({"lang": "fr"}, {"numeric_dates": "random"}):
            with self.assertRaises(ValueError):
                Replacer(0, **bad)

    def test_state_keeps_the_language(self):
        r = Replacer(5, lang="es")
        again = Replacer.from_state(json.loads(json.dumps(r.state())))
        self.assertEqual((again.lang, again.numeric_dates), ("es", "day-first"))

    def test_english_behaviour_is_unchanged(self):
        text = "Dr. Wu saw Kim Reyes on 04/05/2025."
        spans = [{"start": text.index(w), "end": text.index(w) + len(w), "type": k}
                 for w, k in (("Wu", "NAME"), ("Kim Reyes", "NAME"), ("04/05/2025", "DATE"))]
        r = Replacer(0).fit([{"text": text, "spans": spans}])
        new, changes = r.apply({"text": text, "spans": spans, "patient_key": "p"})
        self.assertIn("assumed-month-first", changes[-1]["rule"])
        allowed = {w.lower() for w in pools.FIRST + pools.LAST + pools.EITHER}
        self.assertIn(changes[1]["replacement"].split()[0].lower(), allowed)


class Generator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.notes = spanish.generate_notes()

    def test_deterministic_and_labels_exact(self):
        self.assertEqual(self.notes, spanish.generate_notes())
        self.assertEqual(len(self.notes), 40)
        for n in self.notes:
            for s in n["spans"]:
                self.assertEqual(n["text"][s["start"]:s["end"]], s["text"])

    def test_the_notes_look_spanish_and_cover_every_type(self):
        self.assertEqual({s["type"] for n in self.notes for s in n["spans"]}, {"NAME", "DATE", "ID", "PHONE", "EMAIL", "ADDRESS"})
        text = "\n".join(n["text"] for n in self.notes)
        for word in ("Paciente", "Fecha de nacimiento", "Sra.", "Calle", " de abril", "Dr."):
            self.assertIn(word.strip() if word != " de abril" else "de ", text)
        self.assertTrue(any(" " in s["text"] and s["type"] == "NAME" and len(s["text"].split()) >= 3 for n in self.notes for s in n["spans"]))

    def test_stand_in_pools_do_not_overlap_the_generators_names(self):
        real = {w.lower() for w in spanish.FEMALE_FIRST + spanish.MALE_FIRST + spanish.SURNAMES}
        stand_in = {w.lower() for w in pools.FIRST_ES + pools.LAST_ES + pools.EITHER_ES}
        self.assertEqual(real & stand_in, set())
        streets = {w.lower() for w in spanish.STREETS}
        self.assertEqual(streets & {w.lower() for w in pools.STREETS_ES}, set())
        towns = {t.lower() for t, _ in spanish.TOWNS}
        self.assertEqual(towns & {t.lower() for t in pools.TOWNS_ES}, set())

    def test_the_replacement_check_finds_no_leak_and_no_fallback(self):
        result = spanish_eval.check(self.notes)
        self.assertEqual(result["leaks"], [])
        self.assertEqual(result["fallback_tags"], 0)
        self.assertEqual(result["patients_with_one_shift"], result["patients_with_dates"])
        self.assertEqual(result["replacements"], sum(len(n["spans"]) for n in self.notes))


class AppOption(unittest.TestCase):
    def test_language_option(self):
        import tempfile
        from deid.app.backend import offline_backend
        from deid.app.jobs import JobStore
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(tmp, offline_backend())
            self.assertEqual(store.options({})["language"], "en")
            self.assertEqual(store.options({"language": "es"})["language"], "es")
            with self.assertRaises(ValueError):
                store.options({"language": "fr"})


if __name__ == "__main__":
    unittest.main()
