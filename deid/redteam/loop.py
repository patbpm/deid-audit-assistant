"""Clean, review, and send leftovers back: the red-team feedback loop.

    result = harden(replacer, note, client, cache)

Each round replaces the current spans, shows the masked result to the reviewer,
and adds any leftover identifier it found to the spans for another pass. The loop
stops when a round finds nothing new or after max_rounds extra passes.

Clues that are not leftover identifiers (a rare condition, an occupation, a small
place) are not edited automatically: changing clinical content could change its
meaning. They are returned as review items for a person to decide.
"""

from dataclasses import dataclass, field

from deid.replace.engine import clean_spans

from .assess import assess_note, masked_view


@dataclass
class HardenResult:
    text: str
    changes: list
    spans: list
    assessments: list = field(default_factory=list)  # one per round, first = before any feedback
    added: list = field(default_factory=list)        # spans added from the reviewer's leftovers
    review: list = field(default_factory=list)       # clues a person should look at

    @property
    def risk(self):
        return self.assessments[-1].risk


def _covered(span, spans):
    return any(span["start"] < s["end"] and s["start"] < span["end"] for s in spans)


def new_leftover_spans(assessment, spans):
    """Spans for located leftover identifiers that no current span covers."""
    found = []
    for clue in assessment.clues:
        if clue["category"] != "LEFTOVER" or not clue["type"]:
            continue
        for start, end in clue["ranges"]:
            span = {"start": start, "end": end, "type": clue["type"]}
            if not _covered(span, spans + found):
                found.append(span)
    return found


def review_items(assessment):
    return [{"text": c["text"], "category": c["category"], "why": c["why"]}
            for c in assessment.clues if c["category"] != "LEFTOVER" or not c["type"]]


def harden(replacer, note, client, cache=None, max_rounds=2):
    """note: {"text", "spans", "patient_key"?, "note_id"?}. Returns a HardenResult."""
    spans = clean_spans(note["text"], note["spans"])
    result = HardenResult("", [], spans)
    for round_number in range(max_rounds + 1):
        text, changes = replacer.apply({**note, "spans": spans})
        assessment = assess_note(client, masked_view(note["text"], changes), cache)
        result.text, result.changes, result.spans = text, changes, spans
        result.assessments.append(assessment)
        result.review = review_items(assessment)
        extra = new_leftover_spans(assessment, spans) if round_number < max_rounds else []
        if not extra:
            break
        result.added.extend(extra)
        spans = clean_spans(note["text"], spans + extra)
    return result
