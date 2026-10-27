"""Template rendering that records label offsets as text is appended.

A template is plain text with {token} placeholders. A resolver maps each token
to a list of Pieces; labeled Pieces become spans, so offsets are correct by
construction and validate_spans only guards against bugs.
"""

import re
from dataclasses import dataclass

TOKEN = re.compile(r"\{(\w+)\}")


@dataclass(frozen=True)
class Piece:
    text: str
    label: str = ""  # identifier type (NAME, DATE, ...); empty for plain text
    subtype: str = ""
    entity: str = ""
    norm: str = ""  # normalised value (ISO date for DATE spans)


def plain(text):
    return Piece(text)


def render(template, resolve):
    """Return (text, spans). resolve(token) -> list[Piece]."""
    out = []
    spans = []
    length = 0
    cursor = 0
    for match in TOKEN.finditer(template):
        literal = template[cursor:match.start()]
        out.append(literal)
        length += len(literal)
        for piece in resolve(match.group(1)):
            if piece.label:
                span = {
                    "start": length,
                    "end": length + len(piece.text),
                    "type": piece.label,
                    "subtype": piece.subtype,
                    "entity": piece.entity,
                    "text": piece.text,
                }
                if piece.norm:
                    span["norm"] = piece.norm
                spans.append(span)
            out.append(piece.text)
            length += len(piece.text)
        cursor = match.end()
    tail = template[cursor:]
    out.append(tail)
    return "".join(out), spans


def validate_spans(text, spans):
    """Raise ValueError if spans are out of bounds, mismatched, or overlapping."""
    previous_end = 0
    for span in spans:
        start, end = span["start"], span["end"]
        if not 0 <= start < end <= len(text):
            raise ValueError(f"span out of bounds: {span}")
        if text[start:end] != span["text"]:
            raise ValueError(f"span text mismatch: {span} vs {text[start:end]!r}")
        if start < previous_end:
            raise ValueError(f"overlapping or unsorted span: {span}")
        previous_end = end
