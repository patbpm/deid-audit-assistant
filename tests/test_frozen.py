"""Guards for the frozen dataset and test split (data/frozen.json).

If one of these fails, either something changed that should not have, or the
dataset was changed on purpose. In the second case the test set is no longer the
one earlier results were measured on: re-run every baseline and update
data/frozen.json deliberately (python -m deid.eval.freeze --write).
"""

import tempfile
import unittest
from pathlib import Path

from deid.eval import freeze
from deid.eval.run import DEV_MAX_PATIENT
from deid.synth import generate

FROZEN = freeze.load()


class FrozenDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        notes = generate.generate_notes(FROZEN["seed"], FROZEN["patients"])
        manifest = generate.write_notes(notes, cls.tmp.name, FROZEN["seed"], FROZEN["patients"])
        cls.current = freeze.describe(Path(cls.tmp.name) / generate.NOTES_FILE)
        cls.manifest = manifest

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_generator_still_produces_the_frozen_dataset(self):
        self.assertEqual(freeze.differences(FROZEN, self.current), {},
                         "generator output differs from data/frozen.json "
                         f"(frozen on Python {FROZEN['python_version_generated_with']})")

    def test_generator_version_and_span_count_unchanged(self):
        self.assertEqual(self.manifest["generator_version"], FROZEN["generator_version"])
        self.assertEqual(self.manifest["spans"], FROZEN["spans"])

    def test_split_boundary_is_unchanged(self):
        self.assertEqual(DEV_MAX_PATIENT, FROZEN["dev_max_patient"])
        self.assertEqual(FROZEN["dev_patients"] + FROZEN["test_patients"], FROZEN["patients"])
        self.assertEqual(FROZEN["dev_notes"] + FROZEN["test_notes"], FROZEN["notes"])
        self.assertEqual(FROZEN["test_notes"], 400)

    def test_generated_files_on_disk_match_when_present(self):
        if not freeze.NOTES_PATH.exists():
            self.skipTest("data/generated/notes.jsonl not generated here")
        self.assertEqual(freeze.differences(FROZEN, freeze.describe(freeze.NOTES_PATH)), {},
                         "data/generated/notes.jsonl is not the frozen dataset; "
                         "regenerate with: python -m deid.synth.generate")


if __name__ == "__main__":
    unittest.main()
