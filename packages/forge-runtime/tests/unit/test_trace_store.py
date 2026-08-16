"""TraceStore: run recording, listing, lookup, pruning, persistence."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from kbws_forge_runtime.models import (
    MessageCreated,
    ModelFinished,
    RunFinished,
    RunStarted,
    TextDelta,
    ToolFinished,
    ToolStarted,
)
from kbws_forge_runtime.models.messages import ChatMessage
from kbws_forge_runtime.sinks import TraceStore

RUN_ID = "run-abc"
AGENT_ID = "agent-1"
SESSION_ID = "sess-1"


def _event(model: type, **overrides):
    defaults = {
        "run_id": RUN_ID,
        "agent_id": AGENT_ID,
        "session_id": SESSION_ID,
        "created_at": datetime.now(UTC),
    }
    return model(**(defaults | overrides))


def _user_message() -> ChatMessage:
    return ChatMessage.user("现在几点？")


def _full_run_events() -> list:
    return [
        _event(RunStarted, sequence=1),
        _event(MessageCreated, sequence=2, message=_user_message()),
        _event(
            ModelFinished,
            sequence=3,
            call_id="c1",
            usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        ),
        _event(ToolStarted, sequence=4, tool_name="current_time", call_id="t1"),
        _event(
            ToolFinished, sequence=5, tool_name="current_time", tool_output="12:00", call_id="t1"
        ),
        _event(TextDelta, sequence=6, text="hi"),
        _event(
            RunFinished,
            sequence=7,
            message=ChatMessage.assistant("hi"),
            duration_ms=100.0,
            model_calls=2,
            tool_calls=1,
            usage={"input_tokens": 40, "output_tokens": 10, "total_tokens": 50},
        ),
    ]


async def test_records_run_with_summary_and_events() -> None:
    store = TraceStore()
    for event in _full_run_events():
        await store.emit(event)

    runs = store.list_runs()
    assert len(runs) == 1
    summary = runs[0]
    assert summary["run_id"] == RUN_ID
    assert summary["agent_id"] == AGENT_ID
    assert summary["status"] == "finished"
    assert summary["prompt"] == "现在几点？"
    assert summary["duration_ms"] == 100.0
    assert summary["model_calls"] == 2
    assert summary["tool_calls"] == 1
    assert summary["usage"]["total_tokens"] == 50
    assert "events" not in summary  # list 不带 events

    full = store.get_run(RUN_ID)
    assert full is not None
    assert len(full["events"]) == 7
    assert full["events"][-1]["type"] == "run_finished"


async def test_running_run_has_partial_state() -> None:
    store = TraceStore()
    await store.emit(_event(RunStarted, sequence=1))
    await store.emit(_event(MessageCreated, sequence=2, message=_user_message()))

    summary = store.list_runs()[0]
    assert summary["status"] == "running"
    assert summary["model_calls"] == 0


async def test_newest_first_and_cap() -> None:
    store = TraceStore(max_runs=3)
    for index in range(5):
        await store.emit(_event(RunStarted, run_id=f"run-{index}", sequence=1))
        await store.emit(
            _event(
                RunFinished, run_id=f"run-{index}", sequence=2, message=ChatMessage.assistant("ok")
            ),
        )

    runs = store.list_runs()
    assert [run["run_id"] for run in runs] == ["run-4", "run-3", "run-2"]
    assert store.get_run("run-0") is None
    assert store.get_run("run-4") is not None


async def test_delete_and_clear() -> None:
    store = TraceStore()
    for event in _full_run_events():
        await store.emit(event)

    assert store.delete_run("missing") is False
    assert store.delete_run(RUN_ID) is True
    assert store.list_runs() == []

    await store.emit(_event(RunStarted, sequence=1))
    await store.emit(_event(RunStarted, run_id="other", sequence=1))
    store.clear()
    assert store.list_runs() == []


async def test_persist_roundtrip(tmp_path) -> None:
    path = tmp_path / "traces" / "traces.json"
    store = TraceStore(persist_path=path)
    for event in _full_run_events():
        await store.emit(event)
    assert path.exists()

    reloaded = TraceStore(persist_path=path)
    summary = reloaded.list_runs()[0]
    assert summary["run_id"] == RUN_ID
    assert summary["status"] == "finished"
    full = reloaded.get_run(RUN_ID)
    assert len(full["events"]) == 7


async def test_persist_ignores_corrupt_file(tmp_path) -> None:
    path = tmp_path / "traces.json"
    path.write_text("{not json", encoding="utf-8")
    store = TraceStore(persist_path=path)
    assert store.list_runs() == []
    await store.emit(_event(RunStarted, sequence=1))
    assert store.list_runs()[0]["status"] == "running"


@pytest.mark.parametrize("limit", [1, 10, None])
async def test_list_limit(limit) -> None:
    store = TraceStore()
    for index in range(4):
        await store.emit(_event(RunStarted, run_id=f"r{index}", sequence=1))
        await store.emit(
            _event(RunFinished, run_id=f"r{index}", sequence=2, message=ChatMessage.assistant("ok"))
        )
    runs = store.list_runs(limit=limit)
    expected = 4 if limit is None else min(limit, 4)
    assert len(runs) == expected
