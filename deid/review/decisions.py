"""What a reviewer decided, and the final note that follows from it.

Decisions are stored beside the audit file and never change it. The rules:

  * A flagged replacement the reviewer accepts stays replaced; one they reject
    is restored to the original text. Anything undecided stays replaced, so
    leaving work unfinished never un-redacts anything.
  * A clue the reviewer redacts is replaced with [REDACTED] (all its locations); so is a word the
    name check left as written, if the reviewer chooses to replace it after all.
    Other clues, unmatched strings and notes are dismissed (acknowledged).
  * Text the reviewer selects and redacts is replaced with its type tag, such as
    [NAME], not with a surrogate: the surrogate engine is not rerun here.

Everything here is pure data in, data out, so it can be tested without a server.
"""

import copy
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from deid.eval import TYPES

MANUAL_TYPES = TYPES + ("OTHER",)
ENTRY_DECISIONS = ("accept", "reject")


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def audit_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def empty_note():
    return {"entries": {}, "items": {}, "manual": []}


def item_id(note_id, index):
    return f"{note_id}:r{index}"


def tag(kind):
    return f"[{kind}]" if kind in TYPES else "[REDACTED]"


def apply_decisions(note, state):
    """note: one audit note; state: its decisions. Returns the final text with
    marks [{start, end, id, kind}] in final-text coordinates, plus counts."""
    pieces = []
    for e in note["entries"]:
        decision = state["entries"].get(e["id"], {}).get("decision")
        if decision == "reject":
            pieces.append((e["start"], e["end"], note["text"][e["start"]:e["end"]], "restored", e["id"]))
        else:
            pieces.append((e["start"], e["end"], e["replacement"], "replaced", e["id"]))
    for m in state["manual"]:
        pieces.append((m["start"], m["end"], tag(m["type"]), "manual", m["id"]))
    for i, item in enumerate(note["review"]):
        if state["items"].get(item_id(note["note_id"], i), {}).get("decision") == "redact":
            for n, (a, b) in enumerate(item.get("ranges", [])):
                pieces.append((a, b, "[REDACTED]", "redacted", f"{item_id(note['note_id'], i)}.{n}"))
    pieces.sort(key=lambda p: (p[0], p[1]))
    out, marks, conflicts, cursor, pos = [], [], [], 0, 0
    for start, end, text, kind, ident in pieces:
        if start < cursor:
            conflicts.append(ident)
            continue
        before = note["text"][cursor:start]
        out.append(before)
        pos += len(before)
        out.append(text)
        marks.append({"start": pos, "end": pos + len(text), "id": ident, "kind": kind})
        pos += len(text)
        cursor = end
    out.append(note["text"][cursor:])
    counts = {k: sum(m["kind"] == k for m in marks) for k in ("replaced", "restored", "manual", "redacted")}
    return {"text": "".join(out), "marks": marks, "conflicts": conflicts, "counts": counts,
            **progress(note, state)}


def is_decided(note, state, index):
    item = note["review"][index]
    if item["kind"] == "span":
        return item["ref"] in state["entries"]
    return item_id(note["note_id"], index) in state["items"]


def progress(note, state):
    done = sum(is_decided(note, state, i) for i in range(len(note["review"])))
    return {"review_items": len(note["review"]), "decided": done,
            "undecided": len(note["review"]) - done}


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def record(note, state, op, reviewer="reviewer", now=now_iso):
    """Apply one reviewer action to a copy of state; return it, or raise ValueError
    (and change nothing) if the action is invalid or would make two edits overlap."""
    new = copy.deepcopy(state)
    stamp = {"by": reviewer, "at": now()}
    kind = op.get("op")
    if kind == "entry":
        if op.get("id") not in {e["id"] for e in note["entries"]}:
            raise ValueError("unknown replacement")
        if op.get("decision") == "clear":
            new["entries"].pop(op["id"], None)
        elif op.get("decision") in ENTRY_DECISIONS:
            new["entries"][op["id"]] = {"decision": op["decision"], **stamp}
        else:
            raise ValueError("decision must be accept, reject or clear")
    elif kind == "item":
        index = op.get("index")
        if not is_int(index) or not 0 <= index < len(note["review"]):
            raise ValueError("unknown review item")
        item, key = note["review"][index], item_id(note["note_id"], index)
        if item["kind"] == "span":
            raise ValueError("decide a flagged replacement with accept or reject")
        if item["kind"] == "failed":
            raise ValueError("this note was not cleaned; it cannot be dismissed, only redacted by hand or rerun")
        decision = op.get("decision")
        if decision == "clear":
            new["items"].pop(key, None)
        elif decision == "dismiss":
            new["items"][key] = {"decision": decision, **stamp}
        elif decision == "redact":
            if item["kind"] not in ("clue", "not-replaced") or not item.get("ranges"):
                raise ValueError("this item cannot be redacted")
            new["items"][key] = {"decision": decision, **stamp}
        else:
            raise ValueError("decision must be dismiss, redact or clear")
    elif kind == "manual-add":
        start, end = op.get("start"), op.get("end")
        if not (is_int(start) and is_int(end)) or not 0 <= start < end <= len(note["text"]):
            raise ValueError("selection is outside the note")
        if op.get("type") not in MANUAL_TYPES:
            raise ValueError("unknown type")
        number = 1 + max([int(m["id"].rsplit(":m", 1)[1]) for m in new["manual"]] or [0])
        new["manual"].append({"id": f"{note['note_id']}:m{number}", "start": start, "end": end,
                              "type": op["type"], **stamp})
    elif kind == "manual-remove":
        before = len(new["manual"])
        new["manual"] = [m for m in new["manual"] if m["id"] != op.get("id")]
        if len(new["manual"]) == before:
            raise ValueError("unknown manual redaction")
    else:
        raise ValueError("unknown action")
    if apply_decisions(note, new)["conflicts"]:
        raise ValueError("that overlaps another edit in this note")
    return new


class Store:
    """Decisions for one audit file, saved next to it after every change."""

    def __init__(self, audit_path, reviewer="reviewer", now=now_iso):
        self.audit_path = Path(audit_path)
        stem = self.audit_path.name.removesuffix(".json")
        self.path = self.audit_path.with_name(stem + ".decisions.json")
        self.base = self.audit_path.with_name(stem.removesuffix(".audit"))
        self.reviewer, self.now = reviewer, now
        self.sha = audit_hash(self.audit_path)
        self.audit = json.loads(self.audit_path.read_text(encoding="utf-8"))
        self.notes = {n["note_id"]: n for n in self.audit["notes"]}
        self.state = {"version": 1, "audit_sha256": self.sha, "notes": {}}
        if self.path.exists():
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            if saved.get("audit_sha256") != self.sha:
                raise ValueError(f"{self.path.name} belongs to a different audit file; move or delete it")
            self.state = saved

    def refresh(self):
        """Pick up an audit file that deid.watch has rewritten. The watcher rewrites the decisions file
        under the new hash, so if the two do not match yet (it is mid-write), keep what is loaded and look
        again next time. Returns True when something new was loaded."""
        try:
            sha = audit_hash(self.audit_path)
            if sha == self.sha:
                return False
            audit = json.loads(self.audit_path.read_text(encoding="utf-8"))
            saved = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else None
        except (OSError, ValueError):
            return False
        if saved is None or saved.get("audit_sha256") != sha:
            return False
        self.sha, self.audit, self.state = sha, audit, saved
        self.notes = {n["note_id"]: n for n in audit["notes"]}
        return True

    def note_state(self, note_id):
        return self.state["notes"].setdefault(note_id, empty_note())

    def apply(self, note_id, op):
        if note_id not in self.notes:
            raise ValueError("unknown note")
        self.state["notes"][note_id] = record(self.notes[note_id], self.note_state(note_id), op,
                                              self.reviewer, self.now)
        self.save()
        return self.view(note_id)

    def view(self, note_id):
        return {"note_id": note_id, "state": self.note_state(note_id),
                "final": apply_decisions(self.notes[note_id], self.note_state(note_id))}

    def save(self):
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self.state, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        os.replace(tmp, self.path)

    def export(self, out_prefix=None):
        """Write the reviewed notes and the review log. Returns the summary."""
        base = Path(out_prefix) if out_prefix else self.base
        notes, log = [], []
        withheld = []
        for note_id, note in self.notes.items():
            final = apply_decisions(note, self.note_state(note_id))
            if note.get("failed"):  # never export a note as reviewed when the agent could not clean it
                withheld.append(note_id)
            else:
                notes.append({"note_id": note_id, "text": final["text"]})
            log.append({"note_id": note_id, "counts": final["counts"], "decided": final["decided"],
                        "undecided": final["undecided"], "review_items": final["review_items"],
                        "decisions": self.note_state(note_id)})
        count = lambda part, name: sum(d["decision"] == name for r in log for d in r["decisions"][part].values())
        summary = {
            "notes": len(self.notes), "notes_exported": len(notes), "notes_withheld_not_cleaned": withheld,
            "review_items": sum(r["review_items"] for r in log),
            "undecided": sum(r["undecided"] for r in log),
            "notes_fully_reviewed": sum(r["undecided"] == 0 for r in log),
            "accepted": count("entries", "accept"), "rejected": count("entries", "reject"),
            "dismissed": count("items", "dismiss"), "clues_redacted": count("items", "redact"),
            "added_by_reviewer": sum(len(r["decisions"]["manual"]) for r in log),
            "audit_sha256": self.sha, "exported_at": self.now(),
        }
        Path(f"{base}.reviewed.notes.jsonl").write_text(
            "".join(json.dumps(n, sort_keys=True) + "\n" for n in notes), encoding="utf-8", newline="\n")
        Path(f"{base}.review-log.json").write_text(
            json.dumps({"summary": summary, "notes": log}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8", newline="\n")
        return summary
