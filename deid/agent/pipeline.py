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
from deid.redteam.assess import assess_note, masked_view
from deid.redteam.loop import harden
from deid.replace.engine import Replacer, clean_spans

from .crosscheck import cross_check, disagreements
from .nameuse import check_name_use
from .parallel import run_ordered
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
    ignored: list = field(default_factory=list)  # strings or occurrences left as written, with the reason
    second_spans: list = field(default_factory=list)  # what the second model found alone, when there is one
    second_name: str = ""
    notices: list = field(default_factory=list)  # things a person should know that are not about one span


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


def sum_usage(*usages):
    out = {}
    for u in usages:
        for k, v in (u or {}).items():
            if isinstance(v, (int, float)):
                out[k] = out.get(k, 0) + v
    return out


def settle_name_use(note, spans, ignored, client, verify_cache, ask):
    """Decide the occurrences the detector marked as doubtful ("Short of breath"). Returns
    (spans, name verdicts, the check's result). Only a clear "ordinary_word" leaves an occurrence
    as written, and that is recorded in `ignored`; every other answer, or no answer, keeps it replaced.
    With ask=False (no second model) they stay replaced and are sent to a person."""
    doubtful = [s for s in spans if s.get("doubt") == "name_use"]
    if not doubtful:
        return spans, {}, None
    if not ask:
        for s in doubtful:
            s["confidence"] = min(s["confidence"] if s.get("confidence") is not None else 1.0, 0.5)
        return spans, {}, None
    check = check_name_use(client, note["text"], doubtful, verify_cache)
    verdicts, drop = {}, set()
    for s in doubtful:
        key = (s["start"], s["end"])
        v = check.verdicts[key]
        if v["decision"] == "ordinary_word":
            drop.add(key)
            ignored.append({"text": note["text"][s["start"]:s["end"]], "type": "NAME", "start": s["start"],
                            "end": s["end"], "source": "name-use check",
                            "reason": "the model says this is an ordinary word here, not a person: " + (v["why"] or "no reason given")})
        else:
            verdicts[key] = ({"decision": "identifier", "why": v["why"]} if v["decision"] == "name"
                             else {"decision": "unsure", "why": v["why"] or "name use not settled"})
    return [s for s in spans if (s["start"], s["end"]) not in drop], verdicts, check


def second_opinion(note, spans, ignored, client, second, verify_cache, ask):
    """The second detector reads the note alone; its doubtful name occurrences get the same check as the
    primary's. Returns (merged spans, the second's spans, name verdicts, notices, usage, flags). A second model
    that cannot be read costs the note a notice, never the clean."""
    second_client, second_cache = second
    found = detect_note(second_client, note["text"], second_cache)
    flags = {"second_parse_error": found.parse_error, "second_truncated": found.truncated,
             "second_cached": found.cached}
    if found.parse_error or found.truncated:
        why = "could not be read" if found.parse_error else "was cut off at the output limit"
        notice = (f"the second model ({second_client.model}) {why}, so this note was checked by one model only")
        return spans, [], {}, [notice], found.usage, flags
    second_ignored = []
    theirs, verdicts, check = settle_name_use(note, found.spans, second_ignored, client, verify_cache, ask)
    for g in second_ignored:  # a word only the second model listed and the check released: still on record
        if g["source"] == "name-use check" and not any(
                g["start"] < s["end"] and s["start"] < g["end"] for s in spans + ignored):
            ignored.append(g)
    return (cross_check(spans, theirs), theirs, verdicts, [],
            sum_usage(found.usage, check.usage if check else None), flags)


def detect_one(note, client, detect_cache, verify_cache, low, verify, second=None):
    """Detect one note, settle doubtful name occurrences, optionally ask a second model, and verify its
    uncertain spans. Touches no shared state, so notes can run in parallel.
    Returns (Detected, the second looks' usage). second: (client, cache) of a second detector, or None."""
    found = detect_note(client, note["text"], detect_cache)
    failures = []
    if found.parse_error:
        failures.append("the detection reply could not be read")
    elif found.truncated:
        failures.append("the detection reply was cut off at the output limit, so identifiers may be missing")
    spans, ignored = found.spans, list(found.ignored)
    name_verdicts, nu = {}, None
    if not failures:
        spans, name_verdicts, nu = settle_name_use(note, spans, ignored, client, verify_cache, verify)
    theirs, notices, extra_usage, second_flags = [], [], {}, {}
    if second and not failures:
        spans, theirs, more, notices, extra_usage, second_flags = second_opinion(
            note, spans, ignored, client, second, verify_cache, verify)
        name_verdicts = {**more, **name_verdicts}
    uncertain = [] if failures or not verify else select_uncertain(note["text"], spans, low)
    uncertain += [s for s in disagreements(spans) if verify and not failures and s not in uncertain]
    check = verify_spans(client, note["text"], uncertain, verify_cache)
    verdicts = dict(name_verdicts)
    for key, v in check.verdicts.items():  # the more cautious answer of the two stands
        if key not in verdicts or v["decision"] != "identifier":
            verdicts[key] = v
    return Detected(
        note, spans, found.unmatched, verdicts, found.usage,
        {"detect_parse_error": found.parse_error, "detect_truncated": found.truncated,
         "detect_cached": found.cached, "verify_asked": check.asked,
         "verify_parse_error": check.parse_error, "verify_truncated": check.truncated,
         "verify_cached": check.cached,
         "nameuse_asked": nu.asked if nu else 0, "nameuse_parse_error": bool(nu and nu.parse_error),
         "nameuse_truncated": bool(nu and nu.truncated),
         "latency_s": found.latency_s + check.latency_s + (nu.latency_s if nu else 0.0), **second_flags},
        failures, ignored, theirs, second[0].model if second else "", notices), sum_usage(
            check.usage, nu.usage if nu else None, extra_usage)


def detect_and_verify(notes, client, detect_cache, verify_cache, budget, low, progress=None, verify=True, workers=1,
                      second=None):
    """Stage 1. Returns (list of Detected, stopped_early). verify=False skips the verifier (the
    offline detector has no second opinion to give); uncertain spans still go to a person.
    workers > 1 runs several notes at once; the result and its order do not change. second=(client, cache)
    adds a second detector whose disagreements with the first go to a person (deid.agent.crosscheck)."""
    out = []

    def consume(result):
        detected, verify_usage = result
        budget.add(detected.detect_usage)
        budget.add(verify_usage)
        out.append(detected)
        if progress:
            progress("detect+verify", len(out), len(notes), budget)

    stopped = run_ordered(lambda n: detect_one(n, client, detect_cache, verify_cache, low, verify, second),
                          notes, workers, lambda: budget.exceeded, consume)
    return out, stopped


def cross_args(d):
    """Arguments for build_note_audit that carry the second model's view, if there was one."""
    if not d.second_name and not d.notices:
        return {}
    args = {"notices": d.notices}
    if d.second_name:
        args["others"] = {d.second_name: d.second_spans}
        args["cross"] = {(s["start"], s["end"]): s for s in d.spans if s.get("cross")}
        args["second_name"] = d.second_name
    return args


def prefetch_redteam(batch, client, redteam_cache, budget, seed, workers, progress=None):
    """Ask the red-team reviewer about every note's first masked view, several at once, so that the
    note-by-note stage that follows finds those replies in the cache. The masked view shows each
    change as its type tag, so it does not depend on which stand-in values are chosen; a throwaway
    Replacer fitted the same way gives the same views, and the real run's own Replacer is not touched.
    Later feedback rounds (rare) are still asked one note at a time. Returns True if the cap stopped it."""
    replacer = Replacer(seed).fit([{"text": d.note["text"], "spans": d.spans} for d in batch])
    views = []
    for d in batch:
        if d.failures:
            continue
        spans = clean_spans(d.note["text"], d.spans)
        _, changes = replacer.apply({"text": d.note["text"], "spans": spans, "patient_key": d.note["patient_id"],
                                     "note_id": d.note["note_id"]})
        views.append(masked_view(d.note["text"], changes))
    done = []

    def consume(assessment):
        budget.add(assessment.usage)
        done.append(assessment)
        if progress:
            progress("red-team (first look)", len(done), len(views), budget)

    return run_ordered(lambda v: assess_note(client, v, redteam_cache), views, workers,
                       lambda: budget.exceeded, consume)


def replace_only(replacer, d, note, client, low):
    """One replacement pass with no red-team review; the audit says the risk was not assessed."""
    text, changes = replacer.apply({**note, "spans": clean_spans(note["text"], note["spans"])})
    audit = build_note_audit(d.note["note_id"], d.note["text"], d.spans, changes, client.model,
                             unmatched=d.unmatched, low=low, verdicts=d.verdicts, ignored=d.ignored,
                             **cross_args(d))
    return Outcome(d.note["note_id"], d, text, changes, clean_spans(note["text"], note["spans"]), [],
                   "not assessed", "not assessed", audit, {"redteam_calls": 0, "redteam_parse_errors": 0})


def review_and_clean(batch, client, redteam_cache, budget, seed, low, max_rounds, progress=None, redteam=True,
                     replacer=None):
    """Stage 2. Returns (list of Outcome, stopped_early, the fitted Replacer). redteam=False replaces
    once and leaves the risk "not assessed" (no reviewer model is available). replacer: one that already
    knows these notes (for a feed, deid.watch); by default a new one is fitted on the batch."""
    replacer = replacer or Replacer(seed).fit([{"text": d.note["text"], "spans": d.spans} for d in batch])
    outcomes = []
    for d in batch:
        if budget.exceeded:
            return outcomes, True, replacer
        if d.failures:  # fail closed: nothing is written as "cleaned" for this note
            audit = build_note_audit(d.note["note_id"], d.note["text"], [], [], client.model,
                                     unmatched=d.unmatched, low=low, failures=d.failures, ignored=d.ignored,
                                     notices=d.notices)
            outcomes.append(Outcome(d.note["note_id"], d, None, [], [], [], "not assessed", "not assessed", audit,
                                    {"redteam_calls": 0, "redteam_parse_errors": 0}))
            if progress:
                progress("red-team", len(outcomes), len(batch), budget)
            continue
        note = {"text": d.note["text"], "spans": d.spans,
                "patient_key": d.note["patient_id"], "note_id": d.note["note_id"]}
        if not redteam:
            outcomes.append(replace_only(replacer, d, note, client, low))
            if progress:
                progress("replace", len(outcomes), len(batch), budget)
            continue
        result = harden(replacer, note, client, redteam_cache, max_rounds)
        for a in result.assessments:
            budget.add(a.usage)
        final = result.assessments[-1]
        audit = build_note_audit(
            d.note["note_id"], d.note["text"], d.spans, result.changes, client.model,
            unmatched=d.unmatched, low=low, verdicts=d.verdicts, added=result.added,
            assessment={"risk": final.risk, "clues": final.clues}, ignored=d.ignored, **cross_args(d))
        outcomes.append(Outcome(
            d.note["note_id"], d, result.text, result.changes, result.spans, result.added,
            result.assessments[0].risk, final.risk, audit,
            {"redteam_calls": len(result.assessments),
             "redteam_parse_errors": sum(a.parse_error for a in result.assessments)}))
        if progress:
            progress("red-team", len(outcomes), len(batch), budget)
    return outcomes, False, replacer
