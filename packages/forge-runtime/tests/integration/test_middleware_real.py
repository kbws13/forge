"""Real-provider evaluation of model middlewares (deepagents-style)."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from kbws_forge_runtime import AgentInfo, AgentRuntime
from kbws_forge_runtime.middleware import AppendSystemContextMiddleware, CallCountMiddleware
from kbws_forge_runtime.tools import tool
from kbws_forge_runtime.workflow import build_chat_graph

pytestmark = pytest.mark.real_provider


@tool
def add(a: float, b: float) -> float:
    """Add two numbers and return the sum."""
    return a + b


async def test_append_system_context_changes_real_output(real_model: ChatOpenAI) -> None:
    """before_model 注入的指令应真实改变模型行为（对照组实验）。"""
    base_prompt = "回答：1+1 等于几？"

    plain = AgentRuntime(plugins=[])
    plain.register_agent(
        AgentInfo(agent_id="plain", name="Plain"),
        build_chat_graph(
            real_model, instruction=base_prompt, checkpointer=InMemorySaver()
        ),
    )
    result_plain = await plain.chat("plain", "u1", "run")

    with_context = AgentRuntime(plugins=[])
    with_context.register_agent(
        AgentInfo(agent_id="ctx", name="Ctx"),
        build_chat_graph(
            real_model,
            instruction=base_prompt,
            middleware=[AppendSystemContextMiddleware("所有回答必须只输出数字，禁止任何其他文字。")],
            checkpointer=InMemorySaver(),
        ),
    )
    result_ctx = await with_context.chat("ctx", "u1", "run")

    # 中间件注入后输出应更短（只输出数字）
    assert len(result_ctx.content.strip()) < len(result_plain.content.strip())


async def test_call_count_middleware_counts_tool_loop(real_model: ChatOpenAI) -> None:
    """工具循环场景下，每次模型调用都应被计数。"""
    counter = CallCountMiddleware()
    runtime = AgentRuntime(plugins=[])
    runtime.register_agent(
        AgentInfo(agent_id="calc", name="Calc"),
        build_chat_graph(
            real_model,
            instruction=(
                "用户问两数相加时先调用 add 工具，再基于工具结果只回复数字。"
            ),
            tools=[add],
            middleware=[counter],
            checkpointer=InMemorySaver(),
        ),
    )
    result = await runtime.chat("calc", "u1", "12 + 30 = ?")
    assert "42" in result.content
    # 至少两次模型调用（一次工具调用 + 一次总结）
    assert counter.count >= 2


async def test_custom_wrap_model_call_wraps_real_invocations(real_model: ChatOpenAI) -> None:
    """自定义 wrap_model_call 应包裹每一次真实模型调用。"""

    class WrappingMiddleware:
        name = "wrapping"

        def __init__(self) -> None:
            self.calls: list[int] = []

        async def before_model(
            self, state: Any, messages: list[BaseMessage]
        ) -> None:
            return None

        async def after_model(
            self, state: Any, response: BaseMessage
        ) -> None:
            return None

        async def wrap_model_call(
            self, messages: list[BaseMessage], handler: Any
        ) -> BaseMessage:
            self.calls.append(len(messages))
            return await handler(messages)

    wrapper = WrappingMiddleware()
    runtime = AgentRuntime(plugins=[])
    runtime.register_agent(
        AgentInfo(agent_id="w", name="W"),
        build_chat_graph(
            real_model,
            instruction="只回复 OK 两字。",
            middleware=[wrapper],
            checkpointer=InMemorySaver(),
        ),
    )
    result = await runtime.chat("w", "u1", "run")
    assert result.content  # 有回复内容（模型措辞不可控，不限定具体词）
    assert wrapper.calls, "wrap_model_call 没有被调用"
