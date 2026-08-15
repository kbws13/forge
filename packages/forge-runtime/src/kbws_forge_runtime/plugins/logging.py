from __future__ import annotations

import logging

from kbws_forge_runtime.models import AgentInfo, ChatEvent, ChatRequest, ChatResult, UserSession
from kbws_forge_runtime.plugins.base import Plugin


class LoggingPlugin(Plugin):
    def __init__(self, log: logging.Logger | None = None) -> None:
        self._log = log or logging.getLogger("kbws_forge_runtime")

    async def on_error(self, agent: AgentInfo, error: Exception) -> None:
        self._log.error(
            "agent failed agent_id=%s error=%s",
            agent.agent_id,
            error,
        )

    async def after_agent(self, agent: AgentInfo, result: ChatResult) -> None:
        self._log.info(
            "agent finished agent_id=%s run_id=%s",
            agent.agent_id,
            result.run_id,
        )

    async def on_event(self, event: ChatEvent) -> None:
        self._log.debug(
            "chat event type=%s run_id=%s",
            event.type,
            event.run_id,
        )

    async def before_agent(self, agent: AgentInfo, session: UserSession) -> None:
        self._log.info(
            "agent started agent_id=%ssession_id=%s",
            agent.agent_id,
            session.session_id,
        )

    async def on_user_message(self, request: ChatRequest, session: UserSession) -> None:
        self._log.info(
            "chat received agent_id=%s user_id=%s session_id=%s",
            request.agent_id,
            request.user_id,
            session.session_id,
        )
