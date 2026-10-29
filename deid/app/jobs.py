"""Jobs: one upload (files or pasted text), from the first click to the results.

A job lives in <data-dir>/<id>/ (input/, job.json and the outputs). Its state moves
draft -> running -> done or failed; a table job stops at awaiting_plan so a person
can check the column plan before anything is changed. Work runs on a background
thread and reports through Ctx. Everything here is in-process: no network call is
made unless the backend is hosted and the person has confirmed the content is
synthetic.
"""

import copy
import json
import os
import re
import secrets
import shutil
import threading
import time
from pathlib import Path

from . import flows, kinds
from .flows import JobError

MAX_FILE_BYTES = 50_000_000
MAX_FILES = 200
MAX_TOTAL_BYTES = 250_000_000
HEADER_CHOICES = ("auto", "yes", "no")
UNKNOWN_CHOICES = ("withhold", "mask")
FREETEXT_CHOICES = ("mask", "detector")
ID_PATTERN = re.compile(r"[0-9a-f]{12}")

NOTE_STEPS = [("read", "Read the input"), ("detect", "Find identifiers"), ("replace", "Replace and re-check"),
              ("audit", "Write the audit trail")]
TABLE_STEPS = [("read", "Read the tables"), ("plan", "Propose a treatment for each column"),
               ("confirm", "You confirm the plan"), ("clean", "Clean the tables"), ("risk", "Check for small groups")]


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def safe_name(name):
    base = re.split(r"[\\/]", name or "")[-1]
    base = re.sub(r"[^\w.\- ]", "_", base).strip(" .") or "file"
    return base[:80]


class Ctx:
    """What a running flow uses to report back."""

    def __init__(self, store, job_id):
        self.store, self.id, self.dir = store, job_id, store.dir(job_id)

    def step(self, step_id, state, detail=None):
        def change(job):
            for s in job["steps"]:
                if s["id"] == step_id:
                    s["state"] = state
                    if detail is not None:
                        s["detail"] = detail
        self.store.update(self.id, change)

    def tokens(self, budget, prior=None):
        """Show a budget's use. prior: tokens already spent earlier in the job (a dict with in and out)."""
        before = prior or {"in": 0, "out": 0}
        used_in, used_out = before["in"] + budget.tokens_in, before["out"] + budget.tokens_out
        self.store.update(self.id, lambda job: job["tokens"].update(
            {"in": used_in, "out": used_out, "used": used_in + used_out}))

    def result(self, value):
        self.store.update(self.id, lambda job: job.update(result=value))


class JobStore:
    def __init__(self, root, backend, max_job_tokens=100_000, seed=0):
        self.root, self.backend, self.max_job_tokens, self.seed = Path(root), backend, max_job_tokens, seed
        self.lock = threading.RLock()
        self.jobs = {}
        self.root.mkdir(parents=True, exist_ok=True)
        for path in sorted(self.root.glob("*/job.json")):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if ID_PATTERN.fullmatch(job.get("id", "")):
                if job["state"] == "running":
                    job["state"], job["error"] = "failed", "The app stopped while this job was running."
                self.jobs[job["id"]] = job

    # --- storage ---------------------------------------------------------------------
    def dir(self, job_id):
        if not ID_PATTERN.fullmatch(job_id or ""):
            raise KeyError(job_id)
        return self.root / job_id

    def save(self, job):
        path = self.dir(job["id"]) / "job.json"
        tmp = path.with_name("job.json.tmp")
        tmp.write_text(json.dumps(job, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        os.replace(tmp, path)

    def update(self, job_id, change):
        with self.lock:
            job = self.jobs[job_id]
            change(job)
            self.save(job)

    def get(self, job_id):
        with self.lock:
            if job_id not in self.jobs:
                raise KeyError(job_id)
            return copy.deepcopy(self.jobs[job_id])

    def listing(self):
        with self.lock:
            rows = [{"id": j["id"], "created": j["created"], "state": j["state"], "kind": j["kind"],
                     "files": len(j["files"]), "title": j.get("title", "")} for j in self.jobs.values()]
        return sorted(rows, key=lambda r: r["created"], reverse=True)

    # --- building a job --------------------------------------------------------------------
    def create(self, title=""):
        job_id = secrets.token_hex(6)
        (self.dir(job_id) / "input").mkdir(parents=True)
        job = {"id": job_id, "created": now(), "state": "draft", "kind": None, "title": title[:80],
               "engine": self.backend.name, "engine_label": self.backend.label, "hosted": self.backend.hosted,
               "files": [], "options": {}, "steps": [], "tokens": {"in": 0, "out": 0, "used": 0, "cap": 0},
               "error": None, "result": None, "plan": None}
        with self.lock:
            self.jobs[job_id] = job
            self.save(job)
        return self.get(job_id)

    def draft(self, job_id):
        job = self.get(job_id)
        if job["state"] != "draft":
            raise ValueError("this job has already started; begin a new one to add more")
        return job

    def add_file(self, job_id, name, data):
        job = self.draft(job_id)
        if len(job["files"]) >= MAX_FILES:
            raise ValueError(f"at most {MAX_FILES} files per job")
        if len(data) > MAX_FILE_BYTES:
            raise ValueError(f"{safe_name(name)} is larger than {MAX_FILE_BYTES:,} bytes")
        if sum(f["size"] for f in job["files"]) + len(data) > MAX_TOTAL_BYTES:
            raise ValueError("this job is over the total size limit")
        found = kinds.kind_of_file(name, data)
        entry = {"name": safe_name(name), "size": len(data), "kind": found.kind, "label": found.label,
                 "reason": found.reason, "stored": None}
        if found.ok:
            try:
                self.supported(found.kind)
            except ValueError as err:
                entry.update(kind=None, label="not available", reason=str(err))
                return entry
            entry["stored"] = f"{len(job['files']) + 1:03d}-{safe_name(name)}"
            (self.dir(job_id) / "input" / entry["stored"]).write_bytes(data)
            self.update(job_id, lambda j: j["files"].append(entry))
        return entry

    def add_text(self, job_id, text, name="pasted text"):
        found = kinds.kind_of_text(text)
        if not found.ok:
            return {"name": name, "size": len(text), "kind": None, "label": found.label, "reason": found.reason,
                    "stored": None}
        ext = ".csv" if found.kind == "table" else ".txt"
        return self.add_file(job_id, f"{name}{ext}", text.encode())

    def supported(self, kind):
        if kind not in self.backend.kinds:
            raise ValueError({
                "audio": "Dictated audio needs the hosted speech model: start the app with --live.",
                "scan": "Scanned pages need the hosted vision model: start the app with --live."}.get(
                    kind, f"{kind} input is not available with this engine"))

    def set_kind(self, job_id, index, kind):
        job = self.draft(job_id)
        if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(job["files"]):
            raise ValueError("unknown file")
        entry = job["files"][index]
        if entry["kind"] not in ("note", "table") or kind not in ("note", "table"):
            raise ValueError("only text files can be switched between note and table")
        if kind == "table" and not kinds.looks_like_table(
                (self.dir(job_id) / "input" / entry["stored"]).read_text(encoding="utf-8-sig")):
            raise ValueError("this file does not have a steady number of columns, so it cannot be read as a table")
        self.update(job_id, lambda j: j["files"][index].update(
            kind=kind, label="CSV table (you chose)" if kind == "table" else "note text (you chose)"))

    # --- running --------------------------------------------------------------------------
    def options(self, raw):
        raw = raw if isinstance(raw, dict) else {}
        cap = raw.get("token_cap", self.max_job_tokens)
        if not isinstance(cap, int) or isinstance(cap, bool) or cap < 1:
            raise ValueError("token cap must be a positive whole number")
        seconds = raw.get("max_audio_seconds", 600)
        if not isinstance(seconds, int) or isinstance(seconds, bool) or not 1 <= seconds <= 3600:
            raise ValueError("audio seconds must be between 1 and 3600")
        out = {"same_patient": bool(raw.get("same_patient")), "model_typing": bool(raw.get("model_typing")),
               "header": raw.get("header", "auto"), "unknown": raw.get("unknown", "withhold"),
               "freetext": raw.get("freetext", "mask"), "token_cap": min(cap, self.max_job_tokens),
               "max_audio_seconds": seconds, "confirm_synthetic": raw.get("confirm_synthetic") is True}
        for key, choices in (("header", HEADER_CHOICES), ("unknown", UNKNOWN_CHOICES), ("freetext", FREETEXT_CHOICES)):
            if out[key] not in choices:
                raise ValueError(f"{key} must be one of {', '.join(choices)}")
        if out["model_typing"] and not self.backend.model_help:
            raise ValueError("model help for columns needs the hosted model: start the app with --live")
        return out

    def start(self, job_id, raw_options):
        job = self.draft(job_id)
        files = job["files"]
        if not files:
            raise ValueError("add a file or some text first")
        families = {kinds.family(f["kind"]) for f in files}
        if len(families) > 1:
            raise ValueError("notes (text, audio, scans) and tables are cleaned differently: process them as separate jobs")
        for f in files:
            self.supported(f["kind"])
        options = self.options(raw_options)
        if self.backend.hosted and not options["confirm_synthetic"]:
            raise ValueError("confirm that the content is synthetic or public before it is sent to a hosted model")
        family = families.pop()
        steps = NOTE_STEPS if family == "notes" else TABLE_STEPS

        def begin(j):
            j.update(state="running", kind=family, options=options, error=None,
                     steps=[{"id": i, "label": label, "state": "pending", "detail": ""} for i, label in steps])
            j["tokens"]["cap"] = options["token_cap"] if self.backend.hosted else 0
        self.update(job_id, begin)
        target = self.run_notes if family == "notes" else self.plan_tables
        self.spawn(job_id, target)

    def submit_plan(self, job_id, edits):
        job = self.get(job_id)
        if job["state"] != "awaiting_plan":
            raise ValueError("this job is not waiting for a plan")
        if not isinstance(edits, dict):
            raise ValueError("send the edits as an object")
        flows.check_edits(self.dir(job_id), edits)
        self.update(job_id, lambda j: j.update(state="running"))
        self.spawn(job_id, lambda ctx: self.apply_tables(ctx, edits))

    def spawn(self, job_id, target):
        def work():
            ctx = Ctx(self, job_id)
            try:
                target(ctx)
            except JobError as err:
                self.fail(job_id, str(err))
            except Exception as err:  # a hosted-service error, a bad file: say what, never the content
                self.fail(job_id, f"{type(err).__name__}: {err}"[:400])
        threading.Thread(target=work, daemon=True).start()

    def fail(self, job_id, message):
        def change(job):
            job["state"], job["error"] = "failed", message
            for s in job["steps"]:
                if s["state"] == "running":
                    s["state"] = "failed"
        self.update(job_id, change)

    def finish(self, job_id):
        self.update(job_id, lambda j: j.update(state="done"))

    def run_notes(self, ctx):
        job = self.get(ctx.id)
        flows.run_notes(ctx, self.backend, job["files"], job["options"], self.seed, self.root / "cache")
        self.finish(ctx.id)

    def plan_tables(self, ctx):
        job = self.get(ctx.id)
        view = flows.plan_tables(ctx, self.backend, job["files"], job["options"], self.root / "cache")
        self.update(ctx.id, lambda j: j.update(state="awaiting_plan", plan=view))

    def apply_tables(self, ctx, edits):
        job = self.get(ctx.id)
        flows.apply_tables(ctx, self.backend, job["files"], job["options"], self.seed, edits, self.root / "cache")
        self.finish(ctx.id)

    def delete(self, job_id):
        job = self.get(job_id)
        if job["state"] == "running":
            raise ValueError("wait for this job to finish")
        with self.lock:
            self.jobs.pop(job_id, None)
        shutil.rmtree(self.dir(job_id), ignore_errors=True)
