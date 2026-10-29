"""The local web app: a front page, progress, the review page and downloads.

    python -m deid.app                 # offline rules, no model, no network
    python -m deid.app --live          # hosted models (Meta Model API); synthetic data only

Binds to 127.0.0.1 only, rejects a Host header that is not the local address (a guard
against DNS rebinding), and needs a custom header on every change so another website
cannot post to it. Uploads are sent as the raw request body, one file per request.
Nothing is sent to a hosted service unless the app was started with --live and the
person has ticked that the content is synthetic or public.
"""

import argparse
import json
import re
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from deid.review import server as review_server
from deid.review.decisions import Store

from . import downloads, samples
from .backend import live_backend, offline_backend
from .jobs import ID_PATTERN, MAX_FILE_BYTES, JobStore
from .flows import TYPE_HELP

PAGE = Path(__file__).with_name("app.html")
HEADERS = review_server.HEADERS
VIEW_CSP = "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
MAX_JSON = 6_000_000
JOB = re.compile(r"/api/jobs/([0-9a-f]{12})(?:/([a-z]+))?")
JOB_PAGE = re.compile(r"/job/([0-9a-f]{12})/(review|audit-report|api/state|api/op|api/export|download/[\w.\- ]+)")


class Handler(BaseHTTPRequestHandler):
    server_version = "deid-app"

    def log_message(self, *args):
        pass

    def send(self, status, body, content_type="application/json", extra=None):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        for key, value in {**HEADERS, **(extra or {})}.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def host_ok(self):
        port = self.server.server_address[1]
        return self.headers.get("Host", "") in (f"127.0.0.1:{port}", f"localhost:{port}")

    @property
    def jobs(self):
        return self.server.jobs

    def read_body(self, limit):
        length = int(self.headers.get("Content-Length") or 0)
        if length > limit:
            raise OverflowError
        return self.rfile.read(length)

    def read_json(self):
        try:
            body = json.loads(self.read_body(MAX_JSON) or b"{}")
        except ValueError:
            raise ValueError("the request was not valid JSON") from None
        if not isinstance(body, dict):
            raise ValueError("expected a JSON object")
        return body

    # --- GET ---------------------------------------------------------------------------
    def do_GET(self):
        if not self.host_ok():
            return self.send(403, {"error": "bad host"})
        try:
            self.get(unquote(urlsplit(self.path).path))
        except KeyError:
            self.send(404, {"error": "not found"})
        except ValueError as err:
            self.send(400, {"error": str(err)})

    def get(self, path):
        if path == "/":
            return self.send(200, PAGE.read_bytes(), "text/html")
        if path == "/api/info":
            return self.send(200, {"backend": self.server.backend.describe(), "max_job_tokens": self.jobs.max_job_tokens,
                                   "max_file_bytes": MAX_FILE_BYTES, "type_help": TYPE_HELP,
                                   "samples": sorted(samples.SAMPLES)})
        if path == "/api/jobs":
            return self.send(200, self.jobs.listing())
        m = JOB.fullmatch(path)
        if m and not m.group(2):
            return self.send(200, self.snapshot(m.group(1)))
        m = JOB_PAGE.fullmatch(path)
        if not m:
            raise KeyError(path)
        job_id, what = m.groups()
        if what == "review":
            self.review_store(job_id)
            return self.send(200, review_server.page_bytes(f"/job/{job_id}", f"/#{job_id}"), "text/html")
        if what == "audit-report":
            job = self.jobs.get(job_id)
            files = downloads.available(job, self.jobs.dir(job_id), self.review_store(job_id) if job["kind"] == "notes" else None)
            if "audit-report.html" not in files:
                raise KeyError(path)
            return self.send(200, files["audit-report.html"][1](), "text/html", {"Content-Security-Policy": VIEW_CSP})
        if what == "api/state":
            with self.server.lock:
                return self.send(200, review_server.state_payload(self.review_store(job_id)))
        return self.download(job_id, what.split("/", 1)[1])

    def snapshot(self, job_id):
        job = self.jobs.get(job_id)
        review = self.review_store(job_id) if job["state"] == "done" and job["kind"] == "notes" else None
        files = downloads.available(job, self.jobs.dir(job_id), review)
        job["downloads"] = [{"name": n, "warning": w, "note": note} for n, (_, _, w, note) in files.items()]
        job["can_review"] = review is not None
        return job

    def download(self, job_id, name):
        job = self.jobs.get(job_id)
        review = self.review_store(job_id) if job["state"] == "done" and job["kind"] == "notes" else None
        files = downloads.available(job, self.jobs.dir(job_id), review)
        if name not in files:
            raise KeyError(name)
        ctype, load, _, _ = files[name]
        with self.server.lock:
            data = load()
        self.send(200, data, ctype, {"Content-Disposition": f'attachment; filename="{name}"'})

    def review_store(self, job_id):
        job = self.jobs.get(job_id)
        if job["state"] != "done" or job["kind"] != "notes":
            raise KeyError(job_id)
        with self.server.lock:
            if job_id not in self.server.reviews:
                self.server.reviews[job_id] = Store(self.jobs.dir(job_id) / "notes.audit.json", self.server.reviewer)
            return self.server.reviews[job_id]

    # --- POST --------------------------------------------------------------------------
    def do_POST(self):
        if not self.host_ok():
            return self.send(403, {"error": "bad host"})
        if self.headers.get("X-Review") != "1":
            return self.send(403, {"error": "missing header"})
        try:
            self.post(urlsplit(self.path))
        except OverflowError:
            self.send(413, {"error": "too large"})
        except KeyError:
            self.send(404, {"error": "not found"})
        except ValueError as err:
            self.send(400, {"error": str(err)})

    def post(self, url):
        path = url.path
        if path == "/api/jobs":
            body = self.read_json()
            return self.send(200, self.jobs.create(str(body.get("title") or "")))
        if path == "/api/jobs/sample":
            which = self.read_json().get("which")
            if which not in samples.SAMPLES:
                raise ValueError("unknown sample")
            job = self.jobs.create(f"sample {which}")
            for name, data in samples.SAMPLES[which]():
                self.jobs.add_file(job["id"], name, data)
            return self.send(200, self.jobs.get(job["id"]))
        m = JOB.fullmatch(path)
        if m and m.group(2):
            return self.job_action(m.group(1), m.group(2), url)
        m = JOB_PAGE.fullmatch(path)
        if m and m.group(2) in ("api/op", "api/export"):
            store = self.review_store(m.group(1))
            body = self.read_json() if m.group(2) == "api/op" else {}
            with self.server.lock:
                reply = review_server.post_payload(store, "/" + m.group(2), body)
            if reply is not None:
                return self.send(200, reply)
        raise KeyError(path)

    def job_action(self, job_id, action, url):
        jobs = self.jobs
        if action == "file":
            name = (parse_qs(url.query).get("name") or [""])[0]
            return self.send(200, jobs.add_file(job_id, name, self.read_body(MAX_FILE_BYTES)))
        body = self.read_json()
        if action == "text":
            text = body.get("text")
            if not isinstance(text, str):
                raise ValueError("send the text as a string")
            entry = jobs.add_text(job_id, text)
        elif action == "kind":
            jobs.set_kind(job_id, body.get("index"), body.get("kind"))
            entry = None
        elif action == "start":
            jobs.start(job_id, body.get("options"))
            entry = None
        elif action == "plan":
            jobs.submit_plan(job_id, body.get("edits"))
            entry = None
        elif action == "delete":
            jobs.delete(job_id)
            with self.server.lock:
                self.server.reviews.pop(job_id, None)
            return self.send(200, {"deleted": job_id})
        else:
            raise KeyError(action)
        self.send(200, entry if entry is not None else self.jobs.get(job_id))


def make_server(store, port=0, reviewer="reviewer"):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.jobs, server.backend, server.reviewer = store, store.backend, reviewer
    server.lock, server.reviews = threading.RLock(), {}
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--live", action="store_true",
                        help="use the hosted models (text, audio and images are sent to the provider: synthetic data only)")
    parser.add_argument("--provider", choices=("meta", "custom"), default="meta", help="hosted provider with --live")
    parser.add_argument("--port", type=int, default=8780)
    parser.add_argument("--data-dir", default="runs/app", help="where jobs are kept (git-ignored; holds original text)")
    parser.add_argument("--max-job-tokens", type=int, default=100_000, help="most tokens one job may use with --live")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--reviewer", default="reviewer", help="name recorded with each review decision")
    parser.add_argument("--open", action="store_true", help="open the page in the default browser")
    args = parser.parse_args(argv)
    backend = live_backend(args.provider) if args.live else offline_backend()
    server = make_server(JobStore(args.data_dir, backend, args.max_job_tokens, args.seed), args.port, args.reviewer)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"De-identification app: {url}  (this computer only; Ctrl+C to stop)")
    print(f"Engine: {backend.label}. " + ("Content you add is SENT to the hosted service: synthetic or public data only."
                                          if backend.hosted else "Nothing is sent anywhere."))
    print(f"Jobs are kept in {args.data_dir} and hold original text: synthetic data only.")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
