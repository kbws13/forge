"""ModelMiddleware protocol."""

from __future__ import annotations

from typing import Any, Protocol

from langchain_core.messages import BaseMessage

from kbws_forge_runtime.workflow.state import WorkflowState


class ModelMiddleware(Protocol):
    """Intercepts each model call inside a chat graph.

    ``state`` is the current graph state (a ``WorkflowState`` dict); it is
    read-only from the middleware's perspective.
    """

    name: str

    async def before_model(
        self, state: WorkflowState, messages: list[BaseMessage]
    ) -> list[BaseMessage] | None:
        """Called before the model call. Return new messages to replace the
        prompt, or None to keep it."""
        return None

    async def after_model(
        self, state: WorkflowState, response: BaseMessage
    ) -> BaseMessage | None:
        """Called after the model call. Return a replacement response, or None
        to keep the original."""
        return None

    async def wrap_model_call(
        self, messages: list[BaseMessage], handler: Any
    ) -> BaseMessage:
        """Fully wrap the model call: ``await handler(messages)`` invokes the
        next layer (a previous middleware or the actual model)."""
        return await handler(messages)
