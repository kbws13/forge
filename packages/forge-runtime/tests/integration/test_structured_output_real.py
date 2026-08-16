"""Real-provider evaluation of structured output (tool-calling path)."""

from __future__ import annotations

import pytest
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel, Field

from kbws_forge_runtime import AgentInfo, AgentRuntime
from kbws_forge_runtime.agent import Agent
from kbws_forge_runtime.middleware import AppendSystemContextMiddleware
from kbws_forge_runtime.models import RunFinished
from kbws_forge_runtime.tools import tool
from kbws_forge_runtime.workflow import build_chat_graph

pytestmark = pytest.mark.real_provider


class Scientist(BaseModel):
    """嵌套结构：列表 + 嵌套对象。"""

    name: str = Field(description="科学家的全名")
    birth_year: int = Field(description="出生年份")
    nationality: str = Field(description="国籍")
    fields: list[str] = Field(description="研究领域列表")
    achievements: list[str] = Field(description="主要成就")
    biography: str = Field(description="简短传记")


class Weather(BaseModel):
    city: str
    temperature: float


@tool
def add(a: float, b: float) -> float:
    """Add two numbers and return the sum."""
    return a + b


async def test_structured_output_parses_real_model_response(
    real_model: ChatOpenAI,
) -> None:
    """外部传入嵌套 pydantic schema，真实模型输出应被解析为正确对象。"""
    runtime = AgentRuntime(plugins=[])
    runtime.register_agent(
        AgentInfo(agent_id="sci", name="Sci"),
        build_chat_graph(
            real_model,
            instruction="根据用户问题提取信息，通过结构化输出工具返回。",
            output_schema=Scientist,
            checkpointer=InMemorySaver(),
        ),
    )
    result = await runtime.chat("sci", "u1", "介绍牛顿的生平和成就")

    assert result.parsed is not None, "parsed 应为解析后的对象"
    assert isinstance(result.parsed, Scientist)
    assert result.parsed.name  # 有值
    assert result.parsed.birth_year == 1643  # 数值字段解析正确
    assert result.parsed.fields  # 列表解析
    assert result.parsed.achievements  # 列表解析
    assert result.parsed.biography


async def test_structured_output_available_in_stream_events(
    real_model: ChatOpenAI,
) -> None:
    """流式路径：RunFinished 事件应携带 parsed。"""
    runtime = AgentRuntime(plugins=[])
    runtime.register_agent(
        AgentInfo(agent_id="sci", name="Sci"),
        build_chat_graph(
            real_model,
            instruction="根据用户问题提取信息，通过结构化输出工具返回。",
            output_schema=Weather,
            checkpointer=InMemorySaver(),
        ),
    )
    events = [
        event
        async for event in runtime.chat_stream("sci", "u1", "今天杭州天气如何？")
    ]
    finished = next(e for e in events if isinstance(e, RunFinished))
    assert finished.parsed is not None
    assert isinstance(finished.parsed, Weather)
    assert finished.parsed.city
    assert isinstance(finished.parsed.temperature, float)


async def test_structured_output_coexists_with_real_tools(
    real_model: ChatOpenAI,
) -> None:
    """真实工具与结构化输出共存：先算数，再结构化返回结果。"""
    runtime = AgentRuntime(plugins=[])
    runtime.register_agent(
        AgentInfo(agent_id="calc", name="Calc"),
        build_chat_graph(
            real_model,
            instruction=(
                "用户问两数相加时先调用 add 工具，最后通过结构化输出工具返回 "
                "result（计算结果）与 explanation（一句话解释）。"
            ),
            tools=[add],
            output_schema=Weather,  # 复用 Weather 的 city/temperature 字段做演示容器
            checkpointer=InMemorySaver(),
        ),
    )
    result = await runtime.chat("calc", "u1", "What is 15 + 27?")

    # 模型可能只输出结构化结果而不写文本；核心断言是结构化结果正确
    assert result.parsed is not None
    assert result.parsed.temperature == 42.0


async def test_agent_aggregation_with_middleware_and_output_schema(
    real_model_factory,
) -> None:
    """Agent 聚合类应支持 middleware + output_schema 组合。"""

    class Report(BaseModel):
        summary: str

    agent = Agent(
        agent_id="agg",
        name="Agg",
        prompt="根据用户问题给出摘要。",
        middleware=(AppendSystemContextMiddleware("所有回答必须通过结构化输出工具返回。"),),
        output_schema=Report,
    )
    graph = await agent.build_graph(real_model_factory)
    runtime = AgentRuntime(plugins=[])
    runtime.register_agent(AgentInfo(agent_id="agg", name="Agg"), graph)

    result = await runtime.chat("agg", "u1", "用一句话总结：AI 是什么？")
    assert result.parsed is not None
    assert isinstance(result.parsed, Report)
    assert result.parsed.summary
