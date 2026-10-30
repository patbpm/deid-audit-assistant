import unittest

from deid.eval.leak import check, cleaned_text


def audit_of(text, entries):
    return {"notes": [{"note_id": "N1", "text": text, "entries": entries}]}


class LeakCheckTest(unittest.TestCase):
    def test_cleaned_text_applies_changes_by_offset(self):
        text = "Dr. Kim saw Ana on 4/1."
        entries = [{"start": 4, "end": 7, "replacement": "Lee"}, {"start": 12, "end": 15, "replacement": "Bo"},
                   {"start": 19, "end": 22, "replacement": "5/9"}]
        self.assertEqual(cleaned_text({"text": text, "entries": entries}), "Dr. Lee saw Bo on 5/9.")

    def test_clean_note_has_no_hits(self):
        text = "Dr. Kim saw Ana."
        gold = {"N1": {"text": text, "spans": [{"type": "NAME", "text": "Kim", "start": 4, "end": 7}]}}
        entries = [{"start": 4, "end": 7, "replacement": "Lee"}]
        result = check(audit_of(text, entries), gold)
        self.assertEqual(result["full_string_hits"], [])
        self.assertEqual(result["labeled_spans"], 1)

    def test_a_name_left_in_place_is_listed_with_its_context(self):
        text = "Dr. Kingston saw Maria Lopez."
        gold = {"N1": {"text": text, "spans": [{"type": "NAME", "text": "Maria Lopez", "start": 17, "end": 28}]}}
        result = check(audit_of(text, []), gold)
        self.assertEqual(len(result["full_string_hits"]), 1)
        self.assertIn("Maria Lopez", result["full_string_hits"][0]["context"])
        self.assertEqual({h["part"] for h in result["name_part_hits"]}, {"Maria", "Lopez"})

    def test_a_short_string_inside_other_text_is_listed_not_decided(self):
        text = "Seen 8/1. Pain 8/10."
        gold = {"N1": {"text": text, "spans": [{"type": "DATE", "text": "8/1", "start": 5, "end": 8}]}}
        result = check(audit_of(text, [{"start": 5, "end": 8, "replacement": "2/8"}]), gold)
        self.assertEqual(len(result["full_string_hits"]), 1)

    def test_a_changed_original_text_is_refused(self):
        gold = {"N1": {"text": "other", "spans": []}}
        with self.assertRaises(ValueError):
            check(audit_of("text", []), gold)


if __name__ == "__main__":
    unittest.main()
