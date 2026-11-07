"""Local dev server — run the REAL handler code without AWS.

Translates plain HTTP requests into API Gateway proxy events, dispatches them
through ``handlers.handler``, and writes the proxy response back out. This lets
you point the React app at a live local API (the same code that runs in
Lambda) before any AWS infra exists — the 4 PM milestone's "temporary trusted
backend handler using the same API contract".

Run:
    SENTINEL_AUTH_MODE=dev SENTINEL_ADMIN_TOKEN=devtoken \\
        python -m backend.api.local_server

Then in frontend/.env.local:
    VITE_MOCK=false
    VITE_API_BASE_URL=http://localhost:8000/v1

Admin routes (approve/revoke/reset) need header: X-Admin-Token: devtoken
"""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from .handlers import handler

PORT = int(os.environ.get("SENTINEL_API_PORT", "8000"))


class Proxy(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[api] {self.command} {self.path} -> {args[1]}")

    def _event(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length).decode("utf-8") if length else ""
        qs = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        return {
            "httpMethod": self.command,
            "path": parsed.path,
            "queryStringParameters": qs or None,
            "headers": {k: v for k, v in self.headers.items()},
            "body": body,
        }

    def _dispatch(self):
        resp = handler(self._event(), None)
        self.send_response(resp["statusCode"])
        for k, v in (resp.get("headers") or {}).items():
            self.send_header(k, v)
        self.end_headers()
        body = resp.get("body") or ""
        if body:
            self.wfile.write(body.encode("utf-8"))

    # All verbs funnel through the same dispatcher.
    do_GET = do_POST = do_OPTIONS = _dispatch


def main():
    print(f"SentinelOS API (backend={os.environ.get('SENTINEL_BACKEND', 'local')}, "
          f"auth={os.environ.get('SENTINEL_AUTH_MODE', 'prod')}) on http://localhost:{PORT}/v1")
    ThreadingHTTPServer(("127.0.0.1", PORT), Proxy).serve_forever()


if __name__ == "__main__":
    main()
