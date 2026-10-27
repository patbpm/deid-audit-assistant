"""Day 1 smoke test: one chat call to a local model or to the Meta Model API.

Usage:
    python scripts/hello.py local
    python scripts/hello.py api

Both targets use the OpenAI-style /chat/completions format. Settings come from
environment variables (see .env.example); keys are never read from files and
never printed. Use only synthetic text here.

The API target defaults follow Meta's published docs (dev.meta.ai/docs): base
URL https://api.meta.ai/v1, model muse-spark-1.3, key in MODEL_API_KEY. Only
the key is required; META_API_BASE_URL and META_API_MODEL override the rest.
"""

import json
import os
import sys
import urllib.error
import urllib.request

PROMPT = "Reply with the single word: hello"

TARGETS = {
    "local": {
        "base_url": ("LOCAL_BASE_URL", "http://localhost:11434/v1"),
        "model": ("LOCAL_MODEL", None),
        "key": (),
        # Local servers expect max_tokens.
        "params": {"max_tokens": 16, "temperature": 0},
    },
    "api": {
        "base_url": ("META_API_BASE_URL", "https://api.meta.ai/v1"),
        "model": ("META_API_MODEL", "muse-spark-1.3"),
        "key": ("MODEL_API_KEY", "META_API_KEY"),
        # Muse Spark always reasons, so leave room for reasoning tokens. The
        # docs say max_tokens is deprecated and temperature is best left unset.
        "params": {"max_completion_tokens": 1024},
    },
}


def require(name, default=None):
    value = os.environ.get(name, default)
    if not value:
        sys.exit(f"Missing environment variable: {name}")
    return value


def read_key(names):
    for name in names:
        if os.environ.get(name):
            return os.environ[name]
    sys.exit(f"Missing environment variable: {' or '.join(names)}")


def hello(target):
    cfg = TARGETS[target]
    base_url = require(*cfg["base_url"]).rstrip("/")
    model = require(*cfg["model"])
    headers = {"Content-Type": "application/json"}
    if cfg["key"]:
        headers["Authorization"] = f"Bearer {read_key(cfg['key'])}"

    body = json.dumps(
        {"model": model, "messages": [{"role": "user", "content": PROMPT}], **cfg["params"]}
    ).encode()
    request = urllib.request.Request(
        f"{base_url}/chat/completions", data=body, headers=headers
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as err:
        detail = err.read().decode(errors="replace")[:300]
        sys.exit(f"{target}: HTTP {err.code} {err.reason} {detail}")
    except urllib.error.URLError as err:
        sys.exit(f"{target}: could not reach {base_url} ({err.reason})")

    reply = (payload["choices"][0]["message"].get("content") or "").strip()
    print(f"{target} ({model}): {reply!r}")
    usage = payload.get("usage")
    if usage:
        print(f"tokens: {usage}")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in TARGETS:
        sys.exit(__doc__)
    hello(sys.argv[1])
