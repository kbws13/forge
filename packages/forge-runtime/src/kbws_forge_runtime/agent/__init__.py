"""Agent aggregation and directory discovery.

One agent = one directory under the agents root, exporting an ``agent``
object from its ``agent.py``. Prompts, tools, MCP config and skills live
alongside it in the same directory.
"""

from kbws_forge_runtime.agent.base import Agent
from kbws_forge_runtime.agent.loader import load_agents

__all__ = ["Agent", "load_agents"]
