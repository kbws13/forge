"""Render prompts (str | Prompt | langchain template) into concrete messages."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.prompts import BaseChatPromptTemplate

from kbws_forge_runtime.prompts.base import Prompt


def _format(template: str, prompt_name: str, variables: dict[str, Any]) -> str:
    try:
        return template.format(**variables)
    except KeyError as exc:
        raise ValueError(f"prompt {prompt_name!r} is missing variable {exc}") from exc
    except IndexError as exc:
        raise ValueError(f"prompt {prompt_name!r} has a stray placeholder: {exc}") from exc


def _render_messages(
    prompt: Prompt,
    variables: dict[str, Any],
    history: Sequence[BaseMessage],
) -> list[BaseMessage]:
    """Render a Prompt's messages, injecting history at ``history`` placeholders."""
    messages: list[BaseMessage] = []
    injected = False
    for message in prompt.messages:
        if message.role == "placeholder":
            if message.template != "history":
                raise ValueError(
                    f"prompt {prompt.name!r} has unknown placeholder {message.template!r}"
                )
            messages.extend(history)
            injected = True
            continue
        merged = {**message.partial, **variables}
        content = _format(message.template, prompt.name, merged)
        if message.role == "system":
            messages.append(SystemMessage(content=content))
        elif message.role == "human":
            messages.append(HumanMessage(content=content))
        else:
            messages.append(AIMessage(content=content))
    if history and not injected:
        messages.extend(history)
    return messages


def render_prompt(prompt: Prompt, variables: dict[str, Any]) -> list[BaseMessage]:
    """Render a Prompt without history injection (placeholders stay empty)."""
    return _render_messages(prompt, variables, history=[])


def render_instruction(
    instruction: str | Prompt | BaseChatPromptTemplate,
    *,
    history: Sequence[BaseMessage],
    outputs: dict[str, Any],
    variables: dict[str, Any] | None,
) -> list[BaseMessage]:
    """Build the full prompt message list for one model call.

    - ``str``: a system message with ``{outputs.*}`` substitution + history.
    - ``Prompt``: rendered blocks; a ``history`` placeholder is filled with
      the session history, otherwise history is appended at the end.
    - langchain template: rendered via the template, history appended.
    """
    merged = {**(outputs or {}), **(variables or {})}

    if isinstance(instruction, str):
        text = instruction
        for key, value in (outputs or {}).items():
            text = text.replace(f"{{{key}}}", str(value))
        messages: list[BaseMessage] = [SystemMessage(content=text)]
    elif isinstance(instruction, Prompt):
        return _render_messages(instruction, merged, history)
    else:
        messages = list(instruction.format_messages(**merged))

    messages.extend(history)
    return messages
