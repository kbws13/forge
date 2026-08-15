from pathlib import Path

import pytest
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from kbws_forge_runtime import (
    AgentInfo,
    AgentRuntime,
    RunFinished,
    ToolStarted,
)
from kbws_forge_runtime.tools import SkillLoader
from kbws_forge_runtime.workflow import build_chat_graph

pytestmark = pytest.mark.real_provider


async def test_real_provider_reads_skill_and_creates_plan(real_model: ChatOpenAI) -> None:
    skills = SkillLoader()
    skills.add_directory(
        Path(__file__).parents[1] / "fixtures" / "java_parity_agent" / "skills"
    )
    runtime = AgentRuntime(plugins=[])
    runtime.register_agent(
        AgentInfo(agent_id="planner", name="Planner"),
        build_chat_graph(
            real_model,
            instruction=(
                "You are a planning agent. You must first call list_skills, then call "
                "read_skill_file for the project-planning skill. Follow that skill to plan the "
                "user's task. The final answer must contain exactly three numbered steps and each "
                "step must include a verification action."
            ),
            tools=skills.as_tool(),
            checkpointer=InMemorySaver(),
        ),
    )

    events = [
        event
        async for event in runtime.chat_stream(
            "planner",
            "user-1",
            "Plan how to add a health endpoint to a FastAPI service.",
        )
    ]

    started_tools = [
        event.tool_name for event in events if isinstance(event, ToolStarted)
    ]
    assert started_tools == ["list_skills", "read_skill_file"]
    assert isinstance(events[-1], RunFinished)
    assert all(f"{number}." in events[-1].message.text for number in range(1, 4))
    assert "verif" in events[-1].message.text.lower()
