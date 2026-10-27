import random
import unittest

from deid.synth import people


class PatientTests(unittest.TestCase):
    def setUp(self):
        self.rng = random.Random(7)
        self.providers = people.make_providers(self.rng)

    def test_timeline_is_ordered(self):
        for i in range(1, 100):
            p = people.make_patient(self.rng, i, self.providers)
            self.assertLess(p.prior, p.admit)
            self.assertLess(p.admit, p.discharge)
            self.assertLess(p.discharge, p.followup)
            self.assertLess(p.dob, p.admit)

    def test_age_matches_dob_roughly(self):
        for i in range(1, 100):
            p = people.make_patient(self.rng, i, self.providers)
            years = (p.admit - p.dob).days / 365.25
            self.assertAlmostEqual(years, p.age, delta=1.1)
            self.assertLess(p.age, 90)  # ages over 89 are a separate identifier class

    def test_entity_ids_are_unique_per_patient(self):
        p = people.make_patient(self.rng, 5, self.providers)
        ids = [p.person.entity, p.kin.entity] + ([p.spouse.entity] if p.spouse else [])
        self.assertEqual(len(set(ids)), len(ids))
        self.assertEqual(p.person.entity, "P0005")

    def test_providers_are_stable_ids(self):
        self.assertEqual([x.person.entity for x in self.providers][:3], ["D01", "D02", "D03"])
        self.assertTrue(all(x.specialty == "radiology" for x in self.providers[:4]))
        self.assertFalse(any(x.specialty == "radiology" for x in self.providers[4:]))


if __name__ == "__main__":
    unittest.main()
