import asyncio
import json
from types import SimpleNamespace

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from kbws_forge_runtime import AgentInfo, AgentRuntime, RunContext, RunPolicy
from kbws_forge_runtime.execution import ModelExecutor, default_usage_resolver
from kbws_forge_runtime.models import ModelFinished, RunStarted
from kbws_forge_runtime.plugins import Plugin
from kbws_forge_runtime.sinks import TraceStore
from kbws_forge_runtime.workflow import build_chat_graph


class FakeModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


class WaitingGraph:
    def __init__(self):
        self.started = asyncio.Event()
        self.stopped = asyncio.Event()

    async def astream_events(self, *args, **kwargs):
        self.started.set()
        try:
            await asyncio.Event().wait()
            yield {}
        finally:
            self.stopped.set()


class BrokenObserver(Plugin):
    async def on_event(self, event):
        if event.type == "run_finished":
            raise RuntimeError("observer broke")

    async def on_error(self, agent, error):
        raise RuntimeError("error observer broke")


class FailingBefore(BrokenObserver):
    async def before_agent(self, agent, session):
        raise ValueError("business failure")


def context():
    return RunContext(run_id="r", agent_id="a", user_id="u", session_id="s")


async def test_run_start_is_durable_and_reloaded_as_interrupted(tmp_path):
    path = tmp_path / "traces.json"
    store = TraceStore(persist_path=path)
    await store.emit(RunStarted(run_id="r", agent_id="a", session_id="s"))
    assert path.exists()
    assert json.loads(path.read_text())["runs"]["r"]["status"] == "running"
    recovered = TraceStore(persist_path=path).get_run("r")
    assert recovered["status"] == "interrupted"
    assert recovered["events"][0]["type"] == "run_started"
    assert recovered["completed_at"] is not None


async def test_live_trace_preserves_known_usage_before_terminal(tmp_path):
    path = tmp_path / "trace.json"
    store = TraceStore(persist_path=path)
    await store.emit(RunStarted(run_id="r", agent_id="a", session_id="s"))
    await store.emit(
        ModelFinished(
            run_id="r",
            agent_id="a",
            session_id="s",
            call_id="m",
            usage={"input_tokens": 4, "output_tokens": 1, "total_tokens": 5},
        )
    )
    recovered = TraceStore(persist_path=path).get_run("r")
    assert recovered["usage"]["total_tokens"] == 5


async def test_persistence_failure_is_logged(tmp_path, caplog):
    parent = tmp_path / "not-a-directory"
    parent.write_text("occupied")
    store = TraceStore(persist_path=parent / "trace.json")
    await store.emit(RunStarted(run_id="r", agent_id="a", session_id="s"))
    assert "persist" in caplog.text.lower()


async def test_consumer_close_records_one_cancelled_terminal(tmp_path):
    store = TraceStore(persist_path=tmp_path / "trace.json")
    runtime = AgentRuntime(trace_store=store)
    runtime.register_agent(AgentInfo(agent_id="a", name="A"), WaitingGraph())
    stream = runtime.chat_stream("a", "u", "hi")
    start = await anext(stream)
    await stream.aclose()
    assert runtime.active_run_ids() == ()
    trace = store.get_run(start.run_id)
    assert trace["status"] == "cancelled"
    assert [e["type"] for e in trace["events"]] == ["run_started", "run_cancelled"]
    assert (
        TraceStore(persist_path=tmp_path / "trace.json").get_run(start.run_id)["status"]
        == "cancelled"
    )


async def test_consumer_task_cancel_stops_graph_and_records_terminal():
    runtime = AgentRuntime()
    graph = WaitingGraph()
    runtime.register_agent(AgentInfo(agent_id="a", name="A"), graph)
    stream = runtime.chat_stream("a", "u", "hi")
    start = await anext(stream)
    await anext(stream)
    pending = asyncio.create_task(anext(stream))
    await asyncio.wait_for(graph.started.wait(), 2)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    await asyncio.wait_for(graph.stopped.wait(), 2)
    assert runtime.active_run_ids() == ()
    assert runtime.trace_store.get_run(start.run_id)["status"] == "cancelled"


@pytest.mark.parametrize(
    "plugin,expected", [(BrokenObserver(), "run_finished"), (FailingBefore(), "run_failed")]
)
async def test_observer_failure_does_not_replace_business_terminal(plugin, expected, caplog):
    runtime = AgentRuntime(plugins=[plugin])
    runtime.register_agent(
        AgentInfo(agent_id="a", name="A"),
        build_chat_graph(FakeModel(responses=[AIMessage(content="ok")]), instruction="Reply"),
    )
    events = [e async for e in runtime.chat_stream("a", "u", "hi")]
    trace = runtime.trace_store.get_run(events[0].run_id)
    terminals = [
        e["type"]
        for e in trace["events"]
        if e["type"] in {"run_finished", "run_failed", "run_cancelled"}
    ]
    assert terminals == [expected]
    assert events[-1].type == expected
    assert "observer" in caplog.text


def test_explicit_zero_usage_is_known_and_missing_usage_is_not():
    zero = default_usage_resolver(
        SimpleNamespace(usage_metadata={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
    )
    assert zero is not None
    assert zero.completeness == "complete"
    assert default_usage_resolver(SimpleNamespace(usage_metadata={})) is None


async def test_usage_distinguishes_missing_and_partial_calls():
    run = context()
    executor = ModelExecutor(run)
    await executor.ainvoke(lambda: asyncio.sleep(0, result=AIMessage(content="no usage")))
    assert run.usage.completeness == "unknown"
    await executor.ainvoke(
        lambda: asyncio.sleep(
            0,
            result=AIMessage(
                content="ok",
                usage_metadata={"input_tokens": 4, "output_tokens": 1, "total_tokens": 5},
            ),
        )
    )
    assert run.usage.completeness == "partial"
    assert run.usage.total_tokens == 5


async def test_failed_model_attempt_does_not_look_like_known_zero():
    run = context()

    async def fail():
        raise ValueError("connection lost")

    with pytest.raises(ValueError):
        await ModelExecutor(run).ainvoke(fail)
    assert run.usage.completeness == "unknown"


def test_partial_provider_counts_are_not_complete():
    usage = default_usage_resolver(SimpleNamespace(usage_metadata={"total_tokens": 5}))
    assert usage.completeness == "partial"
    assert usage.total_tokens == 5


async def test_trace_retention_preserves_start_and_latest_events():
    store = TraceStore(max_events_per_run=3)
    for i in range(5):
        await store.emit(RunStarted(run_id="r", agent_id="a", session_id="s", sequence=i))
    trace = store.get_run("r")
    assert len(trace["events"]) == 3
    assert trace["events"][0]["sequence"] == 0
    assert trace["events"][-1]["sequence"] == 4
    assert trace["events_dropped"] == 2


async def test_cost_is_unknown_when_one_attempt_has_no_cost():
    run = context()
    run.usage_resolver = lambda response: response
    from kbws_forge_runtime import ModelUsage

    run.reserve_model_call()
    run.record_model_usage(
        ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2, cost_usd=0.01)
    )
    run.reserve_model_call()
    run.record_model_usage(ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2))
    assert run.usage.completeness == "complete"
    assert run.usage.cost_usd is None


async def test_token_budget_fails_closed_after_unmeasured_retry():
    from kbws_forge_runtime.errors import RunUsageUnavailableError

    run = RunContext(
        run_id="r",
        agent_id="a",
        user_id="u",
        session_id="s",
        policy=RunPolicy(model_retries=1, max_total_tokens=100),
    )
    calls = 0

    async def retry():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("response lost")
        return AIMessage(
            content="ok", usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}
        )

    with pytest.raises(RunUsageUnavailableError):
        await ModelExecutor(run).ainvoke(retry)
    assert run.usage.completeness == "partial"


async def test_reload_applies_retention_to_lookup_and_zero_limit(tmp_path):
    path = tmp_path / "traces.json"
    store = TraceStore(persist_path=path)
    for i in range(4):
        await store.emit(RunStarted(run_id=str(i), agent_id="a", session_id="s"))
    restored = TraceStore(persist_path=path, max_runs=2)
    assert restored.get_run("0") is None
    assert restored.list_runs(limit=0) == []
    assert len(restored.list_runs()) == 2


async def test_pending_model_makes_live_usage_partial_and_cost_unknown():
    from kbws_forge_runtime.models import ModelStarted

    store = TraceStore()
    await store.emit(ModelStarted(run_id="r", agent_id="a", session_id="s", call_id="1"))
    await store.emit(
        ModelFinished(
            run_id="r",
            agent_id="a",
            session_id="s",
            call_id="1",
            usage={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2, "cost_usd": 0.01},
        )
    )
    await store.emit(ModelStarted(run_id="r", agent_id="a", session_id="s", call_id="2"))
    assert store.get_run("r")["usage"]["completeness"] == "partial"
    assert store.get_run("r")["usage"]["cost_usd"] is None


async def test_cancel_after_delivered_success_cannot_add_second_terminal():
    runtime = AgentRuntime()
    runtime.register_agent(
        AgentInfo(agent_id="a", name="A"),
        build_chat_graph(FakeModel(responses=[AIMessage(content="ok")]), instruction="Reply"),
    )
    events = []
    async for event in runtime.chat_stream("a", "u", "hi"):
        events.append(event)
        if event.type == "run_finished":
            runtime.cancel(event.run_id)
    terminals = [
        e.type for e in events if e.type in {"run_finished", "run_failed", "run_cancelled"}
    ]
    assert terminals == ["run_finished"]
