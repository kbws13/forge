from __future__ import annotations

from kbws_forge_runtime._internal.agent_handle import AgentHandle
from kbws_forge_runtime.errors import AgentNotFoundError
from kbws_forge_runtime.models import AgentInfo


class AgentRegistry:
    """
    The startup registry for all runnable agents.
    """

    def __init__(self):
        self._agents: dict[str, AgentHandle] = {}

    def register(self, handle: AgentHandle) -> None:
        agent_id = handle.info.agent_id
        if agent_id in self._agents:
            raise ValueError(f"agent already registered: {agent_id}")
        self._agents[agent_id] = handle

    def get(self, agent_id: str) -> AgentHandle:
        try:
            return self._agents[agent_id]
        except KeyError as exc:
            raise AgentNotFoundError(f"agent does not exist: {agent_id}") from exc

    def list_agents(self) -> list[AgentInfo]:
        return [handle.info for handle in self._agents.values()]
