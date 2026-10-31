import json
import tempfile
import time
import unittest
from pathlib import Path

from deid.agent.pipeline import detect_and_verify, review_and_clean
from deid.agent.verifier import PROMPT_VERSION as VERIFY_VERSION
from deid.app import replay, samples
from deid.app.jobs import JobStore
from deid.audit.verify import LOW_CONFIDENCE
from deid.detect.client import Budget
from deid.detect.detector import Cache
from deid.redteam.prompt import PROMPT_VERSION as REDTEAM_VERSION
from deid.synth import generate
from tests.test_agent import ScriptedModel


class Recorded(ScriptedModel):
    """The scripted model, wearing the model name and parameters the recording is keyed by."""
    model, params = replay.MODEL, replay.PARAMS


def wait(store, job_id, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        job = store.get(job_id)
        if job["state"] in ("done", "failed"):
            return job
        time.sleep(0.02)
    raise AssertionError("timed out")


class ReplayMode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        sample = generate.generate_notes(generate.DEFAULT_SEED, 1)
        model = Recorded(sample)  # stands in for the hosted model in the "live" run being recorded
        notes = [{"note_id": n["note_id"], "patient_id": n["patient_id"], "text": n["text"]} for n in sample]
        src = root / "live-cache"
        budget = Budget(10 ** 9)
        batch, _ = detect_and_verify(notes, model, Cache(src / "cache"), Cache(src / "cache-verify", VERIFY_VERSION),
                                     budget, LOW_CONFIDENCE)
        review_and_clean(batch, model, Cache(src / "cache-redteam", REDTEAM_VERSION), budget, 0, LOW_CONFIDENCE, 2)
        cls.meta, _ = replay.record(src, root / "data-replay")
        cls.recording = root / "data-replay"
        cls.calls_while_recording = len(model.calls)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_job(self, data, name="notes.jsonl"):
        store = JobStore(Path(self.tmp.name) / "jobs", replay.replay_backend(self.recording))
        job = store.create()
        store.add_file(job["id"], name, data)
        store.start(job["id"], {})
        return wait(store, job["id"])

    def test_the_recording_names_what_it_holds(self):
        self.assertEqual(self.meta["notes"], ["N0001", "N0002", "N0003", "N0004"])
        self.assertEqual(self.meta["model"], "muse-spark-1.3")
        self.assertEqual({p.name for p in self.recording.iterdir() if p.is_dir()}, {"cache", "cache-verify", "cache-redteam"})

    def test_sample_notes_run_with_no_model_call_and_no_hosted_flag(self):
        (_, data), = samples.notes()
        job = self.run_job(data, "sample-notes.jsonl")
        self.assertEqual(job["state"], "done", job.get("error"))
        self.assertFalse(job["hosted"])
        self.assertEqual(job["result"]["notes"], 4)
        self.assertEqual(job["result"]["not_cleaned"], 0)
        self.assertTrue(job["result"]["assessed"])
        self.assertGreater(job["result"]["replacements"], 0)

    def test_other_text_is_refused_with_the_reason_never_guessed(self):
        job = self.run_job(b"Patient: Kim Reyes\nSeen 2025-03-04.\n", "mine.txt")
        self.assertEqual(job["state"], "failed")
        self.assertIn("Replay mode only holds the replies saved for the sample notes", job["error"])

    def test_backend_says_it_is_a_replay(self):
        backend = replay.replay_backend(self.recording)
        self.assertTrue(backend.describe()["replay"])
        self.assertFalse(backend.hosted)
        self.assertIn("no model is called", backend.label.lower())

    def test_a_missing_recording_is_a_clear_error(self):
        with self.assertRaises(SystemExit) as caught:
            replay.replay_backend(Path(self.tmp.name) / "nothing-here")
        self.assertIn("no recording", str(caught.exception))

    def test_the_client_refuses_every_call(self):
        with self.assertRaises(LookupError):
            replay.ReplayClient().complete([])


if __name__ == "__main__":
    unittest.main()
