"""Local static server for the Forge Trace development UI."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from typing import cast
from urllib.parse import urlsplit, urlunsplit

TRACE_HOST = "127.0.0.1"
DEFAULT_TRACE_PORT = 8765
DEFAULT_API_URL = "http://127.0.0.1:8000/api/v1"

_ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
}


def normalize_api_url(value: str) -> str:
    """Validate and normalize the configured Forge API base URL."""
    value = value.strip()
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("API URL must be an absolute http:// or https:// URL")
    if parsed.username or parsed.password:
        raise ValueError("API URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("API URL must not contain a query string or fragment")

    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


class TraceHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], api_url: str) -> None:
        self.api_url = api_url
        super().__init__(server_address, TraceRequestHandler)


class TraceRequestHandler(BaseHTTPRequestHandler):
    server_version = "ForgeTrace/1.0"

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/config.json":
            server = cast(TraceHTTPServer, self.server)
            self._send(
                json.dumps({"apiUrl": server.api_url}).encode(),
                "application/json; charset=utf-8",
            )
            return

        asset = _ASSETS.get(path)
        if asset is None:
            self.send_error(404, "Not found")
            return

        filename, content_type = asset
        content = files("kbws_forge_cli").joinpath("trace_ui", filename).read_bytes()
        self._send(content, content_type)

    def _send(self, content: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src http: https:; img-src 'self' data:; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format: str, *args: object) -> None:
        return


def create_trace_server(
    api_url: str = DEFAULT_API_URL,
    port: int = DEFAULT_TRACE_PORT,
) -> TraceHTTPServer:
    """Create a loopback-only Trace UI server without starting its event loop."""
    return TraceHTTPServer((TRACE_HOST, port), normalize_api_url(api_url))


__all__ = [
    "DEFAULT_API_URL",
    "DEFAULT_TRACE_PORT",
    "TRACE_HOST",
    "TraceHTTPServer",
    "create_trace_server",
    "normalize_api_url",
]
