#!/usr/bin/env python3
"""
Local HTTP server for the infographic.

Serves files from this directory and exposes a POST /run-tests endpoint
that re-runs test_infographic.py and returns the result.

Usage:
    python3 serve.py
Then open http://localhost:8765/infographic_dayahead.html
"""
import http.server
import json
import os
import socketserver
import subprocess
import sys

PORT = 8765
DIR = os.path.dirname(os.path.abspath(__file__))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIR, **kwargs)

    def do_POST(self):
        if self.path == "/run-tests":
            try:
                result = subprocess.run(
                    [sys.executable, os.path.join(DIR, "test_infographic.py")],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                ok = result.returncode == 0
                payload = {
                    "ok": ok,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
            except Exception as e:
                payload = {"ok": False, "stdout": "", "stderr": str(e)}

            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        # Quieter logs
        sys.stderr.write(f"[serve] {format % args}\n")


class Server(socketserver.ThreadingTCPServer):
    # Threaded: Chrome keeps idle pre-opened sockets, which hang a single-threaded server
    daemon_threads = True
    allow_reuse_address = True


def main():
    os.chdir(DIR)
    with Server(("127.0.0.1", PORT), Handler) as httpd:
        url = f"http://localhost:{PORT}/infographic_dayahead.html"
        print(f"Serving {DIR}")
        print(f"Open {url}")
        print("Press Ctrl+C to stop.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down.")


if __name__ == "__main__":
    main()
