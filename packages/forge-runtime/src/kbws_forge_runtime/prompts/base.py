"""Prompt component models: ``Message`` and ``Prompt``."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from langchain_core.messages import BaseMessage
from pydantic import BaseModel, ConfigDict, Field


class Message(BaseModel):
    """One templated message inside a Prompt.

    ``template`` supports ``{var}`` placeholders filled from call variables,
    workflow outputs, or ``partial`` values. A ``placeholder`` role declares
    an injection point for session history (template name ``history``).
    """

    model_config = ConfigDict(frozen=True)

    role: Literal["system", "human", "assistant", "placeholder"]
    template: str = Field(min_length=1)
    partial: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def system(cls, template: str, **partial: str) -> Message:
        return cls(role="system", template=template, partial=partial)

    @classmethod
    def human(cls, template: str, **partial: str) -> Message:
        return cls(role="human", template=template, partial=partial)

    @classmethod
    def assistant(cls, template: str, **partial: str) -> Message:
        return cls(role="assistant", template=template, partial=partial)

    @classmethod
    def history(cls) -> Message:
        """Declare where session history is injected into the prompt."""
        return cls(role="placeholder", template="history")


class Prompt(BaseModel):
    """An ordered collection of messages, optionally composed from smaller prompts."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    messages: tuple[Message, ...] = Field(min_length=1)

    def partial(self, **values: str) -> Prompt:
        """Return a new Prompt with values pre-filled into every message."""
        messages = tuple(
            message.model_copy(update={"partial": {**message.partial, **values}})
            for message in self.messages
        )
        return Prompt(name=self.name, messages=messages)

    def render(self, variables: dict[str, Any] | None = None) -> list[BaseMessage]:
        """Render messages (no history injection)."""
        from kbws_forge_runtime.prompts.render import render_prompt

        return render_prompt(self, variables=variables or {})


def compose(
    *prompts: Prompt,
    name: str | None = None,
    extra_messages: Sequence[Message] = (),
) -> Prompt:
    """Concatenate prompt components into one Prompt.

    ``extra_messages`` appends trailing messages (e.g. a history placeholder).
    """
    if not prompts:
        raise ValueError("compose needs at least one prompt")
    messages = tuple(message for prompt in prompts for message in prompt.messages)
    messages = messages + tuple(extra_messages)
    return Prompt(name=name or "+".join(prompt.name for prompt in prompts), messages=messages)
