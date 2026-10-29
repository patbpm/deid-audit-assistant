"""One pass of the agent over a batch of notes.

    detect (model) -> verify uncertain spans (model) -> replace -> red-team review (model)
        -> leftovers sent back, replaced again (up to max_rounds) -> audit record

Stage 1 (detect and verify) runs over the whole batch first, because the
replacement engine reads the names in the batch to tell first names from
surnames. Stage 2 (replace, review, feed back) then runs note by note. Nothing
but note text and the masked, cleaned view is ever sent to a model.
"""

from dataclasses import dataclass, field

from deid.audit.build import build_note_audit
from deid.detect.detector import detect_note
from deid.redteam.loop import harden
from deid.replace.engine import Replacer

from .verifier import select_uncertain, verify_spans


@dataclass
class Detected:
    note: dict
    spans: list
    unmatched: list
    verdicts: dict
    detect_usage: dict = field(default_factory=dict)
    flags: dict = field(default_factory=dict)  # parse errors, truncation, cache use
    failures: list = field(default_factory=list)  # why detection cannot be trusted; empty when fine


@dataclass
class Outcome:
    note_id: str
    detected: Detected
    cleaned: str | None  # None when the note was not cleaned (see detected.failures)
    changes: list
    final_spans: list
    added: list
    risk_before: str
    risk_after: str
    audit: dict
    calls: dict = field(default_factory=dict)


def detect_and_verify(notes, client, detect_cache, verify_cache, budget, low, progress=None):
    """Stage 1. Returns (list of Detected, stopped_early)."""
    out = []
    for note in notes:
        if budget.exceeded:
            return out, True
        found = detect_note(client, note["text"], detect_cache)
        budget.add(found.usage)
        failures = []
        if found.parse_error:
            failures.append("the detection reply could not be read")
        elif found.truncated:
            failures.append("the detection reply was cut off at the output limit, so identifiers may be missing")
        uncertain = [] if failures else select_uncertain(note["text"], found.spans, low)
        check = verify_spans(client, note["text"], uncertain, verify_cache)
        budget.add(check.usage)
        out.append(Detected(
            note, found.spans, found.unmatched, check.verdicts, found.usage,
            {"detect_parse_error": found.parse_error, "detect_truncated": found.truncated,
             "detect_cached": found.cached, "verify_asked": check.asked,
             "verify_parse_error": check.parse_error, "verify_truncated": check.truncated,
             "verify_cached": check.cached,
             "latency_s": found.latency_s + check.latency_s}, failures))
        if progress:
            progress("detect+verify", len(out), len(notes), budget)
    return out, False


def review_and_clean(batch, client, redteam_cache, budget, seed, low, max_rounds, progress=None):
    """Stage 2. Returns (list of Outcome, stopped_early, the fitted Replacer)."""
    replacer = Replacer(seed).fit([{"text": d.note["text"], "spans": d.spans} for d in batch])
    outcomes = []
    for d in batch:
        if budget.exceeded:
            return outcomes, True, replacer
        if d.failures:  # fail closed: nothing is written as "cleaned" for this note
            audit = build_note_audit(d.note["note_id"], d.note["text"], [], [], client.model,
                                     unmatched=d.unmatched, low=low, failures=d.failures)
            outcomes.append(Outcome(d.note["note_id"], d, None, [], [], [], "not assessed", "not assessed", audit,
                                    {"redteam_calls": 0, "redteam_parse_errors": 0}))
            if progress:
                progress("red-team", len(outcomes), len(batch), budget)
            continue
        note = {"text": d.note["text"], "spans": d.spans,
                "patient_key": d.note["patient_id"], "note_id": d.note["note_id"]}
        result = harden(replacer, note, client, redteam_cache, max_rounds)
        for a in result.assessments:
            budget.add(a.usage)
        final = result.assessments[-1]
        audit = build_note_audit(
            d.note["note_id"], d.note["text"], d.spans, result.changes, client.model,
            unmatched=d.unmatched, low=low, verdicts=d.verdicts, added=result.added,
            assessment={"risk": final.risk, "clues": final.clues})
        outcomes.append(Outcome(
            d.note["note_id"], d, result.text, result.changes, result.spans, result.added,
            result.assessments[0].risk, final.risk, audit,
            {"redteam_calls": len(result.assessments),
             "redteam_parse_errors": sum(a.parse_error for a in result.assessments)}))
        if progress:
            progress("red-team", len(outcomes), len(batch), budget)
    return outcomes, False, replacer
