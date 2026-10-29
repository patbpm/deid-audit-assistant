"""Detect identifiers in one note with a chat model; cache responses on disk."""

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .client import Completion, estimate_tokens
from .matching import clean_items, find_spans
from .prompt import PROMPT_VERSION, build_messages

FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class ParseError(ValueError):
    pass


def parse_items(content):
    """The model's reply -> list of raw item dicts. Accepts fenced JSON, a bare
    list, or JSON surrounded by stray text. Raises ParseError otherwise."""
    text = FENCE.sub("", content.strip())
    for candidate in (text, text[text.find("{"): text.rfind("}") + 1]):
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict) and isinstance(data.get("identifiers"), list):
            return data["identifiers"]
        if isinstance(data, list):
            return data
    raise ParseError("no JSON identifier list in reply")


class Cache:
    """Raw replies keyed by model, parameters, prompt version and note text, so
    reruns and re-matching cost nothing."""

    def __init__(self, directory, version=PROMPT_VERSION):
        self.directory = Path(directory) if directory else None
        self.version = version  # the prompt version whose replies these are

    def key(self, client, text):
        blob = json.dumps([self.version, client.model, client.params, text], sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()

    def get(self, key):
        if not self.directory or not (self.directory / f"{key}.json").exists():
            return None
        data = json.loads((self.directory / f"{key}.json").read_text(encoding="utf-8"))
        if data.get("finish_reason") == "length":
            return None  # cut off at the output limit: incomplete, so ask again
        return Completion(**data)

    def put(self, key, completion):
        if self.directory and completion.finish_reason != "length":
            self.directory.mkdir(parents=True, exist_ok=True)
            data = {k: getattr(completion, k) for k in ("content", "usage", "latency_s", "finish_reason")}
            (self.directory / f"{key}.json").write_text(json.dumps(data), encoding="utf-8", newline="\n")


@dataclass
class NoteResult:
    spans: list
    unmatched: list = field(default_factory=list)
    dropped_items: int = 0
    parse_error: bool = False
    truncated: bool = False
    cached: bool = False
    usage: dict = field(default_factory=dict)
    latency_s: float = 0.0


def detect_note(client, text, cache=None):
    """Send one note (text only) and return spans located in it."""
    messages = build_messages(text)
    cache = cache or Cache(None)
    key = cache.key(client, text)
    completion = cache.get(key)
    cached = completion is not None
    if not cached:
        completion = client.complete(messages)
        cache.put(key, completion)
    usage = dict(completion.usage)
    if cached:
        usage = {}  # a cache hit costs nothing now
    elif "prompt_tokens" not in usage:
        usage["prompt_tokens"] = estimate_tokens(" ".join(m["content"] for m in messages))
    truncated = completion.finish_reason == "length"
    try:
        raw = parse_items(completion.content)
    except ParseError:
        return NoteResult([], parse_error=True, truncated=truncated, cached=cached,
                          usage=usage, latency_s=completion.latency_s)
    items, dropped = clean_items(raw)
    spans, unmatched = find_spans(text, items)
    return NoteResult(spans, unmatched, dropped, False, truncated, cached, usage,
                      completion.latency_s)
