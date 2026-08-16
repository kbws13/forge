"""Agent model: aggregates prompt, tools, MCP config and skills."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from kbws_forge_runtime.prompts import Prompt
from kbws_forge_runtime.tools import McpToolLoader, SkillLoader, ToolBox
from kbws_forge_runtime.tools.mcp import McpServer
from kbws_forge_runtime.workflow import build_chat_graph


class Agent(BaseModel):
    """One deployable agent: everything it needs lives in one place.

    ``prompt`` accepts a string, a composable ``Prompt``, or a langchain
    chat prompt template. ``model_factory`` (passed to :func:`load_agents`)
    supplies the LLM; ``checkpointer`` is shared from the host by default.
    """

    model_config = ConfigDict(frozen=True)

    agent_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    prompt: str | Prompt | Any
    tools: tuple[Any, ...] = ()
    mcp: tuple[McpServer, ...] = ()
    skills: tuple[str | Path, ...] = ()
    checkpointer: Any = None
    # 运行时对象（不参与 pydantic 校验）：模型级中间件
    middleware: tuple[Any, ...] = ()
    output_schema: type[BaseModel] | None = None

    async def build_graph(self, model_factory: Callable[[], Any]) -> Any:
        """Assemble the chat graph: local tools + MCP tools + skills."""
        model = model_factory()
        toolbox = ToolBox(self.tools)

        for server in self.mcp:
            loaded = await McpToolLoader([server]).load()
            toolbox.extend(loaded)

        if self.skills:
            skill_loader = SkillLoader()
            for path in self.skills:
                skill_loader.add_directory(path)
            toolbox.extend(skill_loader.as_tool())

        return build_chat_graph(
            model,
            instruction=self.prompt,
            tools=list(toolbox.tools),
            checkpointer=self.checkpointer,
            middleware=list(self.middleware),
            output_schema=self.output_schema,
        )
