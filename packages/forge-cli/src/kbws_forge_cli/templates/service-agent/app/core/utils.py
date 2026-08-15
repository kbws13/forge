"""Small helpers."""

from __future__ import annotations

from typing import Any


def sse_frame(event: str, data: Any) -> str:
    """Format one Server-Sent-Events frame."""
    import json

    payload = data.model_dump_json() if hasattr(data, "model_dump_json") else json.dumps(data)
    return f"event: {event}\ndata: {payload}\n\n"
