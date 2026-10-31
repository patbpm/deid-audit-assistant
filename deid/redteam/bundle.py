"""Read all of one patient's cleaned notes together: details that are harmless alone can single someone out together.

    results = run_linkage(outcomes, client, cache, budget)

The per-note reviewer (deid.redteam.assess) sees one note at a time. A teacher in one note, a statewide
award in another and a small town in a third are each ordinary, and together they may name one person.
Here the masked views of a patient's notes (every changed value shown as its type tag, as the per-note
reviewer sees them) go to the same reviewer prompt as one document headed "notes about the same patient".
If reading them together gives a higher risk level than the highest any single note got, or the reviewer
quotes clues, a "linkage" item is added to the first note's review queue. Nothing is edited: clues about
who a person is (occupation, small place, a public event) are for a person to decide.

One extra reviewer call per patient with two or more cleaned notes; off unless asked for (--linkage).
The risk level is a model's judgment, a signal for a human reviewer and never a guarantee.
"""

from .assess import MaskedView, assess_note, masked_view

RANK = {"low": 0, "medium": 1, "high": 2}
HEADER = "Notes about the same patient, to be read together as one record."


def bundle_view(views):
    """One MaskedView from a patient's per-note masked views. Clue ranges are not mapped back (they span notes)."""
    parts = [HEADER]
    for i, v in enumerate(views, 1):
        parts.append(f"--- Note {i} of {len(views)} ---\n{v.text}")
    return MaskedView("\n\n".join(parts), [])


def which_notes(phrase, views):
    return [i for i, v in enumerate(views, 1) if " ".join(phrase.split()) in " ".join(v.text.split())]


def linkage_item(note_ids, single_risks, assessment, views):
    """The review item for a patient, or None when reading the notes together adds nothing."""
    if assessment.parse_error:
        return {"kind": "linkage", "ref": None, "patient_notes": note_ids,
                "reasons": ["reading this patient's notes together could not be assessed: the reviewer's reply could not be read"]}
    top = max(single_risks, key=lambda r: RANK.get(r, -1)) if single_risks else "low"
    raised = RANK.get(assessment.risk, 0) > RANK.get(top, 0)
    clues = [c for c in assessment.clues if c["category"] != "LEFTOVER"]
    if not raised and not (clues and assessment.risk != "low"):
        return None
    shown = []
    for c in clues[:3]:
        notes = which_notes(c["text"], views)
        where = " and ".join(f"note {n}" for n in notes) if notes else "the notes together"
        shown.append(f"“{c['text']}” ({c['category'].lower().replace('_', ' ')}, {where})")
    head = (f"read together, this patient's {len(note_ids)} notes are rated {assessment.risk} risk"
            + (f", up from {top} for the riskiest single note" if raised else ""))
    return {"kind": "linkage", "ref": None, "patient_notes": note_ids,
            "reasons": [head + (": " + "; ".join(shown) if shown else "")]}


def run_linkage(outcomes, client, cache, budget, progress=None):
    """Assess each patient's cleaned notes together and add review items to the first note's audit.
    outcomes: Outcome objects from the pipeline. Returns one record per patient assessed."""
    groups = {}
    for o in outcomes:
        if o.cleaned is None or o.detected.failures:
            continue
        groups.setdefault(o.detected.note["patient_id"], []).append(o)
    results = []
    todo = {pid: os for pid, os in groups.items() if len(os) >= 2}
    for n, (pid, group) in enumerate(sorted(todo.items()), 1):
        if budget.exceeded:
            break
        views = [masked_view(o.detected.note["text"], o.changes) for o in group]
        assessment = assess_note(client, bundle_view(views), cache)
        budget.add(assessment.usage)
        ids = [o.note_id for o in group]
        singles = [o.risk_after for o in group]
        item = linkage_item(ids, singles, assessment, views)
        if item:
            group[0].audit["review"].append(item)
        results.append({"patient_id": pid, "notes": ids, "single_risks": singles, "linked_risk": assessment.risk,
                        "parse_error": assessment.parse_error, "flagged": item is not None,
                        "clues": [{k: c[k] for k in ("text", "category", "why")} for c in assessment.clues]})
        if progress:
            progress("linkage", n, len(todo), budget)
    return results
