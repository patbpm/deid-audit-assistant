"""A small OpenAI-style chat client (standard library only) and a token budget.

Providers differ only in base URL, model id, key variable and the name of the
output-token parameter. Keys come from environment variables and are never
printed or logged. Use synthetic text only.
"""

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

PROVIDERS = {
    # Meta Model API: defaults follow dev.meta.ai/docs (also used by scripts/hello.py).
    # Muse Spark always reasons, so output limits must leave room for reasoning tokens.
    "meta": {
        "base_url": ("META_API_BASE_URL", "https://api.meta.ai/v1"),
        "model": ("META_API_MODEL", "muse-spark-1.3"),
        "key": ("MODEL_API_KEY", "META_API_KEY"),
        "token_param": "max_completion_tokens",
    },
    # Any other OpenAI-compatible host (Baseten, Fireworks, Modal, self-hosted).
    "custom": {
        "base_url": ("DETECT_BASE_URL", None),
        "model": ("DETECT_MODEL", None),
        "key": ("DETECT_API_KEY",),
        "token_param": "max_tokens",
    },
}

RETRY_STATUS = {429, 500, 502, 503, 504}


class ApiError(RuntimeError):
    pass


@dataclass
class Completion:
    content: str
    usage: dict = field(default_factory=dict)
    latency_s: float = 0.0
    finish_reason: str = ""


class ChatClient:
    def __init__(self, base_url, model, api_key, token_param, max_output_tokens=4096,
                 timeout=120, retries=3, sleep=time.sleep):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self.token_param = token_param
        self.max_output_tokens = max_output_tokens
        self.timeout = timeout
        self.retries = retries
        self._sleep = sleep

    @property
    def params(self):
        return {self.token_param: self.max_output_tokens}

    @classmethod
    def from_env(cls, provider, max_output_tokens=4096):
        cfg = PROVIDERS[provider]

        def need(name, default):
            value = os.environ.get(name, default)
            if not value:
                raise ApiError(f"Missing environment variable: {name}")
            return value

        key = next((os.environ[n] for n in cfg["key"] if os.environ.get(n)), None)
        if not key:
            raise ApiError(f"Missing environment variable: {' or '.join(cfg['key'])}")
        return cls(need(*cfg["base_url"]), need(*cfg["model"]), key, cfg["token_param"],
                   max_output_tokens)

    def complete(self, messages, max_output_tokens=None):
        """max_output_tokens overrides the client's limit for this call only. Nothing shared is changed,
        so calls from several threads cannot disturb each other or the cache keys."""
        params = {self.token_param: max_output_tokens or self.max_output_tokens}
        body = json.dumps({"model": self.model, "messages": messages, **params}).encode()
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self._api_key}"})
        for attempt in range(self.retries + 1):
            started = time.perf_counter()
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = json.load(response)
            except urllib.error.HTTPError as err:
                detail = err.read().decode(errors="replace")[:300]
                if err.code in RETRY_STATUS and attempt < self.retries:
                    self._sleep(2 ** attempt)
                    continue
                raise ApiError(f"HTTP {err.code} {err.reason} {detail}") from None
            except (urllib.error.URLError, TimeoutError) as err:
                if attempt < self.retries:
                    self._sleep(2 ** attempt)
                    continue
                raise ApiError(f"could not reach {self.base_url}: {err}") from None
            choice = payload["choices"][0]
            return Completion(
                content=(choice["message"].get("content") or ""),
                usage=payload.get("usage") or {},
                latency_s=time.perf_counter() - started,
                finish_reason=choice.get("finish_reason") or "",
            )


class LargerLimitRetry:
    """Wraps a ChatClient: a reply cut off at the output limit is asked again once
    with a larger limit (Muse Spark reasons, so a long note can use up a small
    one). Cache keys use the wrapped client's normal limit, and the usage of both
    attempts is counted."""

    def __init__(self, inner, retry_limit):
        self.inner, self.retry_limit = inner, retry_limit

    model = property(lambda self: self.inner.model)
    params = property(lambda self: self.inner.params)

    def complete(self, messages):
        first = self.inner.complete(messages)
        if first.finish_reason != "length" or not self.retry_limit or self.retry_limit <= self.inner.max_output_tokens:
            return first
        second = self.inner.complete(messages, max_output_tokens=self.retry_limit)
        usage = dict(second.usage)
        for key in ("prompt_tokens", "completion_tokens"):
            usage[key] = first.usage.get(key, 0) + second.usage.get(key, 0)
        return Completion(second.content, usage, first.latency_s + second.latency_s, second.finish_reason)


def estimate_tokens(text):
    """Rough guess (about 4 characters per token). Only for dry runs and as a
    fallback when a response carries no usage figures."""
    return max(1, len(text) // 4)


class Budget:
    """Stops a run once a token cap is reached. Dollar cost is reported only if
    prices (USD per million tokens) are supplied; none are assumed."""

    def __init__(self, max_total_tokens, price_in=None, price_out=None):
        self.max_total_tokens = max_total_tokens
        self.price_in, self.price_out = price_in, price_out
        self.tokens_in = self.tokens_out = 0

    def add(self, usage, fallback_in=0):
        self.tokens_in += usage.get("prompt_tokens", fallback_in)
        self.tokens_out += usage.get("completion_tokens", 0)

    @property
    def total(self):
        return self.tokens_in + self.tokens_out

    @property
    def exceeded(self):
        return bool(self.max_total_tokens) and self.total >= self.max_total_tokens

    @property
    def cost_usd(self):
        if self.price_in is None or self.price_out is None:
            return None
        return (self.tokens_in * self.price_in + self.tokens_out * self.price_out) / 1e6
