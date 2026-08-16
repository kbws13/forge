"""Agent directory discovery integration test."""

from __future__ import annotations

from kbws_forge_runtime import AgentRuntime
from kbws_forge_runtime.agent import load_agents
from tests.conftest import BindableFakeChatModel


async def test_load_agents_discovers_all_agents() -> None:
    runtime = AgentRuntime(plugins=[])

    registered = await load_agents(
        "agents", runtime, model_factory=lambda: BindableFakeChatModel(responses=["ok"])
    )

    # load_agents 按目录名注册（字母序），用集合断言避免顺序耦合
    assert set(registered) == {"{{ spec.module_name }}", "extract"}
    by_id = {a.agent_id: a for a in runtime.list_agents()}
    assert set(by_id) == {"{{ spec.module_name }}", "extract"}
    assert by_id["{{ spec.module_name }}"].name == "{{ spec.name }}"
