import pytest
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from kbws_forge_runtime import AgentInfo, AgentRuntime
from kbws_forge_runtime.workflow import build_chat_graph

pytestmark = pytest.mark.real_provider


async def test_runtime_calls_real_deepseek_provider(real_model: ChatOpenAI) -> None:
    runtime = AgentRuntime(plugins=[])
    runtime.register_agent(
        AgentInfo(agent_id="real-deepseek", name="Real DeepSeek"),
        build_chat_graph(
            real_model,
            instruction="Reply with exactly FORGE_RUNTIME_OK and nothing else.",
            checkpointer=InMemorySaver(),
        ),
    )

    result = await runtime.chat("real-deepseek", "provider-test", "Run the check.")

    assert "FORGE_RUNTIME_OK" in result.content
    assert result.usage.completeness == "complete"
    assert result.usage.total_tokens > 0
    print("text usage:", result.usage.model_dump())


async def test_real_tool_structured_history_and_stream_usage(real_model_factory) -> None:
    from pydantic import BaseModel

    from kbws_forge_runtime.tools import tool

    class Answer(BaseModel):
        result: int

    calls = []

    @tool
    def add_numbers(a: int, b: int) -> int:
        """Add two integers; use the returned value as the final result."""
        calls.append((a, b))
        return a + b

    runtime = AgentRuntime()
    runtime.register_agent(
        AgentInfo(agent_id="calc", name="Calculator"),
        build_chat_graph(
            real_model_factory(max_tokens=800),
            instruction=(
                "Always call add_numbers first. After receiving its result, "
                "call the structured output tool with that result. "
                "Never call both tools in the same response."
            ),
            tools=[add_numbers],
            output_schema=Answer,
            checkpointer=InMemorySaver(),
        ),
    )
    session_id = None
    for prompt, expected in (("Add 15 and 27", 42), ("Now add 3 and 8", 11)):
        events = [
            e
            async for e in runtime.chat_stream(
                "calc", "provider-test", prompt, session_id=session_id
            )
        ]
        terminal = events[-1]
        assert terminal.type == "run_finished", str(terminal)
        assert terminal.parsed.result == expected
        assert terminal.tool_calls == 1
        assert terminal.usage.completeness == "complete"
        assert terminal.usage.total_tokens > 0
        assert any(e.type == "tool_finished" for e in events)
        session_id = terminal.session_id
        print("tool+structured usage:", terminal.usage.model_dump())
    assert calls == [(15, 27), (3, 8)]
