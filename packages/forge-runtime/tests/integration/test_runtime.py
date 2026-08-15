import pytest
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from kbws_forge_runtime import (
    AgentInfo,
    AgentRuntime,
    ChatRequest,
    MessageCreated,
    RunFailed,
    RunFinished,
    RunStarted,
    TextDelta,
    ToolFinished,
    ToolStarted,
)
from kbws_forge_runtime.plugins import Plugin
from kbws_forge_runtime.tools import tool
from kbws_forge_runtime.workflow import build_chat_graph

pytestmark = pytest.mark.real_provider


class RecordPlugin(Plugin):
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def on_user_message(self, request: ChatRequest, session) -> None:
        self.calls.append("user")

    async def before_agent(self, agent, session) -> None:
        self.calls.append("before")

    async def after_agent(self, agent, result) -> None:
        self.calls.append("after")

    async def on_error(self, agent, error) -> None:
        self.calls.append("error")


@tool
def upper(word: str) -> str:
    """Convert one word to uppercase."""
    return word.upper()


async def test_runtime_keeps_real_provider_session_and_calls_plugins(
    real_model: ChatOpenAI,
) -> None:
    graph = build_chat_graph(
        real_model,
        instruction=(
            "When the user asks you to remember a code, remember it and reply SAVED. "
            "When asked for the code later, reply with only that code."
        ),
        checkpointer=InMemorySaver(),
    )
    plugin = RecordPlugin()
    runtime = AgentRuntime(plugins=[plugin])
    runtime.register_agent(AgentInfo(agent_id="memory", name="Memory"), graph)

    first = await runtime.chat("memory", "user-1", "Remember code KBWS_SESSION_7319.")
    second = await runtime.chat("memory", "user-1", "What code did I ask you to remember?")

    assert "SAVED" in first.content.upper()
    assert "KBWS_SESSION_7319" in second.content
    assert first.session_id == second.session_id
    assert plugin.calls == ["user", "before", "after", "user", "before", "after"]


async def test_runtime_streams_real_provider_events(real_model: ChatOpenAI) -> None:
    graph = build_chat_graph(
        real_model,
        instruction="Reply with exactly STREAM_OK and nothing else.",
        checkpointer=InMemorySaver(),
    )
    runtime = AgentRuntime(plugins=[])
    runtime.register_agent(AgentInfo(agent_id="stream", name="Stream"), graph)

    events = [event async for event in runtime.chat_stream("stream", "user-1", "Run now.")]

    assert isinstance(events[0], RunStarted)
    assert isinstance(events[1], MessageCreated)
    assert "STREAM_OK" in "".join(
        event.text for event in events if isinstance(event, TextDelta)
    )
    assert isinstance(events[-1], RunFinished)
    assert "STREAM_OK" in events[-1].message.text


async def test_real_provider_calls_local_tool_and_streams_tool_events(
    real_model: ChatOpenAI,
) -> None:
    runtime = AgentRuntime(plugins=[])
    runtime.register_agent(
        AgentInfo(agent_id="tools", name="Tools"),
        build_chat_graph(
            real_model,
            instruction=(
                "You must call the upper tool with word 'forge'. Do not calculate it yourself. "
                "After the tool returns, reply with only the tool result."
            ),
            tools=[upper],
            checkpointer=InMemorySaver(),
        ),
    )

    events = [event async for event in runtime.chat_stream("tools", "user-1", "Run now.")]

    assert any(isinstance(event, ToolStarted) and event.tool_name == "upper" for event in events)
    assert any(isinstance(event, ToolFinished) and event.tool_name == "upper" for event in events)
    assert isinstance(events[-1], RunFinished)
    assert "FORGE" in events[-1].message.text.upper()


async def test_runtime_normalizes_real_provider_error_and_notifies_plugin(
    real_model_factory,
) -> None:
    plugin = RecordPlugin()
    runtime = AgentRuntime(plugins=[plugin])
    runtime.register_agent(
        AgentInfo(agent_id="broken", name="Broken"),
        build_chat_graph(
            real_model_factory(model="model-that-does-not-exist"),
            instruction="Reply with ERROR_TEST.",
        ),
    )

    events = [event async for event in runtime.chat_stream("broken", "user-1", "Run now.")]

    assert isinstance(events[-1], RunFailed)
    assert events[-1].error_code == "0001"
    assert events[-1].error_message
    assert plugin.calls == ["user", "before", "error"]
