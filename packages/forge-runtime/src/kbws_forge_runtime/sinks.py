from __future__ import annotations

from typing import Protocol

from kbws_forge_runtime.models.events import ChatEvent


class EventSink(Protocol):
    async def emit(self, event: ChatEvent) -> None: ...


class InMemoryEventSink:
    """Process-local event collector for tests and development UIs."""

    def __init__(self) -> None:
        self._events: list[ChatEvent] = []

    async def emit(self, event: ChatEvent) -> None:
        self._events.append(event)

    def events(self, run_id: str | None = None) -> tuple[ChatEvent, ...]:
        if run_id is None:
            return tuple(self._events)
        return tuple(event for event in self._events if event.run_id == run_id)


__all__ = ["EventSink", "InMemoryEventSink"]
