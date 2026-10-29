"""Is this word used as a person's name here? One narrow question per doubtful occurrence.

The detector lists strings, and every occurrence of a listed string is marked. For a
name that is also an ordinary word ("Short of breath") or a condition ("Wilson disease") that
marks the wrong places too. When the detector says a name is also a word, each occurrence
without a title or label before it is shown here, with its surroundings, and the model
says whether it is a name, an ordinary word, or unsure.

Only a clear "ordinary_word" lets an occurrence stay as written, and it is recorded in the
audit and sent to the review queue so a person can check it. Anything else (a name, unsure,
a missing verdict, an unreadable or cut-off reply) keeps the occurrence replaced: a missed
name costs more than an extra replacement.
"""

import json
from dataclasses import dataclass, field

from deid.detect.client import estimate_tokens
from deid.detect.detector import FENCE, Cache, ParseError

from .verifier import candidate_lines

PROMPT_VERSION = "nu1"
DECISIONS = ("name", "ordinary_word", "unsure")

SYSTEM = """You help remove personal names from a synthetic clinical note. You are not giving medical advice.

Each candidate is a word that may be a person's name (a patient, relative or clinician) or may be an ordinary English word, or the name of a condition, device or score. It is shown with its surrounding text, with the candidate marked as <<...>>. For each one decide:
- name: here it refers to a person.
- ordinary_word: here it is an ordinary word or part of a condition, device, score or other term, and does not refer to a person (for example "<<Hunter>> syndrome", "<<Marsh>> score").
- unsure: the text does not settle it. Choose unsure whenever you are not clearly sure it is not a person.

Reply with JSON only, in this form:
{"verdicts": [{"id": <number>, "decision": "<name|ordinary_word|unsure>", "why": "<one short sentence>"}]}
Give one verdict for every candidate."""

USER_TEMPLATE = "Candidates:\n{candidates}"


def build_messages(text, candidates):
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": USER_TEMPLATE.format(candidates=candidate_lines(text, candidates))}]


def parse_verdicts(content):
    """Reply -> {candidate index: {"decision", "why"}}. Raises ParseError."""
    text = FENCE.sub("", content.strip())
    for candidate in (text, text[text.find("{"): text.rfind("}") + 1]):
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict) and isinstance(data.get("verdicts"), list):
            out = {}
            for v in data["verdicts"]:
                if isinstance(v, dict) and isinstance(v.get("id"), int) and not isinstance(v["id"], bool):
                    decision = str(v.get("decision", "")).strip().lower()
                    out[v["id"]] = {"decision": decision if decision in DECISIONS else "unsure",
                                    "why": str(v.get("why", ""))[:300]}
            return out
    raise ParseError("no JSON verdicts in reply")


@dataclass
class NameUse:
    verdicts: dict = field(default_factory=dict)  # (start, end) -> {"decision", "why"}
    asked: int = 0
    parse_error: bool = False
    truncated: bool = False
    cached: bool = False
    usage: dict = field(default_factory=dict)
    latency_s: float = 0.0


def check_name_use(client, text, candidates, cache=None):
    """One call for all of a note's doubtful occurrences. A skipped candidate, a cut-off reply or an
    unreadable one is "unsure", never "ordinary_word"."""
    if not candidates:
        return NameUse()
    messages = build_messages(text, candidates)
    cache = cache or Cache(None, PROMPT_VERSION)
    key = cache.key(client, messages[1]["content"] + "\n" + text + "\n" + PROMPT_VERSION)
    completion = cache.get(key)
    cached = completion is not None
    if not cached:
        completion = client.complete(messages)
        cache.put(key, completion)
    usage = {} if cached else dict(completion.usage)
    if not cached and "prompt_tokens" not in usage:
        usage["prompt_tokens"] = estimate_tokens(" ".join(m["content"] for m in messages))
    result = NameUse(asked=len(candidates), cached=cached, usage=usage,
                     truncated=completion.finish_reason == "length", latency_s=completion.latency_s)
    try:
        parsed = {} if result.truncated else parse_verdicts(completion.content)
    except ParseError:
        result.parse_error = True
        parsed = {}
    missing = {"decision": "unsure", "why": "no usable verdict for this occurrence"}
    for i, s in enumerate(candidates):
        result.verdicts[(s["start"], s["end"])] = parsed.get(i, missing)
    return result
