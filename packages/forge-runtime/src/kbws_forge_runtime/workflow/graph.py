"""Structural contract for agent graphs.

``AgentRuntime`` only relies on this minimal async interface, so any
langgraph-compiled graph (or a compatible custom graph) can be registered.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any, Protocol


class ChatGraph(Protocol):
    """Minimal async graph interface used by ``AgentRuntime``."""

    async def astream_events(
        self,
        input: dict[str, Any],
        config: dict[str, Any] | None = None,
        *,
        version: str,
    ) -> AsyncGenerator[dict[str, Any]]:
        """Stream graph events; an async generator in practice."""
        if False:  # pragma: no cover - 协议存根，仅用于声明 yield 类型
            yield {}

    async def aget_state(self, config: dict[str, Any]) -> Any:
        """Read the final graph state for a run."""
        ...  # pragma: no cover