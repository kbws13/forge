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
