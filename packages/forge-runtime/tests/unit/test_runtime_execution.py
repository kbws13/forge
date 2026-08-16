import asyncio
from typing import Any

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from kbws_forge_runtime import (
    AgentInfo,
    AgentRuntime,
    InMemoryEventSink,
    ModelFinished,
    ModelStarted,
    RunCancelled,
    RunFailed,
    RunFinished,
    RunPolicy,
    ToolFinished,
    ToolPolicy,
    ToolStarted,
)
from kbws_forge_runtime.plugins import Plugin
from kbws_forge_runtime.workflow import build_chat_graph


class ToolCapableFakeModel(FakeMessagesListChatModel):
    def bind_tools(self, tools: Any, **kwargs: Any):
        return self


class Answer(BaseModel):
    value: int


class SlowGraph:
    async def astream_events(self, input, config=None, *, version):
        await asyncio.sleep(60)
        if False:
            yield {}

    async def aget_state(self, config):
        raise AssertionError("cancelled graph must not read final state")


class BrokenAfterPlugin(Plugin):
    async def after_agent(self, agent, result) -> None:
        raise RuntimeError("after hook failed")


class BrokenSink:
    async def emit(self, event) -> None:
        raise RuntimeError("sink unavailable")


async def test_runtime_emits_ordered_action_events_to_sink() -> None:
    model = ToolCapableFakeModel(
        responses=[
            AIMessage(
                content="ok",
                usage_metadata={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
            )
        ]
    )
    sink = InMemoryEventSink()
    runtime = AgentRuntime(event_sinks=[sink])
    runtime.register_agent(
        AgentInfo(agent_id="demo", name="Demo"),
        build_chat_graph(model, instruction="Reply briefly."),
    )

    events = [event async for event in runtime.chat_stream("demo", "user-1", "hello")]

    assert any(isinstance(event, ModelStarted) for event in events)
    assert any(isinstance(event, ModelFinished) for event in events)
    assert isinstance(events[-1], RunFinished)
    assert events[-1].model_calls == 1
    assert events[-1].usage.total_tokens == 3
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert len({event.event_id for event in events}) == len(events)
    assert sink.events(events[0].run_id) == tuple(events)


async def test_runtime_publishes_only_one_terminal_event_when_after_hook_fails() -> None:
    model = ToolCapableFakeModel(responses=[AIMessage(content="ok")])
    sink = InMemoryEventSink()
    runtime = AgentRuntime(plugins=[BrokenAfterPlugin()], event_sinks=[sink])
    runtime.register_agent(
        AgentInfo(agent_id="demo", name="Demo"),
        build_chat_graph(model, instruction="Reply briefly."),
    )

    events = [event async for event in runtime.chat_stream("demo", "user-1", "hello")]

    assert isinstance(events[-1], RunFailed)
    assert not any(isinstance(event, RunFinished) for event in events)
    assert sink.events(events[0].run_id) == tuple(events)


async def test_runtime_isolates_event_sink_failures(caplog) -> None:
    model = ToolCapableFakeModel(responses=[AIMessage(content="ok")])
    healthy_sink = InMemoryEventSink()
    runtime = AgentRuntime(event_sinks=[BrokenSink(), healthy_sink])
    runtime.register_agent(
        AgentInfo(agent_id="demo", name="Demo"),
        build_chat_graph(model, instruction="Reply briefly."),
    )

    events = [event async for event in runtime.chat_stream("demo", "user-1", "hello")]

    assert isinstance(events[-1], RunFinished)
    assert healthy_sink.events(events[0].run_id) == tuple(events)
    assert "event sink failed" in caplog.text


async def test_runtime_tool_policy_denial_fails_the_run() -> None:
    model = ToolCapableFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "upper",
                        "args": {"word": "forge"},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            )
        ]
    )

    from kbws_forge_runtime.tools import tool

    @tool
    def upper(word: str) -> str:
        """Convert a word to uppercase."""
        return word.upper()

    runtime = AgentRuntime()
    runtime.register_agent(
        AgentInfo(agent_id="demo", name="Demo"),
        build_chat_graph(model, instruction="Use the tool.", tools=[upper]),
    )
    policy = RunPolicy(tool_policy=ToolPolicy(denied_tools={"upper"}))

    events = [
        event async for event in runtime.chat_stream("demo", "user-1", "hello", policy=policy)
    ]

    assert isinstance(events[-1], RunFailed)
    assert events[-1].error_code == "0010"
    assert events[-1].tool_calls == 0
    model_event = next(event for event in events if isinstance(event, ModelFinished))
    assert model_event.tool_calls[0]["name"] == "upper"


async def test_runtime_executes_allowed_tool_and_records_actions() -> None:
    model = ToolCapableFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "upper",
                        "args": {"word": "forge"},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content="FORGE"),
        ]
    )

    from kbws_forge_runtime.tools import tool

    @tool
    def upper(word: str) -> str:
        """Convert a word to uppercase."""
        return word.upper()

    runtime = AgentRuntime()
    runtime.register_agent(
        AgentInfo(agent_id="demo", name="Demo"),
        build_chat_graph(model, instruction="Use the tool.", tools=[upper]),
    )

    events = [event async for event in runtime.chat_stream("demo", "user-1", "hello")]

    assert any(isinstance(event, ToolStarted) for event in events)
    assert any(isinstance(event, ToolFinished) for event in events)
    assert isinstance(events[-1], RunFinished)
    assert events[-1].tool_calls == 1
    assert events[-1].message.text == "FORGE"


async def test_structured_output_retry_obeys_model_call_budget() -> None:
    model = ToolCapableFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "__forge_structured_output",
                        "args": {"value": "invalid"},
                        "id": "call-1",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "__forge_structured_output",
                        "args": {"value": 1},
                        "id": "call-2",
                        "type": "tool_call",
                    }
                ],
            ),
        ]
    )
    runtime = AgentRuntime(default_policy=RunPolicy(max_model_calls=1))
    runtime.register_agent(
        AgentInfo(agent_id="demo", name="Demo"),
        build_chat_graph(model, instruction="Return an answer.", output_schema=Answer),
    )

    events = [event async for event in runtime.chat_stream("demo", "user-1", "hello")]

    assert isinstance(events[-1], RunFailed)
    assert events[-1].error_code == "0009"
    assert events[-1].model_calls == 1


async def test_runtime_can_cancel_an_active_run() -> None:
    runtime = AgentRuntime()
    runtime.register_agent(AgentInfo(agent_id="slow", name="Slow"), SlowGraph())
    stream = runtime.chat_stream("slow", "user-1", "hello")

    started = await anext(stream)
    await anext(stream)
    pending = asyncio.create_task(anext(stream))
    await asyncio.sleep(0)

    assert runtime.cancel(started.run_id, "cancelled in test")
    cancelled = await pending
    assert isinstance(cancelled, RunCancelled)
    assert cancelled.reason == "cancelled in test"
    await stream.aclose()
    assert runtime.active_run_ids() == ()


async def test_runtime_timeout_fails_a_stalled_graph() -> None:
    runtime = AgentRuntime(default_policy=RunPolicy(timeout_seconds=0.01))
    runtime.register_agent(AgentInfo(agent_id="slow", name="Slow"), SlowGraph())

    events = [event async for event in runtime.chat_stream("slow", "user-1", "hello")]

    assert isinstance(events[-1], RunFailed)
    assert events[-1].error_code == "0008"
