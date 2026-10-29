"""Build the audit record for a note: one evidence-trace entry per change.

Every entry links a replacement to the original span (character offsets), the
detector that found it, its confidence, the other detectors that agree, the
rule that rewrote it, and the checks' decision. A review queue lists what a
person should look at: spans a check objected to, strings the model listed but
that were not found in the note, and the red-team reviewer's clues.
"""

from collections import Counter

from deid.agent.crosscheck import reason as crosscheck_reason

from .verify import LOW_CONFIDENCE, verify_span


def _overlap(a, b):
    return a["start"] < b["end"] and b["start"] < a["end"]


FEEDBACK = "red-team feedback"


def apply_verdict(checks, verdict):
    """Fold the verifier's verdict into the rule checks. A confirmation clears
    only the low-confidence objection; any doubt sends the span to a person."""
    reasons = list(checks["reasons"])
    if verdict["decision"] == "identifier":
        reasons = [r for r in reasons if not r.startswith("detector confidence")]
    elif verdict["decision"] == "not_identifier":
        reasons.append("verifier thinks this is not an identifier: " + (verdict["why"] or "no reason given"))
    else:
        reasons.append("verifier is unsure: " + (verdict["why"] or "no reason given"))
    return {"decision": "review" if reasons else "accept", "reasons": reasons}


def cross_reason(cross, change, primary_name, second_name):
    span = (cross or {}).get((change["start"], change["end"]))
    return crosscheck_reason(span, primary_name, second_name) if span else None


def build_note_audit(note_id, text, spans, changes, detector, others=None, unmatched=(),
                     assessment=None, low=LOW_CONFIDENCE, verdicts=None, added=(), failures=(), ignored=(), cross=None, second_name="", notices=()):
    """spans: the detector's spans (start, end, type, confidence?); changes: from
    Replacer.apply; others: {detector name: spans} from detectors that also ran;
    assessment: {"risk", "clues"} from the red-team reviewer, or None;
    verdicts: {(start, end): {"decision", "why"}} from the verifier;
    added: spans the red-team reviewer's feedback added after detection;
    ignored: strings or occurrences the detector listed that were left as written, each with its
    source ("rule" is informational; "name-use check" is a model's call and goes to the review queue);
    cross: {(start, end): span} for spans a second model was asked about, with the other model's name in
    second_name (spans the two disagree on go to review); notices: sentences for the review queue."""
    confidence = {(s["start"], s["end"]): s.get("confidence") for s in spans}
    added_keys = {(s["start"], s["end"]) for s in added}
    verdicts = verdicts or {}
    entries, review = [], []
    for i, c in enumerate(changes):
        agree = [name for name, other in (others or {}).items()
                 if any(_overlap(c, o) for o in other)]
        conf = confidence.get((c["start"], c["end"]))
        checks = verify_span(c, conf, low)
        verdict = verdicts.get((c["start"], c["end"]))
        if verdict:
            checks = apply_verdict(checks, verdict)
        split = cross_reason(cross, c, detector, second_name)
        if split:
            checks = {"decision": "review", "reasons": checks["reasons"] + [split]}
        from_feedback = (c["start"], c["end"]) in added_keys
        if from_feedback:
            checks = {"decision": "review", "reasons": checks["reasons"] + [
                "found only by the red-team reviewer, not by the detector"]}
        entry = {
            "id": f"{note_id}:{i}", "type": c["type"],
            "start": c["start"], "end": c["end"], "new_start": c["new_start"], "new_end": c["new_end"],
            "original": c["original"], "replacement": c["replacement"], "rule": c["rule"],
            "detector": FEEDBACK if from_feedback else detector, "confidence": conf,
            "also_found_by": agree, "verifier": verdict, "checks": checks, "status": checks["decision"],
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
    for n in notices:
        review.append({"kind": "notice", "ref": None, "reasons": [n]})
    for g in ignored:
        if g.get("source") == "name-use check":  # a model decided to leave a listed name as written: a person checks
            review.append({"kind": "not-replaced", "ref": None, "category": "NAME", "text": g["text"],
                           "ranges": [[g["start"], g["end"]]],
                           "reasons": ["left as written: " + repr(g["text"]) + f" at {g['start']}-{g['end']}. " + g["reason"]]})
    if failures:
        review.insert(0, {"kind": "failed", "ref": None,
                          "reasons": ["NOT CLEANED: " + "; ".join(failures)]})
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
            "risk": risk, "assessed": assessment is not None, "failed": list(failures),
            "ignored": [dict(g) for g in ignored]}


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
        "notes_not_cleaned": sum(bool(a.get("failed")) for a in audits),
        "risk_levels": dict(sorted(Counter(a["risk"] or "not assessed" for a in audits).items())),
    }
