"""Serve the review page on this computer only.

    python -m deid.review.server --audit runs/agent-meta-dev.audit.json

Binds to 127.0.0.1, rejects requests whose Host header is not the local address
(a guard against DNS rebinding), and requires a custom header on every change so
another website cannot post to it. The audit file holds original identifiers:
synthetic data only. Decisions are saved beside the audit file after every click.
"""

import argparse
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .decisions import Store

PAGE = Path(__file__).with_name("page.html")
HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                               "connect-src 'self'; base-uri 'none'; form-action 'none'",
}
MAX_BODY = 1_000_000


class Handler(BaseHTTPRequestHandler):
    server_version = "deid-review"

    def log_message(self, *args):
        pass

    def send(self, status, body, content_type="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        for key, value in HEADERS.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def host_ok(self):
        port = self.server.server_address[1]
        return self.headers.get("Host", "") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def do_GET(self):
        if not self.host_ok():
            return self.send(403, {"error": "bad host"})
        store = self.server.store
        if self.path == "/":
            return self.send(200, PAGE.read_bytes(), "text/html")
        if self.path == "/api/state":
            with self.server.lock:
                return self.send(200, {
                    "summary": store.audit["summary"], "notes": store.audit["notes"],
                    "views": {nid: store.view(nid) for nid in store.notes}, "reviewer": store.reviewer})
        self.send(404, {"error": "not found"})

    def do_POST(self):
        if not self.host_ok():
            return self.send(403, {"error": "bad host"})
        if self.headers.get("X-Review") != "1":
            return self.send(403, {"error": "missing header"})
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self.send(413, {"error": "too large"})
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self.send(400, {"error": "bad json"})
        store = self.server.store
        try:
            with self.server.lock:
                if self.path == "/api/op" and isinstance(body, dict) and isinstance(body.get("op"), dict):
                    return self.send(200, store.apply(body.get("note_id"), body["op"]))
                if self.path == "/api/export":
                    return self.send(200, store.export())
        except ValueError as error:
            return self.send(400, {"error": str(error)})
        self.send(404, {"error": "not found"})


def make_server(store, port=0):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.store, server.lock = store, threading.Lock()
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--audit", required=True, help="an .audit.json file from the agent or deid.audit.run")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--reviewer", default="reviewer", help="name recorded with each decision")
    parser.add_argument("--open", action="store_true", help="open the page in the default browser")
    parser.add_argument("--export", action="store_true", help="write the reviewed notes and log, then exit")
    args = parser.parse_args(argv)
    store = Store(args.audit, args.reviewer)
    if args.export:
        print(json.dumps(store.export(), indent=2, sort_keys=True))
        return 0
    server = make_server(store, args.port)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Review page: {url}  (this computer only; Ctrl+C to stop)\n"
          f"Decisions are saved to {store.path}. Contains original identifiers: synthetic data only.")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
