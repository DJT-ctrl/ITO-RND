"""Minimal stateful mock of the Cloudflare API v4 for testing cloudflare-setup.sh.

Logs each request (method + path) to stderr so the test can assert the call
sequence, and keeps DNS records in memory so a second run exercises the
"update existing record" branch.
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

RECORDS = []  # in-memory DNS records


def ok(result):
    return {"success": True, "errors": [], "messages": [], "result": result}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # silence default noise; we log our own line below

    def _send(self, payload, code=200):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def _route(self, method):
        path = self.path.split("?", 1)[0]
        sys.stderr.write(f"MOCK {method} {self.path}\n")
        sys.stderr.flush()
        parts = [p for p in path.split("/") if p]  # e.g. client v4 zones <id> ...

        # /client/v4/zones/<id>
        if method == "GET" and len(parts) == 4 and parts[2] == "zones":
            return self._send(ok({"id": parts[3], "name": "example.com"}))

        # /client/v4/zones/<id>/dns_records
        if parts[2:5:2] == ["zones", "dns_records"] and len(parts) == 5:
            if method == "GET":
                return self._send(ok(RECORDS))
            if method == "POST":
                rec = self._read_body()
                rec["id"] = "rec-created"
                RECORDS.append(rec)
                return self._send(ok(rec))

        # /client/v4/zones/<id>/dns_records/<rid>
        if method == "PUT" and len(parts) == 6 and parts[4] == "dns_records":
            return self._send(ok({"id": parts[5]}))

        # /client/v4/zones/<id>/settings/<name>
        if method == "PATCH" and len(parts) == 6 and parts[4] == "settings":
            return self._send(ok({"id": parts[5], "value": self._read_body().get("value")}))

        self._send({"success": False, "errors": [{"code": 404, "message": f"no mock route: {method} {path}"}]}, 404)

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def do_PUT(self):
        self._route("PUT")

    def do_PATCH(self):
        self._route("PATCH")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
