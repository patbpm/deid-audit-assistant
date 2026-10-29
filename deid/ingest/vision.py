"""Scanned notes: read the text from a page image with a vision-capable chat model.

    text = read_scan(client, "page.png", cache)

Sends the image as a base64 data URL in a user message (documented at
dev.meta.ai/docs/image-understanding; muse-spark-1.3 accepts images through
chat completions). The model is asked only to copy the text; the output then goes
through the same de-identification steps as typed notes. Reading errors become
errors in the text, so they show up as missed or shifted identifiers later;
nothing is corrected silently. Synthetic images only.
"""

import base64
import hashlib
import re
from pathlib import Path

from deid.detect.detector import Cache

PROMPT_VERSION = "ocr1"
MAX_BYTES = 50_000_000  # inline image limit in Meta's docs
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}

SYSTEM = """You transcribe scanned clinical documents. The page is synthetic. You are not giving medical advice.

Copy all the text on the page exactly as written, character for character:
- Keep the line breaks and the order of the lines.
- Do not correct spelling, fix numbers, expand abbreviations, translate or summarize.
- Write [illegible] where text cannot be read.
- Do not add comments, headings or code fences.

Reply with the transcribed text only."""

USER_TEXT = "Transcribe this page."
FENCE = re.compile(r"^```[a-zA-Z]*\s*\n|\n?```\s*$")


class ImageError(ValueError):
    pass


def load_image(path):
    """(bytes, mime type) or ImageError."""
    path = Path(path)
    mime = MIME.get(path.suffix.lower())
    if not mime:
        raise ImageError(f"{path.name}: use one of {', '.join(sorted(MIME))}")
    data = path.read_bytes()
    if len(data) > MAX_BYTES:
        raise ImageError(f"{path.name} is {len(data):,} bytes; the limit is {MAX_BYTES:,}")
    return data, mime


def build_messages(data, mime):
    url = f"data:{mime};base64,{base64.b64encode(data).decode()}"
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": [{"type": "text", "text": USER_TEXT},
                                         {"type": "image_url", "image_url": {"url": url}}]}]


def clean_text(content):
    return FENCE.sub("", content.strip("\r\n")).rstrip()


class Scan:
    def __init__(self, text, usage, latency_s, cached, truncated):
        self.text, self.usage, self.latency_s, self.cached, self.truncated = text, usage, latency_s, cached, truncated


def read_scan(client, path, cache=None):
    data, mime = load_image(path)
    cache = cache or Cache(None, PROMPT_VERSION)
    key = cache.key(client, hashlib.sha256(data).hexdigest())
    completion = cache.get(key)
    cached = completion is not None
    if not cached:
        completion = client.complete(build_messages(data, mime))
        cache.put(key, completion)
    return Scan(clean_text(completion.content), {} if cached else dict(completion.usage),
                completion.latency_s, cached, completion.finish_reason == "length")
