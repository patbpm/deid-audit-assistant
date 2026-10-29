import math
import random
import tempfile
import unittest
import wave
from pathlib import Path

from deid.ingest import degrade


def tone(path, seconds=1.0, rate=16000, freq=440.0, amplitude=8000):
    frames = b"".join(int(amplitude * math.sin(2 * math.pi * freq * i / rate)).to_bytes(2, "little", signed=True)
                      for i in range(int(seconds * rate)))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)
    return path


def seconds(path):
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


class AudioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.clean = tone(self.dir / "clean.wav")

    def test_noise_is_added_at_the_requested_level_and_is_repeatable(self):
        for snr in (6.0, 12.0, 20.0):
            noisy = degrade.add_noise_wav(self.clean, self.dir / f"n{snr}.wav", snr, seed=1)
            self.assertAlmostEqual(degrade.measured_snr_db(self.clean, noisy), snr, delta=1.0)
        a = degrade.add_noise_wav(self.clean, self.dir / "a.wav", 12, seed=1).read_bytes()
        b = degrade.add_noise_wav(self.clean, self.dir / "b.wav", 12, seed=1).read_bytes()
        c = degrade.add_noise_wav(self.clean, self.dir / "c.wav", 12, seed=2).read_bytes()
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertEqual(seconds(self.dir / "a.wav"), 1.0)           # length and format unchanged

    def test_noise_keeps_the_format_the_speech_service_requires(self):
        from deid.ingest.audio import check_wav
        noisy = degrade.add_noise_wav(self.clean, self.dir / "n.wav", 10, seed=3)
        self.assertEqual(check_wav(noisy).rate, 16000)

    def test_other_formats_are_refused(self):
        stereo = self.dir / "stereo.wav"
        with wave.open(str(stereo), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\x00\x00" * 200)
        with self.assertRaises(ValueError):
            degrade.add_noise_wav(stereo, self.dir / "x.wav")

    def test_joining_adds_the_lengths_and_the_pauses(self):
        other = tone(self.dir / "other.wav", 2.0)
        joined = degrade.join_wavs([self.clean, other], self.dir / "joined.wav", pause_seconds=0.5)
        self.assertAlmostEqual(seconds(joined), 1.0 + 2.0 + 2 * 0.5)
        with self.assertRaises(ValueError):
            degrade.join_wavs([self.clean, tone(self.dir / "r24.wav", 1.0, rate=24000)], self.dir / "bad.wav")


class ImageTests(unittest.TestCase):
    def test_a_rougher_smaller_jpeg_is_written_repeatably(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow is only needed to build test data")
        from deid.ingest.render import render_scan
        with tempfile.TemporaryDirectory() as tmp:
            page = render_scan("Patient: Kim Reyes\nMRN: 1234567", Path(tmp) / "p.png", seed=1)
            a = degrade.degrade_image(page, Path(tmp) / "a.jpg", seed=2).read_bytes()
            b = degrade.degrade_image(page, Path(tmp) / "b.jpg", seed=2).read_bytes()
            c = degrade.degrade_image(page, Path(tmp) / "c.jpg", seed=3).read_bytes()
            self.assertEqual(a, b)
            self.assertNotEqual(a, c)
            with Image.open(Path(tmp) / "a.jpg") as small, Image.open(page) as big:
                self.assertEqual(small.format, "JPEG")
                self.assertLess(small.width, big.width)
            self.assertLess(len(a), page.stat().st_size)


if __name__ == "__main__":
    unittest.main()
