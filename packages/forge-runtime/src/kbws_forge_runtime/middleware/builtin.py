"""Built-in model middlewares (reference implementations)."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import BaseMessage, SystemMessage

from kbws_forge_runtime.workflow.state import WorkflowState

logger = logging.getLogger("kbws_forge_runtime.middleware")


class CallCountMiddleware:
    """Counts model calls; read ``count`` from the instance afterwards."""

    name = "call_count"

    def __init__(self) -> None:
        self.count = 0

    async def before_model(self, state: WorkflowState, messages: list[BaseMessage]) -> None:
        return None

    async def after_model(self, state: WorkflowState, response: BaseMessage) -> None:
        self.count += 1
        return None

    async def wrap_model_call(self, messages: list[BaseMessage], handler: Any) -> BaseMessage:
        return await handler(messages)


class AppendSystemContextMiddleware:
    """Appends a fixed system message before every model call."""

    name = "append_system_context"

    def __init__(self, text: str) -> None:
        self._text = text

    async def before_model(
        self, state: WorkflowState, messages: list[BaseMessage]
    ) -> list[BaseMessage]:
        return [*messages, SystemMessage(content=self._text)]

    async def after_model(self, state: WorkflowState, response: BaseMessage) -> None:
        return None

    async def wrap_model_call(self, messages: list[BaseMessage], handler: Any) -> BaseMessage:
        return await handler(messages)


class LoggingMiddleware:
    """Logs every model call and its response preview."""

    name = "logging"

    def __init__(self, log: logging.Logger | None = None, preview: int = 120) -> None:
        self._log = log or logger
        self._preview = preview

    async def before_model(
        self, state: WorkflowState, messages: list[BaseMessage]
    ) -> None:
        self._log.info("model call messages=%d", len(messages))
        return None

    async def after_model(self, state: WorkflowState, response: BaseMessage) -> None:
        text = getattr(response, "content", "")
        self._log.info("model response preview=%s", str(text)[: self._preview])
        return None

    async def wrap_model_call(self, messages: list[BaseMessage], handler: Any) -> BaseMessage:
        return await handler(messages)
