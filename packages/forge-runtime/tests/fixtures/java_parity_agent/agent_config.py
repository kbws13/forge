from pathlib import Path

from langchain_openai import ChatOpenAI

from kbws_forge_runtime import AgentInfo, AgentRuntime
from kbws_forge_runtime.plugins import LoggingPlugin
from kbws_forge_runtime.tools import SkillLoader, ToolBox

from .settings import Settings
from .tools import current_time
from .workflows import (
    build_assistant,
    build_code_pipeline,
    build_iterative_writer,
    build_research_pipeline,
)


def build_runtime(settings: Settings) -> AgentRuntime:
    model = ChatOpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        model=settings.deepseek_model,
        temperature=0,
    )

    skills = SkillLoader()
    skills.add_directory(Path(__file__).parent / "skills")
    tools = ToolBox([current_time, *skills.as_tool()])

    runtime = AgentRuntime(plugins=[LoggingPlugin()])
    runtime.register_agent(
        AgentInfo(
            agent_id="assistant",
            name="Assistant",
            description="Single chat agent with local tools and skills.",
        ),
        build_assistant(model, list(tools.tools)),
    )
    runtime.register_agent(
        AgentInfo(
            agent_id="code-pipeline",
            name="Code Pipeline",
            description="Write, review, and refactor in sequence.",
        ),
        build_code_pipeline(model),
    )
    runtime.register_agent(
        AgentInfo(
            agent_id="research-pipeline",
            name="Research Pipeline",
            description="Analyze in parallel, then merge the results.",
        ),
        build_research_pipeline(model),
    )
    runtime.register_agent(
        AgentInfo(
            agent_id="iterative-writer",
            name="Iterative Writer",
            description="Write a draft and refine it in a bounded loop.",
        ),
        build_iterative_writer(model),
    )
    return runtime
