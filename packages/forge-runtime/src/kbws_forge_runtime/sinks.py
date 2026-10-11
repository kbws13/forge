from __future__ import annotations

import json
import logging
import threading
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from kbws_forge_runtime.models.events import ChatEvent

logger = logging.getLogger("kbws_forge_runtime")


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


_TERMINAL_STATUS = {
    "run_finished": "finished",
    "run_failed": "failed",
    "run_cancelled": "cancelled",
}


def _message_text(message: dict[str, Any] | None) -> str:
    """Extract the concatenated text of a serialized ChatMessage."""
    if not message:
        return ""
    return "".join(
        part.get("text", "")
        for part in (message.get("parts") or [])
        if isinstance(part, dict) and part.get("type") == "text"
    )


class TraceStore(EventSink):
    """Records every run's events keyed by ``run_id``, newest-first listing.

    ``AgentRuntime`` records into a store automatically; services can pass a
    configured instance (e.g. one with ``persist_path``) via
    ``AgentRuntime(trace_store=store)``. This makes every run visible to trace
    UIs regardless of which client initiated it.
    """

    def __init__(
        self,
        max_runs: int = 200,
        persist_path: str | Path | None = None,
        max_events_per_run: int = 2000,
    ) -> None:
        self._max_runs = max(1, int(max_runs))
        self._max_events_per_run = max(2, int(max_events_per_run))
        self._persist_path = Path(persist_path) if persist_path else None
        self._runs: dict[str, dict[str, Any]] = {}
        self._order: list[str] = []
        self._lock = threading.Lock()
        if self._persist_path is not None and self._persist_path.exists():
            self._load()

    async def emit(self, event: ChatEvent) -> None:
        data = event.model_dump(mode="json")
        event_type = data.get("type", "")
        run_id = data.get("run_id")
        if not isinstance(run_id, str):
            return

        terminal = _TERMINAL_STATUS.get(event_type)
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                run = {
                    "run_id": run_id,
                    "agent_id": data.get("agent_id", ""),
                    "session_id": data.get("session_id", ""),
                    "prompt": "",
                    "status": "running",
                    "started_at": data.get("created_at"),
                    "completed_at": None,
                    "duration_ms": None,
                    "model_calls": 0,
                    "tool_calls": 0,
                    "usage": {},
                    "events": [],
                    "events_dropped": 0,
                    "_finished_models": 0,
                    "_known_models": 0,
                    "_partial_usage": False,
                    "_cost_models": 0,
                    "_cost_usd": 0,
                }
                self._runs[run_id] = run
                self._order.append(run_id)
                while len(self._order) > self._max_runs:
                    oldest = self._order.pop(0)
                    self._runs.pop(oldest, None)
            run["agent_id"] = data.get("agent_id") or run["agent_id"]
            run["session_id"] = data.get("session_id") or run["session_id"]
            if run["started_at"] is None:
                run["started_at"] = data.get("created_at")
            run["events"].append(data)
            self._trim_events(run)
            if event_type == "model_started":
                run["model_calls"] += 1
            elif event_type == "tool_started":
                run["tool_calls"] += 1
            elif event_type in {"model_finished", "model_failed"}:
                run["_finished_models"] += 1
                run["model_calls"] = max(run["model_calls"], run["_finished_models"])
                usage = data.get("usage") or {}
                completeness = usage.get("completeness", "unknown")
                if completeness != "unknown":
                    run["_known_models"] += 1
                if completeness == "partial":
                    run["_partial_usage"] = True
                for key in ("input_tokens", "output_tokens", "total_tokens"):
                    run["usage"][key] = run["usage"].get(key, 0) + usage.get(key, 0)
                if usage.get("cost_usd") is not None:
                    run["_cost_models"] += 1
                    run["_cost_usd"] += usage["cost_usd"]
            if event_type.startswith("model_"):
                run["usage"]["completeness"] = (
                    "complete"
                    if run["_known_models"] == run["model_calls"] and not run["_partial_usage"]
                    else "partial"
                    if run["_known_models"]
                    else "unknown"
                )
                run["usage"]["cost_usd"] = (
                    run["_cost_usd"]
                    if run["_cost_models"] == run["model_calls"] and run["_cost_models"]
                    else None
                )

            if event_type == "message_created" and not run["prompt"]:
                message = data.get("message")
                if isinstance(message, dict) and message.get("role") == "user":
                    run["prompt"] = _message_text(message)

            if terminal is not None:
                run["status"] = terminal
                run["completed_at"] = data.get("created_at") or run["completed_at"]
                for key in ("duration_ms", "model_calls", "tool_calls", "usage"):
                    if data.get(key) is not None:
                        run[key] = data[key]

        self._persist()

    def _trim_events(self, run: dict[str, Any]) -> None:
        excess = len(run["events"]) - self._max_events_per_run
        if excess > 0:
            del run["events"][1 : 1 + excess]
            run["events_dropped"] = run.get("events_dropped", 0) + excess

    def list_runs(self, limit: int = 100) -> list[dict[str, Any]]:
        """Summaries of recorded runs, newest first (no events payload)."""
        with self._lock:
            if limit is not None and limit <= 0:
                return []
            selected = self._order if limit is None else self._order[-limit:]
            return [self._summary(self._runs[run_id]) for run_id in reversed(selected)]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Full run record (summary + all events), or None when unknown."""
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return None
            full = self._summary(run)
            full["events"] = deepcopy(run["events"])
            return full

    def delete_run(self, run_id: str) -> bool:
        with self._lock:
            if run_id not in self._runs:
                return False
            self._runs.pop(run_id)
            self._order.remove(run_id)
        self._persist()
        return True

    def clear(self) -> None:
        with self._lock:
            self._runs.clear()
            self._order.clear()
        self._persist()

    def _summary(self, run: dict[str, Any]) -> dict[str, Any]:
        return deepcopy(
            {
                key: value
                for key, value in run.items()
                if key != "events" and not key.startswith("_")
            }
        )

    def _persist(self) -> None:
        if self._persist_path is None:
            return
        with self._lock:
            payload = {"order": self._order, "runs": self._runs}
            try:
                self._persist_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self._persist_path.with_name(self._persist_path.name + ".tmp")
                tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
                tmp.replace(self._persist_path)
            except OSError:
                logger.exception("failed to persist traces path=%s", self._persist_path)

    def _load(self) -> None:
        try:
            payload = json.loads(self._persist_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.exception("failed to load traces path=%s", self._persist_path)
            return
        if not isinstance(payload, dict):
            logger.error("invalid trace store path=%s", self._persist_path)
            return
        runs = payload.get("runs")
        order = payload.get("order")
        if not isinstance(runs, dict):
            return
        self._runs = {
            key: value
            for key, value in runs.items()
            if isinstance(key, str)
            and isinstance(value, dict)
            and isinstance(value.get("events"), list)
        }
        self._order = [
            key for key in (order if isinstance(order, list) else []) if key in self._runs
        ]
        self._order.extend(key for key in self._runs if key not in self._order)
        while len(self._order) > self._max_runs:
            self._runs.pop(self._order.pop(0), None)
        for run in self._runs.values():
            self._trim_events(run)
            if run.get("status") == "running":
                run["status"] = "interrupted"
                run["completed_at"] = datetime.now(UTC).isoformat()
        self._persist()


__all__ = ["EventSink", "InMemoryEventSink", "TraceStore"]
