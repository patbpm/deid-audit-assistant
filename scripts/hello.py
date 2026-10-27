"""Day 1 smoke test: one chat call to a local model and one to the Meta Model API.

Usage:
    python scripts/hello.py local
    python scripts/hello.py api

Both targets are assumed to speak the OpenAI-compatible /chat/completions
format. Settings come from environment variables (see .env.example); keys are
never read from files and never printed. Use only synthetic text here.
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
        "key": None,
    },
    "api": {
        "base_url": ("META_API_BASE_URL", None),
        "model": ("META_API_MODEL", None),
        "key": "META_API_KEY",
    },
}


def require(name, default=None):
    value = os.environ.get(name, default)
    if not value:
        sys.exit(f"Missing environment variable: {name}")
    return value


def hello(target):
    cfg = TARGETS[target]
    base_url = require(*cfg["base_url"]).rstrip("/")
    model = require(*cfg["model"])
    headers = {"Content-Type": "application/json"}
    if cfg["key"]:
        headers["Authorization"] = f"Bearer {require(cfg['key'])}"

    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": PROMPT}],
            "max_tokens": 16,
            "temperature": 0,
        }
    ).encode()
    request = urllib.request.Request(
        f"{base_url}/chat/completions", data=body, headers=headers
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as err:
        sys.exit(f"{target}: HTTP {err.code} {err.reason}")
    except urllib.error.URLError as err:
        sys.exit(f"{target}: could not reach {base_url} ({err.reason})")

    reply = payload["choices"][0]["message"]["content"].strip()
    print(f"{target} ({model}): {reply!r}")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in TARGETS:
        sys.exit(__doc__)
    hello(sys.argv[1])
