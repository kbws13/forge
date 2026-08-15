from __future__ import annotations

from kbws_forge_runtime.models import (
    AgentInfo,
    ChatEvent,
    ChatRequest,
    ChatResult,
    UserSession,
)


class Plugin:
    async def on_user_message(self, request: ChatRequest, session: UserSession) -> None:
        pass

    async def before_agent(self, agent: AgentInfo, session: UserSession) -> None:
        pass

    async def on_event(self, event: ChatEvent) -> None:
        pass

    async def after_agent(self, agent: AgentInfo, result: ChatResult) -> None:
        pass

    async def on_error(self, agent: AgentInfo, error: Exception) -> None:
        pass
