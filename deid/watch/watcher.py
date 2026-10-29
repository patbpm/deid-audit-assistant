"""Clean notes as they arrive, update them when the original changes, and hold them until a person has looked.

    watcher = Watcher(source, backend, "runs/watch/demo")
    watcher.step()        # one pass: find new, changed and removed notes, clean them, release the cleared ones

What a pass does:
- A new note is detected, replaced and reviewed by the same pipeline as a batch run.
- An edited note (its text hash changed) is cleaned again; its earlier cleaned copy is withdrawn, its earlier
  review decisions are dropped (they were about text that no longer exists), and the new version is held again.
- A removed note's cleaned copy, audit and decisions are deleted.
- A note is released (written to released/) only when nothing in its review queue is undecided. A note that could
  not be cleaned is never released. Nothing is released automatically while a person has something left to look at.
- The replacement mapping is kept in mapping.json, so a patient's stand-in names and date shift are the same in
  a note that arrives next month. That file, audits/ and audit.json contain original identifiers: never share them.
"""

import hashlib
import json
import os
import secrets
import time
from pathlib import Path

from deid.agent.pipeline import detect_and_verify, review_and_clean
from deid.agent.verifier import PROMPT_VERSION as VERIFY_VERSION
from deid.audit.build import summarize
from deid.audit.verify import LOW_CONFIDENCE
from deid.detect.client import ApiError, Budget
from deid.detect.detector import Cache
from deid.redteam.prompt import PROMPT_VERSION as REDTEAM_VERSION
from deid.replace.engine import Replacer
from deid.review.decisions import apply_decisions, audit_hash, empty_note

from .status import render_status

MAX_ATTEMPTS = 3


def write_atomic(path, text):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def write_json(path, value):
    write_atomic(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def read_json(path, default):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def sha_of(note):
    return hashlib.sha256(json.dumps([note["patient_id"], note["text"]]).encode("utf-8")).hexdigest()


class Watcher:
    def __init__(self, source, backend, state_dir, token_cap=200_000, low=LOW_CONFIDENCE, max_rounds=2,
                 log=print, now=time.time):
        self.source, self.backend, self.dir = source, backend, Path(state_dir)
        self.low, self.max_rounds, self.log, self.now = low, max_rounds, log, now
        for sub in ("released", "audits"):
            (self.dir / sub).mkdir(parents=True, exist_ok=True)
        self.state = read_json(self.dir / "state.json", {"version": 1, "notes": {}})
        mapping = read_json(self.dir / "mapping.json", None)
        self.replacer = Replacer.from_state(mapping) if mapping else Replacer(secrets.token_hex(16))
        self.budget = Budget(token_cap)
        self.client = backend.chat()
        disk = backend.hosted
        cache = self.dir / "cache"
        self.detect_cache = Cache(cache / "detect") if disk else Cache(None)
        self.verify_cache = Cache(cache / "verify", VERIFY_VERSION) if disk else Cache(None, VERIFY_VERSION)
        self.redteam_cache = Cache(cache / "redteam", REDTEAM_VERSION) if disk else Cache(None, REDTEAM_VERSION)
        self.paused = False

    # --- one pass ----------------------------------------------------------------------------------
    def step(self):
        snapshot = self.source.snapshot()
        notes = self.state["notes"]
        dropped = set()
        counts = {"new": 0, "changed": 0, "removed": 0, "retried": 0}
        if not getattr(self.source, "incomplete", False):  # a half-written file must not look like a deletion
            for note_id in sorted(set(notes) - set(snapshot)):
                self.remove(note_id)
                dropped.add(note_id)
                counts["removed"] += 1
        todo = []
        for note_id in sorted(snapshot):
            known, sha = notes.get(note_id), sha_of(snapshot[note_id])
            if known is None:
                todo.append((note_id, "new"))
            elif known["sha"] != sha:
                todo.append((note_id, "changed"))
            elif known["status"] == "queued" or (known["status"] == "error" and known["attempts"] < MAX_ATTEMPTS):
                todo.append((note_id, "retried"))
        for note_id, why in todo:
            if self.budget.exceeded:
                self.paused = True
                self.event(None, "paused", "the token cap was reached; raise it to go on")
                break
            if why == "changed":
                self.withdraw(note_id)
                dropped.add(note_id)
            self.process(note_id, snapshot[note_id], why)
            counts[why] += 1
        self.write_audit(dropped)
        self.release()
        self.save()
        return counts

    def process(self, note_id, note, why):
        prior = self.state["notes"].get(note_id, {})
        entry = {"sha": sha_of(note), "patient_id": note["patient_id"], "version": prior.get("version", 0) + 1,
                 "status": "error", "attempts": prior.get("attempts", 0) + 1 if why == "retried" else 1,
                 "error": "", "at": self.now()}
        self.state["notes"][note_id] = entry
        record = {"note_id": note_id, "patient_id": note["patient_id"], "text": note["text"]}
        try:
            batch, _ = detect_and_verify([record], self.client, self.detect_cache, self.verify_cache, self.budget,
                                         self.low, verify=self.backend.verify)
            if not batch:
                entry["status"], entry["error"] = "queued", "waiting for the token cap"
                return
            d = batch[0]
            conflicts = [] if d.failures else self.replacer.extend([{"text": record["text"], "spans": d.spans}])
            outcomes, _, _ = review_and_clean(batch, self.client, self.redteam_cache, self.budget, 0, self.low,
                                              self.max_rounds, redteam=self.backend.redteam, replacer=self.replacer)
        except (ApiError, OSError, ValueError) as err:
            entry["error"] = str(err)[:200]
            self.event(note_id, "error", entry["error"])
            return
        audit = outcomes[0].audit
        if conflicts:
            audit["review"].append({"kind": "notice", "ref": None, "reasons": [
                "a real name in this note equals a stand-in name already given to someone else: " + ", ".join(conflicts)]})
        if not self.backend.redteam and not audit["failed"]:
            # no second reader ran, so an empty queue proves nothing: a person always looks before release
            audit["review"].append({"kind": "notice", "ref": None, "reasons": [
                "this engine has no second reader or verifier, and it only finds names that follow a cue such as "
                "Dr. or Patient:; read the cleaned text yourself before releasing it"]})
        write_json(self.dir / "audits" / f"{note_id}.json", audit)
        entry.update(status="failed" if audit["failed"] else "pending", error="; ".join(audit["failed"]))
        self.event(note_id, why, f"version {entry['version']}, {len(audit['review'])} item(s) to review")
        write_json(self.dir / "mapping.json", self.replacer.state())

    def withdraw(self, note_id):
        """The original changed: the cleaned copy and the decisions about it are about text that is gone."""
        (self.dir / "released" / f"{note_id}.txt").unlink(missing_ok=True)
        (self.dir / "audits" / f"{note_id}.json").unlink(missing_ok=True)

    def remove(self, note_id):
        self.withdraw(note_id)
        self.state["notes"].pop(note_id, None)
        self.event(note_id, "removed", "the original is gone; its cleaned copy, audit and decisions were deleted")

    # --- audit file and decisions ------------------------------------------------------------------
    def audits(self):
        out = []
        for note_id in sorted(self.state["notes"]):
            audit = read_json(self.dir / "audits" / f"{note_id}.json", None)
            if audit and self.state["notes"][note_id]["status"] in ("pending", "released", "failed"):
                out.append(audit)
        return out

    def write_audit(self, dropped):
        """audit.json (what the review page opens) and its decisions file, kept in step: decisions about a
        note that changed or went away are dropped, the rest are kept under the new file's hash."""
        audits = self.audits()
        path, decisions_path = self.dir / "audit.json", self.dir / "audit.decisions.json"
        write_json(path, {"summary": summarize(audits), "notes": audits})
        saved = read_json(decisions_path, {"version": 1, "notes": {}})
        active = {a["note_id"] for a in audits}
        saved["notes"] = {k: v for k, v in saved["notes"].items() if k in active and k not in dropped}
        saved["audit_sha256"] = audit_hash(path)
        write_json(decisions_path, saved)

    def release(self):
        decisions = read_json(self.dir / "audit.decisions.json", {"notes": {}})["notes"]
        for audit in self.audits():
            entry, note_id = self.state["notes"][audit["note_id"]], audit["note_id"]
            if entry["status"] == "failed":
                continue
            final = apply_decisions(audit, decisions.get(note_id, empty_note()))
            entry.update(review_items=final["review_items"], undecided=final["undecided"], risk=audit["risk"])
            target = self.dir / "released" / f"{note_id}.txt"
            if final["undecided"] == 0:
                if not target.exists() or target.read_text(encoding="utf-8") != final["text"]:
                    write_atomic(target, final["text"])
                    self.event(note_id, "released", "nothing left to review")
                entry["status"] = "released"
            else:
                target.unlink(missing_ok=True)
                entry["status"] = "pending"

    # --- records -------------------------------------------------------------------------------------
    def event(self, note_id, what, detail=""):
        line = {"at": round(self.now(), 1), "note_id": note_id, "event": what, "detail": detail}
        with open(self.dir / "events.jsonl", "a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(line) + "\n")
        self.log(f"{note_id or '-'}: {what}" + (f" ({detail})" if detail else ""))

    def save(self):
        write_json(self.dir / "state.json", self.state)
        write_atomic(self.dir / "status.html", render_status(self.state, self.paused, self.backend.label, self.now()))
        write_json(self.dir / "mapping.json", self.replacer.state())

    def run(self, interval=5.0, once=False, sleep=time.sleep):
        while True:
            self.step()
            if once or self.paused:
                return
            sleep(interval)
