"""Dictated notes: transcribe a WAV file with Muse Voice Transcribe.

    client = SpeechClient.from_env()
    transcript = transcribe_file(client, "note.wav", cache)

Uses the file endpoint documented at dev.meta.ai/docs/api-reference/voice/transcribe
(POST /v1/asr/transcribe, multipart form with a JSON `request` part and an
`audio` part). The file must be mono 16-bit PCM WAV at 16 or 24 kHz, at most
10 minutes and 32 MB; anything else is refused here, before a request is made.
The key is read from the environment and never printed. Synthetic audio only.
"""

import hashlib
import json
import os
import time
import uuid
import urllib.error
import urllib.request
import wave
from dataclasses import dataclass
from pathlib import Path

from deid.detect.client import ApiError

MODEL = "muse-voice-transcribe-1.0"
CACHE_VERSION = "asr1"
MAX_SECONDS = 600
MAX_BYTES = 32_000_000
RATES = (16000, 24000)
RETRY_STATUS = {429, 500, 502, 503, 504}


class WavError(ValueError):
    pass


@dataclass
class WavInfo:
    seconds: float
    rate: int
    size: int


def check_wav(path):
    """The file's properties, or WavError saying what to fix."""
    path = Path(path)
    size = path.stat().st_size
    if size > MAX_BYTES:
        raise WavError(f"{path.name} is {size:,} bytes; the limit is {MAX_BYTES:,}")
    try:
        with wave.open(str(path), "rb") as w:
            channels, width, rate, frames = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
    except (wave.Error, EOFError) as err:
        raise WavError(f"{path.name} is not a plain PCM WAV file ({err}); convert it first") from None
    if channels != 1 or width != 2 or rate not in RATES:
        raise WavError(f"{path.name} is {channels} channel(s), {8 * width}-bit, {rate} Hz; "
                       f"it must be mono, 16-bit, at 16000 or 24000 Hz")
    seconds = frames / rate
    if seconds > MAX_SECONDS:
        raise WavError(f"{path.name} is {seconds:.0f} s; the limit is {MAX_SECONDS} s")
    return WavInfo(seconds, rate, size)


def multipart(parts):
    """parts: [(name, filename or None, content type, bytes)] -> (body, content type header)."""
    boundary = uuid.uuid4().hex
    out = []
    for name, filename, ctype, data in parts:
        disposition = f'form-data; name="{name}"' + (f'; filename="{filename}"' if filename else "")
        out.append(f"--{boundary}\r\nContent-Disposition: {disposition}\r\nContent-Type: {ctype}\r\n\r\n".encode())
        out.append(data)
        out.append(b"\r\n")
    out.append(f"--{boundary}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={boundary}"


@dataclass
class Transcript:
    text: str
    seconds: float
    latency_s: float = 0.0
    cached: bool = False


class SpeechClient:
    def __init__(self, base_url, api_key, model=MODEL, mode="PUSH_TO_TALK", timeout=300, retries=3,
                 sleep=time.sleep):
        self.base_url = base_url.rstrip("/")
        self.model, self.mode = model, mode
        self._api_key = api_key
        self.timeout, self.retries, self._sleep = timeout, retries, sleep

    @classmethod
    def from_env(cls, mode="PUSH_TO_TALK"):
        key = os.environ.get("MODEL_API_KEY") or os.environ.get("META_API_KEY")
        if not key:
            raise ApiError("Missing environment variable: MODEL_API_KEY or META_API_KEY")
        return cls(os.environ.get("META_API_BASE_URL", "https://api.meta.ai/v1"), key, mode=mode)

    @property
    def params(self):
        return {"model": self.model, "mode": self.mode}

    def transcribe(self, path):
        data = Path(path).read_bytes()
        settings = {"mode": self.mode, "model": self.model, "audioEncoding": "WAV"}
        body, content_type = multipart([
            ("request", None, "application/json", json.dumps(settings).encode()),
            ("audio", "audio.wav", "audio/wav", data)])
        request = urllib.request.Request(
            f"{self.base_url}/asr/transcribe", data=body,
            headers={"Content-Type": content_type, "Accept": "application/json",
                     "Authorization": f"Bearer {self._api_key}"})
        for attempt in range(self.retries + 1):
            started = time.perf_counter()
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = json.load(response)
            except urllib.error.HTTPError as err:
                detail = err.read().decode(errors="replace")[:300]
                err.close()
                if err.code in RETRY_STATUS and attempt < self.retries:
                    self._sleep(2 ** attempt)
                    continue
                raise ApiError(f"HTTP {err.code} {err.reason} {detail}") from None
            except (urllib.error.URLError, TimeoutError) as err:
                if attempt < self.retries:
                    self._sleep(2 ** attempt)
                    continue
                raise ApiError(f"could not reach {self.base_url}: {err}") from None
            text = payload.get("transcript") if isinstance(payload, dict) else None
            if not isinstance(text, str):
                keys = sorted(payload) if isinstance(payload, dict) else type(payload).__name__
                raise ApiError(f"no transcript in the response (it had: {keys})")
            return text, time.perf_counter() - started


class AudioCache:
    """Transcripts keyed by the audio bytes, model and mode, so reruns cost nothing."""

    def __init__(self, directory):
        self.directory = Path(directory) if directory else None

    def key(self, client, audio_bytes):
        blob = json.dumps([CACHE_VERSION, client.params, hashlib.sha256(audio_bytes).hexdigest()])
        return hashlib.sha256(blob.encode()).hexdigest()

    def get(self, key):
        if self.directory and (self.directory / f"{key}.json").exists():
            return json.loads((self.directory / f"{key}.json").read_text(encoding="utf-8"))
        return None

    def put(self, key, value):
        if self.directory:
            self.directory.mkdir(parents=True, exist_ok=True)
            (self.directory / f"{key}.json").write_text(json.dumps(value), encoding="utf-8", newline="\n")


def transcribe_file(client, path, cache=None):
    info = check_wav(path)
    cache = cache or AudioCache(None)
    key = cache.key(client, Path(path).read_bytes())
    hit = cache.get(key)
    if hit:
        return Transcript(hit["text"], info.seconds, hit["latency_s"], cached=True)
    text, latency = client.transcribe(path)
    cache.put(key, {"text": text, "latency_s": latency})
    return Transcript(text, info.seconds, latency)
