import unittest

from deid.eval import ablation


def span(a, b):
    return {"start": a, "end": b, "type": "NAME"}


class Pieces(unittest.TestCase):
    NOTES = {"n1": {"note_id": "n1", "spans": [span(0, 5), span(10, 15)]}}

    def test_added_spans_are_those_overlapping_nothing_before(self):
        before = {"n1": [span(0, 5)]}
        after = {"n1": [span(0, 5), span(10, 15), span(12, 20)]}
        self.assertEqual(ablation.added_spans(before, after), {"n1": [span(10, 15), span(12, 20)]})

    def test_verifier_answers_are_split_by_truth(self):
        audits = [{"note_id": "n1", "entries": [
            {**span(0, 5), "verifier": {"decision": "identifier"}},
            {**span(20, 25), "verifier": {"decision": "identifier"}},
            {**span(10, 15), "verifier": {"decision": "unsure"}},
            {**span(30, 31), "verifier": None}]}]
        self.assertEqual(ablation.verifier_table(audits, self.NOTES),
                         {"identifier": {"real": 1, "not real": 1}, "unsure": {"real": 1, "not real": 0}})

    def test_name_check_releases_are_split_by_truth(self):
        audits = [{"note_id": "n1", "entries": [], "ignored": [
            {**span(0, 5), "source": "name-use check"},
            {**span(40, 45), "source": "name-use check"},
            {**span(60, 65), "source": "rule"}]}]
        out = ablation.name_check_table(audits, self.NOTES)["released"]
        self.assertEqual(sum(out.values()), 2)
        self.assertEqual(out["real identifier (a leak a person is asked about)"], 1)
        self.assertEqual(out["not an identifier (a false positive avoided)"], 1)

    def test_every_set_names_its_files(self):
        for cfg in ablation.SETS.values():
            for key in ("notes", "version", "summary", "run", "title"):
                self.assertIn(key, cfg)


if __name__ == "__main__":
    unittest.main()
