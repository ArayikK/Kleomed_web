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
import os
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


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
        return super().send_head()

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
