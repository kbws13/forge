"""Assistant agent tools."""

from datetime import UTC, datetime

from kbws_forge_runtime.tools import tool


@tool
def current_time() -> str:
    """Return the current UTC time in ISO 8601 format."""
    return datetime.now(UTC).isoformat()


@tool
def add(a: float, b: float) -> float:
    """Add two numbers and return the sum."""
    return a + b
