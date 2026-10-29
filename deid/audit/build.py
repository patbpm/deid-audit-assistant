"""Build the audit record for a note: one evidence-trace entry per change.

Every entry links a replacement to the original span (character offsets), the
detector that found it, its confidence, the other detectors that agree, the
rule that rewrote it, and the checks' decision. A review queue lists what a
person should look at: spans a check objected to, strings the model listed but
that were not found in the note, and the red-team reviewer's clues.
"""

from collections import Counter

from .verify import LOW_CONFIDENCE, verify_span


def _overlap(a, b):
    return a["start"] < b["end"] and b["start"] < a["end"]


def build_note_audit(note_id, text, spans, changes, detector, others=None, unmatched=(),
                     assessment=None, low=LOW_CONFIDENCE):
    """spans: the detector's spans (start, end, type, confidence?); changes: from
    Replacer.apply; others: {detector name: spans} from detectors that also ran;
    assessment: {"risk", "clues"} from the red-team reviewer, or None."""
    confidence = {(s["start"], s["end"]): s.get("confidence") for s in spans}
    entries, review = [], []
    for i, c in enumerate(changes):
        agree = [name for name, other in (others or {}).items()
                 if any(_overlap(c, o) for o in other)]
        conf = confidence.get((c["start"], c["end"]))
        checks = verify_span(c, conf, low)
        entry = {
            "id": f"{note_id}:{i}", "type": c["type"],
            "start": c["start"], "end": c["end"], "new_start": c["new_start"], "new_end": c["new_end"],
            "original": c["original"], "replacement": c["replacement"], "rule": c["rule"],
            "detector": detector, "confidence": conf, "also_found_by": agree,
            "checks": checks, "status": checks["decision"],
        }
        entries.append(entry)
        if checks["decision"] == "review":
            review.append({"kind": "span", "ref": entry["id"], "reasons": checks["reasons"]})
    dropped = [s for s in spans if not any(_overlap(s, c) for c in changes)]
    for s in dropped:  # a prediction that produced no change; only possible if it was malformed
        review.append({"kind": "dropped-span", "ref": None,
                       "reasons": [f"{s['type']} span {s['start']}-{s['end']} produced no replacement"]})
    for string in unmatched:
        review.append({"kind": "unmatched", "ref": None,
                       "reasons": [f"the model listed {string!r} but it was not found in the note"]})
    risk = None
    if assessment:
        risk = assessment["risk"]
        for clue in assessment["clues"]:
            review.append({"kind": "clue", "ref": None, "category": clue["category"], "text": clue["text"],
                           "ranges": [list(r) for r in clue["ranges"]],
                           "reasons": [clue.get("why") or clue["category"]]})
        if risk in ("unknown",):
            review.append({"kind": "risk", "ref": None, "reasons": ["the red-team reply could not be read"]})
    return {"note_id": note_id, "text": text, "entries": entries, "review": review,
            "risk": risk, "assessed": assessment is not None}


def summarize(audits):
    entries = [e for a in audits for e in a["entries"]]
    return {
        "notes": len(audits),
        "changes": len(entries),
        "by_type": dict(sorted(Counter(e["type"] for e in entries).items())),
        "by_rule": dict(sorted(Counter(e["rule"] for e in entries).items())),
        "changes_needing_review": sum(e["status"] == "review" for e in entries),
        "review_items": sum(len(a["review"]) for a in audits),
        "notes_with_review_items": sum(bool(a["review"]) for a in audits),
        "risk_levels": dict(sorted(Counter(a["risk"] or "not assessed" for a in audits).items())),
    }
