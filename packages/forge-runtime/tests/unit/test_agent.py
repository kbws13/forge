"""Unit tests for Agent aggregation and directory discovery."""

from __future__ import annotations

from pathlib import Path

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langgraph.checkpoint.memory import InMemorySaver

from kbws_forge_runtime import AgentInfo, AgentRuntime
from kbws_forge_runtime.agent import Agent, load_agents
from kbws_forge_runtime.prompts import Message, Prompt
from kbws_forge_runtime.tools import tool


@tool
def _double(x: int) -> int:
    """Double a number."""
    return x * 2


def _fake_model() -> FakeListChatModel:
    return FakeListChatModel(responses=["ok"])


async def test_agent_build_graph_assembles_prompt_and_tools() -> None:
    prompt = Prompt(
        name="test",
        messages=[Message.system("你是{tone}助手"), Message.history()],
    )
    # 注：FakeListChatModel 不支持 bind_tools，故此处不带 tools
    agent = Agent(
        agent_id="t1",
        name="T1",
        prompt=prompt,
        checkpointer=InMemorySaver(),
    )
    graph = await agent.build_graph(_fake_model)

    runtime = AgentRuntime(plugins=[])
    runtime.register_agent(
        AgentInfo(agent_id="t1", name="T1"),
        graph,
    )
    result = await runtime.chat("t1", "u1", "double 3", variables={"tone": "专业"})
    assert result.content == "ok"


async def test_load_agents_discovers_agent_directories(tmp_path: Path) -> None:
    agents_root = tmp_path / "agents"
    agent_dir = agents_root / "hello"
    agent_dir.mkdir(parents=True)
    (agent_dir / "__init__.py").write_text("", encoding="utf-8")
    (agent_dir / "prompts.py").write_text(
        "from kbws_forge_runtime.prompts import Message, Prompt\n"
        "p = Prompt(name='hello', messages=[Message.system('你是助手')])\n",
        encoding="utf-8",
    )
    (agent_dir / "agent.py").write_text(
        "from kbws_forge_runtime.agent import Agent\n"
        "from .prompts import p\n"
        "agent = Agent(agent_id='hello', name='Hello', prompt=p)\n",
        encoding="utf-8",
    )
    # shared 层：无 agent.py，应被跳过
    (agents_root / "shared").mkdir()
    (agents_root / "shared" / "__init__.py").write_text("", encoding="utf-8")

    runtime = AgentRuntime(plugins=[])
    registered = await load_agents(agents_root, runtime, model_factory=_fake_model)

    assert registered == ["hello"]
    assert [a.agent_id for a in runtime.list_agents()] == ["hello"]
