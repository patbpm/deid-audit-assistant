import unittest

from deid.synth.builder import Piece, plain, render, validate_spans


def resolver(token):
    table = {
        "name": [plain("Dr. "), Piece("Kim", "NAME", "PROVIDER", "D01")],
        "date": [Piece("03/07/2024", "DATE", "ADMIT", "", "2024-03-07")],
        "mrn": [Piece("1234567", "ID", "MRN")],
    }
    return table[token]


class RenderTests(unittest.TestCase):
    def test_offsets_match_text(self):
        text, spans = render("Seen by {name} on {date}. MRN: {mrn}", resolver)
        self.assertEqual(text, "Seen by Dr. Kim on 03/07/2024. MRN: 1234567")
        self.assertEqual([s["text"] for s in spans], ["Kim", "03/07/2024", "1234567"])
        validate_spans(text, spans)

    def test_plain_pieces_make_no_spans(self):
        _, spans = render("{name}", resolver)
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0]["start"], 4)

    def test_norm_only_on_dates(self):
        _, spans = render("{date} {mrn}", resolver)
        self.assertEqual(spans[0]["norm"], "2024-03-07")
        self.assertNotIn("norm", spans[1])

    def test_unknown_token_raises(self):
        with self.assertRaises(KeyError):
            render("{missing}", resolver)

    def test_text_without_tokens(self):
        text, spans = render("BP 132/84, no tokens.", resolver)
        self.assertEqual(text, "BP 132/84, no tokens.")
        self.assertEqual(spans, [])


class ValidateTests(unittest.TestCase):
    def span(self, start, end, text):
        return {"start": start, "end": end, "type": "NAME", "text": text}

    def test_accepts_good_spans(self):
        validate_spans("abc def", [self.span(0, 3, "abc"), self.span(4, 7, "def")])

    def test_rejects_mismatch(self):
        with self.assertRaises(ValueError):
            validate_spans("abc def", [self.span(0, 3, "xyz")])

    def test_rejects_overlap(self):
        with self.assertRaises(ValueError):
            validate_spans("abcdef", [self.span(0, 4, "abcd"), self.span(3, 6, "def")])

    def test_rejects_out_of_bounds(self):
        with self.assertRaises(ValueError):
            validate_spans("abc", [self.span(1, 9, "bc")])


if __name__ == "__main__":
    unittest.main()
