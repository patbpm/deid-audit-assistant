import random
import re
import unittest
from datetime import date

from deid.synth import formats


class DateFormatTests(unittest.TestCase):
    def test_each_style(self):
        d = date(2024, 3, 7)
        expected = {
            "slash": "03/07/2024",
            "slash_nopad": "3/7/2024",
            "slash2": "03/07/24",
            "iso": "2024-03-07",
            "long": "March 7, 2024",
            "dmy": "7 Mar 2024",
            "mon_day": "Mar 7",
            "slash_md": "3/7",
        }
        for style, text in expected.items():
            self.assertEqual(formats.fmt_date(d, style), text, style)

    def test_unknown_style_raises(self):
        with self.assertRaises(ValueError):
            formats.fmt_date(date(2024, 1, 1), "nope")


class SafeValueTests(unittest.TestCase):
    def setUp(self):
        self.rng = random.Random(1)

    def test_phones_use_reserved_fiction_block(self):
        for _ in range(200):
            phone = formats.make_phone(self.rng)
            for style in formats.PHONE_STYLES:
                text = formats.fmt_phone(phone, style)
                digits = re.sub(r"\D", "", text)[-7:]
                self.assertTrue(digits.startswith("55501"), text)

    def test_ssn_area_is_never_issued_range(self):
        for _ in range(200):
            ssn = formats.make_ssn(self.rng)
            self.assertRegex(ssn, r"^9\d\d-\d\d-\d{4}$")

    def test_email_domains_are_reserved(self):
        for _ in range(50):
            email = formats.make_email(self.rng, "Maria", "O'Brien")
            self.assertRegex(email, r"^[a-z0-9._]+@example\.(com|org)$")

    def test_address_format(self):
        for _ in range(100):
            text = formats.fmt_address(formats.make_address(self.rng))
            self.assertRegex(text, r"^\d+ [A-Za-z ]+, (.+, )?[A-Za-z ]+, [A-Z]{2} \d{5}$")


if __name__ == "__main__":
    unittest.main()
