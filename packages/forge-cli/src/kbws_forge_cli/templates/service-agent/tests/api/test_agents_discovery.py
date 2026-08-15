"""Agent directory discovery integration test."""

from __future__ import annotations

from kbws_forge_runtime import AgentRuntime
from kbws_forge_runtime.agent import load_agents
from tests.conftest import BindableFakeChatModel


async def test_load_agents_discovers_demo_assistant() -> None:
    runtime = AgentRuntime(plugins=[])

    registered = await load_agents(
        "agents", runtime, model_factory=lambda: BindableFakeChatModel(responses=["ok"])
    )

    assert registered == ["{{ spec.module_name }}"]
    agents = runtime.list_agents()
    assert [a.agent_id for a in agents] == ["{{ spec.module_name }}"]
    assert agents[0].name == "{{ spec.name }}"
