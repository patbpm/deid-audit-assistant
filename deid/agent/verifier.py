"""Second look at the spans the detector was unsure about.

Only uncertain spans are sent (low or missing confidence, or a shape the rule
checks dislike), each with a short stretch of surrounding text. The verifier
can confirm a span or raise doubt; it never removes one. A span it doubts stays
replaced and goes to a person, because a missed identifier costs more than an
extra replacement.
"""

import json
from dataclasses import dataclass, field

from deid.audit.verify import LOW_CONFIDENCE, format_problems
from deid.detect.client import estimate_tokens
from deid.detect.detector import FENCE, Cache, ParseError

PROMPT_VERSION = "vf1"
CONTEXT_CHARS = 90
DECISIONS = ("identifier", "not_identifier", "unsure")

SYSTEM = """You double-check candidate identifiers in a synthetic clinical note before they are removed. You are not giving medical advice.

Each candidate has an id, its text, a type (NAME, DATE, ID, PHONE, EMAIL, ADDRESS) and the surrounding text with the candidate marked as <<...>>. Decide for each one:
- identifier: it is an identifier of the given type that should be removed (a person's name, a date tied to a person or encounter, a record, account, insurance or social security number, a phone or fax number, an email address, a street address or a town).
- not_identifier: it is something else, such as a drug, dose, lab value, blood pressure, pain score, diagnosis code, room number, age under 90, a disease named after a person, or a common word.
- unsure: the text does not settle it.

Reply with JSON only, in this form:
{"verdicts": [{"id": <number>, "decision": "<identifier|not_identifier|unsure>", "why": "<one short sentence>"}]}
Give one verdict for every candidate."""

USER_TEMPLATE = "Candidates:\n{candidates}"


def select_uncertain(text, spans, low=LOW_CONFIDENCE):
    """Spans a second look is worth paying for."""
    return [s for s in spans
            if s.get("confidence") is None or s["confidence"] < low
            or format_problems(s["type"], text[s["start"]:s["end"]])]


def candidate_lines(text, candidates):
    lines = []
    for i, s in enumerate(candidates):
        before = text[max(0, s["start"] - CONTEXT_CHARS):s["start"]]
        after = text[s["end"]:s["end"] + CONTEXT_CHARS]
        shown = f'{before}<<{text[s["start"]:s["end"]]}>>{after}'.replace("\n", " ")
        lines.append(f'{i}. type={s["type"]} text={json.dumps(text[s["start"]:s["end"]])} context={json.dumps(shown)}')
    return "\n".join(lines)


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
class Verification:
    verdicts: dict = field(default_factory=dict)  # (start, end) -> {"decision", "why"}
    asked: int = 0
    parse_error: bool = False
    truncated: bool = False
    cached: bool = False
    usage: dict = field(default_factory=dict)
    latency_s: float = 0.0


def verify_spans(client, text, candidates, cache=None):
    """One call for all of a note's uncertain spans. A candidate the model skips,
    or an unreadable reply, becomes "unsure": silence is never a confirmation."""
    if not candidates:
        return Verification()
    messages = build_messages(text, candidates)
    cache = cache or Cache(None, PROMPT_VERSION)
    key = cache.key(client, messages[1]["content"] + "\n" + text)
    completion = cache.get(key)
    cached = completion is not None
    if not cached:
        completion = client.complete(messages)
        cache.put(key, completion)
    usage = {} if cached else dict(completion.usage)
    if not cached and "prompt_tokens" not in usage:
        usage["prompt_tokens"] = estimate_tokens(" ".join(m["content"] for m in messages))
    result = Verification(asked=len(candidates), cached=cached, usage=usage,
                          truncated=completion.finish_reason == "length", latency_s=completion.latency_s)
    try:
        parsed = parse_verdicts(completion.content)
    except ParseError:
        result.parse_error = True
        parsed = {}
    missing = {"decision": "unsure", "why": "the verifier gave no verdict for this span"}
    for i, s in enumerate(candidates):
        result.verdicts[(s["start"], s["end"])] = parsed.get(i, missing)
    return result
