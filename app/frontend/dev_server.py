"""
Local development server for the browser frontend.

Serves the static files in this directory and forwards API requests to the
FastAPI backend, so the browser talks to a single origin. Nginx plays the same
role on EC2.

Usage (from the repository root, with the backend running on port 8000):
    python app/frontend/dev_server.py
    python app/frontend/dev_server.py --port 8080 --api http://127.0.0.1:8000
"""

import argparse
import http.server
import urllib.error
import urllib.request
from functools import partial
from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parent

# Paths that belong to the FastAPI backend; everything else is a static file.
API_PATHS = ("/register", "/login", "/profile", "/update", "/health", "/docs", "/openapi.json")
FORWARDED_REQUEST_HEADERS = ("Accept", "Authorization", "Content-Type")
FORWARDED_RESPONSE_HEADERS = ("Content-Type", "WWW-Authenticate")
BACKEND_TIMEOUT_SECONDS = 15


class FrontendHandler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript",
        ".css": "text/css",
    }

    def __init__(self, *args, api_url, **kwargs):
        self.api_url = api_url
        super().__init__(*args, **kwargs)

    def is_api_request(self):
        path = self.path.split("?", 1)[0]
        return any(path == api or path.startswith(api + "/") for api in API_PATHS)

    def do_GET(self):
        if self.is_api_request():
            self.forward_to_backend()
        else:
            super().do_GET()

    def do_POST(self):
        self.forward_or_reject()

    def do_PUT(self):
        self.forward_or_reject()

    def forward_or_reject(self):
        if self.is_api_request():
            self.forward_to_backend()
        else:
            self.send_error(404)

    def forward_to_backend(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {
            name: self.headers[name] for name in FORWARDED_REQUEST_HEADERS if self.headers.get(name)
        }
        request = urllib.request.Request(
            self.api_url + self.path, data=body, headers=headers, method=self.command
        )
        try:
            with urllib.request.urlopen(request, timeout=BACKEND_TIMEOUT_SECONDS) as response:
                self.relay(response.status, response.headers, response.read())
        except urllib.error.HTTPError as error:
            # 4xx/5xx from FastAPI: pass the original response through.
            self.relay(error.code, error.headers, error.read())
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            # Backend unreachable: answer like a reverse proxy would.
            self.relay(
                502,
                {"Content-Type": "application/json"},
                b'{"detail": "The backend is unavailable."}',
            )

    def relay(self, status, headers, body):
        self.send_response(status)
        for name in FORWARDED_RESPONSE_HEADERS:
            if headers.get(name):
                self.send_header(name, headers[name])
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        # Always load the latest files while developing.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="FastAPI base URL")
    args = parser.parse_args()

    handler = partial(
        FrontendHandler, directory=str(FRONTEND_DIR), api_url=args.api.rstrip("/")
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"Frontend: http://127.0.0.1:{args.port}/  (API forwarded to {args.api})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
