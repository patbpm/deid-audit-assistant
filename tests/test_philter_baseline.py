import re
import unittest

from deid.baselines.philter_baseline import hoist_global_flags, mask_to_spans


class MaskToSpansTests(unittest.TestCase):
    def test_single_word(self):
        spans = mask_to_spans("Dr. Kim saw", "Dr. *** saw")
        self.assertEqual(spans, [{"start": 4, "end": 7, "type": "PHI"}])

    def test_merges_across_single_space_and_slash(self):
        text = "John Smith, 04/14/2025"
        masked = "**** *****, **/**/****"
        spans = mask_to_spans(text, masked)
        self.assertEqual([(s["start"], s["end"]) for s in spans], [(0, 10), (12, 22)])

    def test_adjacent_masked_words_with_one_space_become_one_span(self):
        self.assertEqual(len(mask_to_spans("John Smith 04/14", "**** ***** **/**")), 1)

    def test_does_not_merge_across_words_or_comma(self):
        spans = mask_to_spans("Kim, Lee", "***, ***")
        self.assertEqual(len(spans), 2)

    def test_existing_asterisks_in_source_are_not_masks(self):
        self.assertEqual(mask_to_spans("a*b", "a*b"), [])

    def test_length_mismatch_raises(self):
        with self.assertRaises(ValueError):
            mask_to_spans("abc", "ab")

    def test_mask_at_end(self):
        self.assertEqual(mask_to_spans("id 123", "id ***")[0]["end"], 6)


class HoistFlagsTests(unittest.TestCase):
    def test_moves_inline_flag_to_front(self):
        fixed = hoist_global_flags(r"\bfoo(?i)bar")
        self.assertEqual(fixed, r"(?i)\bfoobar")
        self.assertTrue(re.compile(fixed).search("xx FOOBAR"))

    def test_leaves_flagless_patterns_alone(self):
        self.assertEqual(hoist_global_flags(r"(?:a|b)(?<=c)"), r"(?:a|b)(?<=c)")

    def test_multiple_flags_are_merged(self):
        self.assertEqual(hoist_global_flags(r"a(?i)b(?s)c"), r"(?is)abc")


if __name__ == "__main__":
    unittest.main()
