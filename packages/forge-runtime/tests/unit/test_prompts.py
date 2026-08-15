"""Unit tests for the composable prompt system."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate

from kbws_forge_runtime.prompts import Message, Prompt, compose, render_instruction


def test_message_factories() -> None:
    assert Message.system("be {tone}").role == "system"
    assert Message.human("hi").role == "human"
    assert Message.assistant("hi").role == "assistant"
    assert Message.history().role == "placeholder"


def test_prompt_render_substitutes_variables() -> None:
    prompt = Prompt(
        name="t",
        messages=[Message.system("你是{tone}的助手"), Message.human("数据：{data}")],
    )
    rendered = prompt.render({"tone": "专业", "data": "x"})
    assert isinstance(rendered[0], SystemMessage)
    assert rendered[0].content == "你是专业的助手"
    assert isinstance(rendered[1], HumanMessage)
    assert rendered[1].content == "数据：x"


def test_prompt_render_missing_variable_raises() -> None:
    prompt = Prompt(name="t", messages=[Message.system("需要 {missing} 变量")])
    with pytest.raises(ValueError, match="missing variable"):
        prompt.render({})


def test_compose_concatenates_blocks_and_extra_messages() -> None:
    persona = Prompt(name="persona", messages=[Message.system("你是{tone}的负责人")])
    task = Prompt(name="task", messages=[Message.human("本周数据：{data}")])
    combined = compose(persona, task, name="weekly", extra_messages=[Message.history()])
    assert combined.name == "weekly"
    assert [m.role for m in combined.messages] == ["system", "human", "placeholder"]


def test_partial_prefills_variables() -> None:
    prompt = Prompt(name="t", messages=[Message.system("公司：{company}，风格：{tone}")])
    bound = prompt.partial(company="星航科技")
    rendered = bound.render({"tone": "专业"})
    assert "公司：星航科技，风格：专业" in rendered[0].content


def test_render_instruction_str_path_appends_history() -> None:
    history = [HumanMessage(content="hi"), AIMessage(content="hello")]
    messages = render_instruction("你是助手", history=history, outputs={}, variables=None)
    assert messages[0].content == "你是助手"
    assert messages[1:] == history


def test_render_instruction_str_path_substitutes_outputs() -> None:
    messages = render_instruction(
        "草稿：{draft}", history=[], outputs={"draft": "D1"}, variables=None
    )
    assert messages[0].content == "草稿：D1"


def test_render_instruction_prompt_injects_history_at_placeholder() -> None:
    prompt = Prompt(
        name="t",
        messages=[Message.system("你是助手"), Message.history(), Message.human("问：{q}")],
    )
    history = [HumanMessage(content="old")]
    messages = render_instruction(prompt, history=history, outputs={}, variables={"q": "now"})
    assert [type(m) for m in messages] == [SystemMessage, HumanMessage, HumanMessage]
    assert messages[1] is history[0]  # 历史注入到 placeholder 位置
    assert messages[2].content == "问：now"


def test_render_instruction_prompt_appends_history_without_placeholder() -> None:
    prompt = Prompt(name="t", messages=[Message.system("你是助手")])
    history = [HumanMessage(content="old")]
    messages = render_instruction(prompt, history=history, outputs={}, variables=None)
    assert messages[0].content == "你是助手"
    assert messages[1] is history[0]


def test_render_instruction_langchain_template() -> None:
    template = ChatPromptTemplate.from_messages(
        [("system", "你是{role}"), ("human", "用户说：{msg}")]
    )
    history = [AIMessage(content="prev")]
    messages = render_instruction(
        template, history=history, outputs={}, variables={"role": "助手", "msg": "hi"}
    )
    assert messages[0].content == "你是助手"
    assert messages[1].content == "用户说：hi"
    assert messages[2] is history[0]
