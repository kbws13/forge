from __future__ import annotations

from collections.abc import Iterator
from http.client import HTTPConnection
from threading import Thread

import pytest

from kbws_forge_cli.trace_server import (
    TRACE_HOST,
    create_trace_server,
    normalize_api_url,
)


@pytest.fixture
def trace_server() -> Iterator[tuple[str, int]]:
    server = create_trace_server("http://127.0.0.1:9000/api/v1/", port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("http://127.0.0.1:8000/api/v1/", "http://127.0.0.1:8000/api/v1"),
        (" https://agents.example.com/v2 ", "https://agents.example.com/v2"),
    ],
)
def test_normalize_api_url(value: str, expected: str) -> None:
    assert normalize_api_url(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "localhost:8000/api/v1",
        "file:///tmp/agent",
        "http://user:secret@localhost:8000/api/v1",
        "http://localhost:8000/api/v1?token=secret",
        "http://localhost:8000/api/v1#trace",
    ],
)
def test_normalize_api_url_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_api_url(value)


@pytest.mark.parametrize(
    ("path", "content_type", "content"),
    [
        ("/", "text/html", b"Forge Trace"),
        ("/app.js", "text/javascript", b"MAX_RUNS"),
        ("/styles.css", "text/css", b"--canvas"),
        ("/config.json", "application/json", b"http://127.0.0.1:9000/api/v1"),
    ],
)
def test_trace_server_serves_assets(
    trace_server: tuple[str, int],
    path: str,
    content_type: str,
    content: bytes,
) -> None:
    connection = HTTPConnection(*trace_server, timeout=2)
    connection.request("GET", path)
    response = connection.getresponse()
    body = response.read()
    connection.close()

    assert response.status == 200
    assert response.headers["Content-Type"].startswith(content_type)
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert content in body


def test_trace_server_rejects_unknown_paths(trace_server: tuple[str, int]) -> None:
    connection = HTTPConnection(*trace_server, timeout=2)
    connection.request("GET", "/../pyproject.toml")
    response = connection.getresponse()
    response.read()
    connection.close()

    assert response.status == 404


def test_trace_server_binds_to_loopback() -> None:
    server = create_trace_server(port=0)
    try:
        assert server.server_address[0] == TRACE_HOST
    finally:
        server.server_close()
