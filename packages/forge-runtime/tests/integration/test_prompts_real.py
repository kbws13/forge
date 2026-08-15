"""Real-provider evaluation of the composable prompt + agent system."""

from __future__ import annotations

import pytest
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from kbws_forge_runtime import AgentInfo, AgentRuntime
from kbws_forge_runtime.agent import Agent
from kbws_forge_runtime.prompts import Message, Prompt, compose
from kbws_forge_runtime.tools import tool
from kbws_forge_runtime.workflow import build_chat_graph

pytestmark = pytest.mark.real_provider


@tool
def add(a: float, b: float) -> float:
    """Add two numbers and return the sum."""
    return a + b


async def test_composed_prompt_with_variables_real_provider(real_model: ChatOpenAI) -> None:
    """compose 多块组件 + variables 注入，真实模型遵守指令。"""
    persona = Prompt(name="persona", messages=[Message.system("你是一个{role}，风格{tone}。")])
    task = Prompt(
        name="task",
        messages=[
            Message.human(
                "评审数据：{data}\n如果数据包含 DRAFT 就回复 REVIEW_OK，否则 REVIEW_BAD。"
            )
        ],
    )
    prompt = compose(persona, task, name="real-composed")

    runtime = AgentRuntime(plugins=[])
    runtime.register_agent(
        AgentInfo(agent_id="composed", name="Composed"),
        build_chat_graph(real_model, instruction=prompt, checkpointer=InMemorySaver()),
    )
    result = await runtime.chat(
        "composed",
        "u1",
        "开始评审。",
        variables={"role": "评审员", "tone": "严格", "data": "DRAFT-v1"},
    )
    assert "REVIEW_OK" in result.content


async def test_placeholder_history_real_provider(real_model: ChatOpenAI) -> None:
    """messages-placeholder 语义：历史由 SDK 注入，多轮对话有记忆。"""
    prompt = Prompt(
        name="memory",
        messages=[
            Message.system("记住用户告诉你的代码。被问到时只回复该代码，不要其他内容。"),
            Message.history(),
        ],
    )
    runtime = AgentRuntime(plugins=[])
    runtime.register_agent(
        AgentInfo(agent_id="mem", name="Mem"),
        build_chat_graph(real_model, instruction=prompt, checkpointer=InMemorySaver()),
    )

    await runtime.chat("mem", "u1", "记住代码 KBWS_PROMPT_88。")
    second = await runtime.chat("mem", "u1", "我让你记的代码是什么？只回复该代码。")
    assert "KBWS_PROMPT_88" in second.content


async def test_agent_with_tools_real_provider(real_model_factory) -> None:
    """Agent 聚合（prompt 组件 + 工具）端到端真实调用。"""
    agent = Agent(
        agent_id="calc",
        name="Calc",
        prompt=Prompt(
            name="calc",
            messages=[
                Message.system("需要时使用 add 工具。用户问两个数相加时，只回复数字结果。"),
            ],
        ),
        tools=(add,),
    )
    graph = await agent.build_graph(real_model_factory)
    runtime = AgentRuntime(plugins=[])
    runtime.register_agent(AgentInfo(agent_id="calc", name="Calc"), graph)

    result = await runtime.chat("calc", "u1", "What is 12 + 30? Reply with only the number.")
    assert "42" in result.content
