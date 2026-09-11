#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local preview server for the Kleomed site.

Unlike `python -m http.server`, this forbids browser caching. Otherwise, after
you replace an image or edit the CSS, the browser keeps showing the old version
and you have to hit Ctrl+F5 every time.

Usage:
    python serve.py            # http://localhost:8080
    python serve.py 9000       # another port
"""
import json
import os
import sys
import urllib.error
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

# Where leads.py listens locally. Same default as the service itself.
LEADS_PORT = int(os.environ.get("KLEOMED_PORT", "8081"))


class NoCacheHandler(SimpleHTTPRequestHandler):
    """Serves files with caching disabled and never answers 304."""

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def send_head(self):
        # Drop conditional-request headers so the file is always sent in full.
        for h in ("If-Modified-Since", "If-None-Match"):
            if h in self.headers:
                del self.headers[h]

        # Mirror the production nginx rule: /ceny resolves to ceny.html. The
        # canonical URLs in the pages are extensionless, so without this the
        # preview would answer 404 for exactly the addresses search engines use.
        head, sep, tail = self.path.partition("?")
        if not os.path.splitext(head)[1] and not head.endswith("/"):
            if os.path.isfile(self.translate_path(head) + ".html"):
                self.path = head + ".html" + sep + tail

        return super().send_head()

    def send_error(self, code, message=None, explain=None):
        """Serve the real 404 page instead of the stock plain-text one, so the
        page can be checked locally the same way visitors will see it."""
        if code == 404 and self.path.startswith("/site/"):
            page = os.path.join(self.directory, "site", "404.html")
            if os.path.isfile(page):
                with open(page, "rb") as f:
                    body = f.read()
                self.send_response(404)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)
                return
        return super().send_error(code, message, explain)

    def do_POST(self):
        """Forward /api/ to the leads service, the way nginx does in production.

        Without this the booking form could only be tested against the live
        server, and a broken form is the one bug on this site that costs
        actual patients."""
        if not self.path.startswith("/api/"):
            return self.send_error(405, "Method Not Allowed")

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        body = self.rfile.read(length) if length else b""

        url = "http://127.0.0.1:%d%s" % (LEADS_PORT, self.path)
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": self.headers.get("Content-Type", "application/json")})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                code, payload = r.status, r.read()
        except urllib.error.HTTPError as e:
            code, payload = e.code, e.read()
        except OSError:
            code = 502
            payload = json.dumps(
                {"ok": False, "error": "Сервис заявок не запущен (leads.py)"},
                ensure_ascii=False).encode("utf-8")

        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        msg = fmt % args
        if " 404 " in msg or " 500 " in msg:
            sys.stderr.write("%s\n" % msg)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    root = os.path.dirname(os.path.abspath(__file__))
    handler = partial(NoCacheHandler, directory=root)
    srv = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print("Site:     http://localhost:%d/site/" % port)
    print("Original: http://localhost:%d/" % port)
    print("Browser cache disabled - files are always re-sent. Ctrl+C to stop.")
    sys.stdout.flush()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
