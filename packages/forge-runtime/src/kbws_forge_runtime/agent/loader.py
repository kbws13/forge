"""Discover agents from a directory tree (convention over configuration)."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from kbws_forge_runtime.agent.base import Agent
from kbws_forge_runtime.models import AgentInfo
from kbws_forge_runtime.runtime import AgentRuntime

# 目录约定：agents/<agent_id>/agent.py 导出名为 `agent` 的 Agent 对象。
# 没有 agent.py 的子目录（如 shared/）是共享层，不会被加载。
_ENTRY_FILE = "agent.py"
_ENTRY_ATTR = "agent"


def _load_module(agents_root: Path, agent_dir: Path) -> Any:
    if str(agents_root.parent) not in sys.path:
        sys.path.insert(0, str(agents_root.parent))
    module_name = f"{agents_root.name}.{agent_dir.name}.agent"
    return importlib.import_module(module_name)


async def load_agents(
    agents_dir: str | Path,
    runtime: AgentRuntime,
    model_factory: Callable[[], Any] | None = None,
) -> list[str]:
    """Scan ``agents_dir`` and register every agent directory.

    Each agent directory must contain ``agent.py`` exporting an ``agent``
    object (an :class:`Agent`). Returns the registered agent ids.
    """
    root = Path(agents_dir).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"agents directory does not exist: {root}")

    if model_factory is None:

        def _missing_factory() -> Any:  # type: ignore[misc]
            raise RuntimeError(
                "load_agents requires a model_factory that builds the shared LLM"
            )

        model_factory = _missing_factory

    registered: list[str] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        entry = child / _ENTRY_FILE
        if not entry.is_file():
            continue  # shared 层等：没有 agent.py 的目录跳过

        module = _load_module(root, child)
        agent: Agent | None = getattr(module, _ENTRY_ATTR, None)
        if agent is None:
            raise ValueError(f"{entry} must export an `agent` object")

        graph = await agent.build_graph(model_factory)
        runtime.register_agent(
            AgentInfo(
                agent_id=agent.agent_id,
                name=agent.name,
                description=agent.description,
            ),
            graph,
        )
        registered.append(agent.agent_id)
    return registered
