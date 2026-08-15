"""Real-provider tests for the public SDK contract (no HTTP layer).

The original version exercised a FastAPI router (``kbws_forge_runtime.api``)
that does not exist: the runtime SDK deliberately stays framework-agnostic.
These tests call the public ``AgentRuntime`` API directly instead of an HTTP
endpoint, so they document the actual SDK contract against a real provider.
"""

import pytest
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from kbws_forge_runtime import AgentInfo, AgentRuntime
from kbws_forge_runtime.errors import AgentNotFoundError, RunError
from kbws_forge_runtime.models import RunFinished, RunStarted, TextDelta
from kbws_forge_runtime.workflow import build_chat_graph

pytestmark = pytest.mark.real_provider


def make_runtime(model: ChatOpenAI, instruction: str = "Reply briefly.") -> AgentRuntime:
    runtime = AgentRuntime(plugins=[])
    runtime.register_agent(
        AgentInfo(agent_id="demo", name="Demo", description="Test agent"),
        build_chat_graph(
            model,
            instruction=instruction,
            checkpointer=InMemorySaver(),
        ),
    )
    return runtime


async def test_list_agents_and_chat_with_real_provider(real_model: ChatOpenAI) -> None:
    runtime = make_runtime(
        real_model,
        instruction="Reply with exactly API_CHAT_OK and nothing else.",
    )

    assert runtime.list_agents() == [
        AgentInfo(agent_id="demo", name="Demo", description="Test agent"),
    ]

    result = await runtime.chat("demo", "user-1", "Run now.")
    assert "API_CHAT_OK" in result.content


async def test_create_session_is_idempotent_for_same_agent_and_user(
    real_model: ChatOpenAI,
) -> None:
    runtime = make_runtime(real_model)

    first = runtime.create_session("demo", "user-1")
    second = runtime.create_session("demo", "user-1")
    assert first.session_id == second.session_id

    other = runtime.create_session("demo", "user-2")
    assert other.session_id != first.session_id


async def test_chat_stream_uses_real_provider_events(real_model: ChatOpenAI) -> None:
    runtime = make_runtime(
        real_model,
        instruction="Reply with exactly API_STREAM_OK and nothing else.",
    )

    events = [event async for event in runtime.chat_stream("demo", "user-1", "Run now.")]

    assert isinstance(events[0], RunStarted)
    assert "API_STREAM_OK" in "".join(
        event.text for event in events if isinstance(event, TextDelta)
    )
    assert isinstance(events[-1], RunFinished)
    assert "API_STREAM_OK" in events[-1].message.text


async def test_unknown_agent_raises_agent_not_found(real_model: ChatOpenAI) -> None:
    runtime = make_runtime(real_model)

    with pytest.raises(AgentNotFoundError) as session_error:
        runtime.create_session("missing", "user-1")
    assert session_error.value.code == "E0001"

    with pytest.raises(RunError) as chat_error:
        await runtime.chat("missing", "user-1", "hello")
    assert chat_error.value.code == "E0001"


async def test_chat_rejects_session_from_another_user(real_model: ChatOpenAI) -> None:
    runtime = make_runtime(real_model)
    session = runtime.create_session("demo", "user-1")

    with pytest.raises(RunError) as exc_info:
        await runtime.chat(
            "demo",
            "user-2",
            "hello",
            session_id=session.session_id,
        )
    assert exc_info.value.code == "0003"
