from __future__ import annotations

from collections.abc import Iterable

from langchain_core.tools import BaseTool, tool


class ToolBox:
    def __init__(self, tools: Iterable[BaseTool] = ()):
        self._tools: list[BaseTool] = []
        self.extend(tools)

    def add(self, item: BaseTool) -> None:
        if any(existing.name == item.name for existing in self._tools):
            raise ValueError(f"tool already exists: {item.name}")
        self._tools.append(item)

    def extend(self, items: Iterable[BaseTool]) -> None:
        for item in items:
            self.add(item)

    @property
    def tools(self) -> tuple[BaseTool, ...]:
        return tuple(self._tools)


__all__ = ["BaseTool", "ToolBox", "tool"]
