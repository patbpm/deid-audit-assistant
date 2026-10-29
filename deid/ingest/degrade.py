"""Make the synthetic test audio and page images harder, in ways real ones are.

Audio: background noise mixed in at a chosen signal-to-noise ratio. Images: more
tilt, blur, speckle, a shadow across the page, a lower resolution and heavy JPEG
compression. All seeded, so the same inputs give the same files. Still synthetic
and still clean in many ways (one voice, one font, no handwriting): harder, not
real. Pillow is needed only for the image part.
"""

import array
import math
import random
import wave
from pathlib import Path


def add_noise_wav(src, dst, snr_db=12.0, seed=0):
    """Mix white noise into a mono 16-bit WAV so that signal power / noise power = snr_db."""
    with wave.open(str(src), "rb") as w:
        params = w.getparams()
        samples = array.array("h")
        samples.frombytes(w.readframes(w.getnframes()))
    if params.nchannels != 1 or params.sampwidth != 2:
        raise ValueError("expected a mono 16-bit WAV")
    power = sum(s * s for s in samples) / max(1, len(samples))
    sigma = math.sqrt(power / (10 ** (snr_db / 10)))
    rng = random.Random(seed)
    noisy = array.array("h", (max(-32768, min(32767, int(s + rng.gauss(0, sigma)))) for s in samples))
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dst), "wb") as out:
        out.setparams(params)
        out.writeframes(noisy.tobytes())
    return Path(dst)


def measured_snr_db(clean, noisy):
    """Signal-to-noise ratio of a noisy WAV against its clean source, for checks."""
    def load(path):
        with wave.open(str(path), "rb") as w:
            data = array.array("h")
            data.frombytes(w.readframes(w.getnframes()))
        return data
    a, b = load(clean), load(noisy)
    signal = sum(x * x for x in a) / len(a)
    noise = sum((y - x) ** 2 for x, y in zip(a, b)) / len(a)
    return 10 * math.log10(signal / noise)


def join_wavs(sources, dst, pause_seconds=1.0):
    """Join mono 16-bit WAV files of the same rate into one longer recording."""
    sources = [Path(s) for s in sources]
    with wave.open(str(sources[0]), "rb") as first:
        params = first.getparams()
    frames = bytearray()
    silence = b"\x00\x00" * int(pause_seconds * params.framerate)
    for src in sources:
        with wave.open(str(src), "rb") as w:
            if w.getframerate() != params.framerate:
                raise ValueError("all files must have the same sample rate")
            frames += w.readframes(w.getnframes()) + silence
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dst), "wb") as out:
        out.setparams(params)
        out.writeframes(bytes(frames))
    return Path(dst)


def degrade_image(src, dst, seed=0, angle=1.8, blur=1.0, scale=0.65, quality=30, speckle=0.004):
    """A rougher copy of a page image: tilt, blur, speckle, a shadow, downscaled, saved as JPEG."""
    from PIL import Image, ImageFilter
    rng = random.Random(seed)
    image = Image.open(src).convert("L")
    image = image.rotate(rng.choice((-1, 1)) * rng.uniform(angle * 0.6, angle), resample=Image.BICUBIC, fillcolor=255)
    image = image.filter(ImageFilter.GaussianBlur(blur))
    pixels = image.load()
    width, height = image.size
    for y in range(height):  # a shadow that darkens toward one side
        for x in range(0, width, 1):
            shade = int(60 * (x / width) ** 2)
            pixels[x, y] = max(0, pixels[x, y] - shade)
    for _ in range(int(width * height * speckle)):
        pixels[rng.randrange(width), rng.randrange(height)] = rng.randrange(60, 200)
    image = image.resize((int(width * scale), int(height * scale)), Image.BILINEAR)
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    image.save(dst, "JPEG", quality=quality)
    return Path(dst)
