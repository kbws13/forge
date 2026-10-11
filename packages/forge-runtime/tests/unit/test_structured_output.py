"""Structured results must belong to this run and preserve tool message history."""

from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from pydantic import BaseModel

from kbws_forge_runtime import AgentInfo, AgentRuntime, RunFailed, RunFinished
from kbws_forge_runtime.middleware import ModelMiddleware
from kbws_forge_runtime.tools import tool
from kbws_forge_runtime.workflow import build_chat_graph


class Answer(BaseModel):
    value: int


class ToolModel(FakeMessagesListChatModel):
    def bind_tools(self, tools: Any, **kwargs: Any):
        return self


def answer(value: Any, call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "__forge_structured_output",
                "args": {"value": value},
                "id": call_id,
                "type": "tool_call",
            }
        ],
    )


def assert_closed_history(messages: list[BaseMessage]) -> None:
    pending: set[str] = set()
    for message in messages:
        if isinstance(message, ToolMessage):
            assert message.tool_call_id in pending, "orphaned tool response"
            pending.remove(message.tool_call_id)
        else:
            assert not pending, "assistant tool calls must be answered before the next message"
            if isinstance(message, AIMessage):
                pending.update(call["id"] for call in message.tool_calls)
                pending.update(call["id"] for call in message.invalid_tool_calls)
    assert not pending, "model input contains unanswered tool calls"


class ProtocolGuard(ModelMiddleware):
    async def before_model(self, state, messages):
        assert_closed_history(messages)
        return None


def runtime_for(responses: list[AIMessage], *, guard: bool = False):
    graph = build_chat_graph(
        ToolModel(responses=responses),
        instruction="Return an integer answer.",
        output_schema=Answer,
        middleware=[ProtocolGuard()] if guard else [],
    )
    runtime = AgentRuntime()
    runtime.register_agent(AgentInfo(agent_id="structured", name="Structured"), graph)
    return runtime, graph


async def test_second_turn_without_output_cannot_reuse_previous_parsed_result():
    runtime, graph = runtime_for([answer(1, "first"), AIMessage(content="no result")])
    first = await runtime.chat("structured", "user", "first")
    assert first.parsed == Answer(value=1)

    events = [
        event
        async for event in runtime.chat_stream(
            "structured",
            "user",
            "second",
            first.session_id,
        )
    ]

    assert isinstance(events[-1], RunFailed)
    assert not any(isinstance(event, RunFinished) for event in events)
    state = await graph.aget_state({"configurable": {"thread_id": first.session_id}})
    assert state.values.get("parsed") is None


@pytest.mark.parametrize(
    "responses",
    [
        [AIMessage(content="no structured answer")],
        [answer("invalid", "first"), answer("still invalid", "retry")],
    ],
)
async def test_missing_or_invalid_structured_output_fails_explicitly(responses):
    runtime, _ = runtime_for(responses)
    events = [event async for event in runtime.chat_stream("structured", "user", "hello")]
    assert isinstance(events[-1], RunFailed)
    assert events[-1].error_code == "0013"
    assert "structured output" in events[-1].error_message.lower()


async def test_successful_structured_tool_calls_are_closed_before_next_turn():
    runtime, graph = runtime_for([answer(1, "first"), answer(2, "second")], guard=True)
    first = await runtime.chat("structured", "user", "first")
    second = await runtime.chat("structured", "user", "second", first.session_id)
    assert second.parsed == Answer(value=2)
    state = await graph.aget_state({"configurable": {"thread_id": first.session_id}})
    assert_closed_history(state.values["messages"])


async def test_validation_retry_closes_calls_and_preserves_original_request():
    class RequestGuard(ProtocolGuard):
        async def before_model(self, state, messages):
            await super().before_model(state, messages)
            assert any(message.content == "answer the original request" for message in messages)

    graph = build_chat_graph(
        ToolModel(responses=[answer("bad", "first"), answer(3, "retry")]),
        instruction="Return an integer answer.",
        output_schema=Answer,
        middleware=[RequestGuard()],
    )
    runtime = AgentRuntime()
    runtime.register_agent(AgentInfo(agent_id="structured", name="Structured"), graph)
    result = await runtime.chat("structured", "user", "answer the original request")
    assert result.parsed == Answer(value=3)
    state = await graph.aget_state({"configurable": {"thread_id": result.session_id}})
    assert_closed_history(state.values["messages"])


async def test_failed_validation_leaves_closed_history_for_later_turn():
    runtime, graph = runtime_for(
        [
            answer("bad", "first"),
            answer("bad again", "retry"),
            answer(4, "next"),
        ],
        guard=True,
    )
    events = [event async for event in runtime.chat_stream("structured", "user", "first")]
    assert isinstance(events[-1], RunFailed)
    session_id = events[-1].session_id
    state = await graph.aget_state({"configurable": {"thread_id": session_id}})
    assert_closed_history(state.values["messages"])
    result = await runtime.chat("structured", "user", "next", session_id)
    assert result.parsed == Answer(value=4)


async def test_multiple_structured_answers_are_rejected_and_all_calls_closed():
    response = answer(1, "first")
    response.tool_calls.extend(answer(2, "second").tool_calls)
    runtime, graph = runtime_for([response])
    events = [event async for event in runtime.chat_stream("structured", "user", "hello")]
    assert isinstance(events[-1], RunFailed)
    assert events[-1].error_code == "0013"
    state = await graph.aget_state({"configurable": {"thread_id": events[-1].session_id}})
    assert_closed_history(state.values["messages"])


async def test_mixed_terminal_and_real_tool_calls_fail_without_executing_tools():
    executed = []

    @tool
    def double(value: int) -> int:
        """Double a number."""
        executed.append(value)
        return value * 2

    response = answer(2, "output")
    response.tool_calls.append(
        {
            "name": "double",
            "args": {"value": 1},
            "id": "double",
            "type": "tool_call",
        }
    )
    graph = build_chat_graph(
        ToolModel(responses=[response]),
        instruction="Return an answer.",
        output_schema=Answer,
        tools=[double],
    )
    runtime = AgentRuntime()
    runtime.register_agent(AgentInfo(agent_id="structured", name="Structured"), graph)
    events = [event async for event in runtime.chat_stream("structured", "user", "hello")]
    assert isinstance(events[-1], RunFailed)
    assert events[-1].error_code == "0013"
    assert executed == []
    state = await graph.aget_state({"configurable": {"thread_id": events[-1].session_id}})
    assert_closed_history(state.values["messages"])


async def test_real_tool_can_run_before_terminal_structured_output():
    @tool
    def double(value: int) -> int:
        """Double a number."""
        return value * 2

    response = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "double",
                "args": {"value": 2},
                "id": "double",
                "type": "tool_call",
            }
        ],
    )
    graph = build_chat_graph(
        ToolModel(responses=[response, answer(4, "output")]),
        instruction="Call double then return an answer.",
        output_schema=Answer,
        tools=[double],
        middleware=[ProtocolGuard()],
    )
    runtime = AgentRuntime()
    runtime.register_agent(AgentInfo(agent_id="structured", name="Structured"), graph)
    result = await runtime.chat("structured", "user", "double 2")
    assert result.parsed == Answer(value=4)
    assert result.tool_calls == 1


async def test_malformed_tool_arguments_fail_and_leave_closed_history():
    response = AIMessage(
        content="",
        invalid_tool_calls=[
            {
                "name": "__forge_structured_output",
                "args": '{"value":',
                "id": "malformed",
                "error": "Invalid JSON",
                "type": "invalid_tool_call",
            }
        ],
    )
    runtime, graph = runtime_for([response, answer(5, "next")], guard=True)
    events = [event async for event in runtime.chat_stream("structured", "user", "hello")]
    assert isinstance(events[-1], RunFailed)
    assert events[-1].error_code == "0013"
    session_id = events[-1].session_id
    state = await graph.aget_state({"configurable": {"thread_id": session_id}})
    assert_closed_history(state.values["messages"])
    result = await runtime.chat("structured", "user", "next", session_id)
    assert result.parsed == Answer(value=5)
