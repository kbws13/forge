from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Any
from uuid import uuid4

from kbws_forge_runtime._internal.agent_handle import AgentHandle
from kbws_forge_runtime._internal.graph_agent import GraphAgent
from kbws_forge_runtime._internal.registry import AgentRegistry
from kbws_forge_runtime._internal.sessions import SessionManager
from kbws_forge_runtime.errors import ForgeRuntimeError, RunError
from kbws_forge_runtime.models import (
    AgentInfo,
    ChatEvent,
    ChatMessage,
    ChatPart,
    ChatRequest,
    ChatResult,
    MessageCreated,
    RunFailed,
    RunFinished,
    RunStarted,
    UserSession,
)
from kbws_forge_runtime.plugins import Plugin
from kbws_forge_runtime.workflow.graph import ChatGraph


class AgentRuntime:
    """
    Register agents, create Sessions, and run chat requests.
    """

    def __init__(self, *, plugins: Sequence[Plugin] = ()) -> None:
        self._registry = AgentRegistry()
        self._sessions = SessionManager()
        self._plugins = tuple(plugins)

    def register_agent(self, info: AgentInfo, graph: ChatGraph) -> None:
        agent = GraphAgent(info=info, graph=graph)
        self._registry.register(AgentHandle(info=info, graph=agent))

    def list_agents(self) -> list[AgentInfo]:
        return self._registry.list_agents()

    def create_session(self, agent_id: str, user_id: str) -> UserSession:
        self._registry.get(agent_id)
        return self._sessions.create(agent_id, user_id)

    def get_session(self, session_id: str) -> UserSession:
        return self._sessions.find(session_id)

    async def chat(
        self,
        agent_id: str,
        user_id: str,
        messages: str | ChatMessage,
        session_id: str | None = None,
        variables: dict[str, Any] | None = None,
    ) -> ChatResult:
        async for event in self.chat_stream(
            agent_id, user_id, messages, session_id, variables=variables
        ):
            if isinstance(event, RunFailed):
                raise RunError(event.error_message, code=event.error_code)
            if isinstance(event, RunFinished):
                return ChatResult(
                    run_id=event.run_id,
                    agent_id=event.agent_id,
                    user_id=user_id,
                    session_id=event.session_id,
                    message=event.message,
                )
        raise RunError("chat stream finished without a result")

    async def chat_parts(
        self,
        agent_id: str,
        user_id: str,
        parts: Sequence[ChatPart],
        session_id: str | None = None,
        variables: dict[str, Any] | None = None,
    ):
        message = ChatMessage(role="user", parts=tuple(parts))
        return await self.chat(agent_id, user_id, message, session_id, variables=variables)

    async def chat_stream(
        self,
        agent_id: str,
        user_id: str,
        message: str | ChatMessage,
        session_id: str | None = None,
        variables: dict[str, Any] | None = None,
    ) -> AsyncIterator[ChatEvent]:
        request_message = ChatMessage.user(message) if isinstance(message, str) else message
        request = ChatRequest(
            agent_id=agent_id,
            user_id=user_id,
            message=request_message,
            session_id=session_id,
        )
        run_id = str(uuid4())
        current_session_id = session_id or ""
        handle: AgentHandle | None = None

        try:
            handle = self._registry.get(agent_id)
            if session_id is None:
                session = self._sessions.create(agent_id, user_id)
            else:
                session = self._sessions.get(session_id, agent_id=agent_id, user_id=user_id)
            current_session_id = session.session_id

            started = RunStarted(
                run_id=run_id,
                agent_id=agent_id,
                session_id=session.session_id,
            )
            await self._notify_event(started)
            yield started

            input_event = MessageCreated(
                run_id=run_id,
                agent_id=agent_id,
                session_id=session.session_id,
                message=request_message,
            )
            await self._notify_event(input_event)
            yield input_event

            for plugin in self._plugins:
                await plugin.on_user_message(request, session)
                await plugin.before_agent(handle.info, session)

            final_message: ChatMessage | None = None
            graph_agent: GraphAgent = handle.graph
            async for event in graph_agent.stream(
                request_message,
                run_id=run_id,
                session_id=session.session_id,
                variables=variables,
            ):
                if isinstance(event, MessageCreated) and event.message.role == "assistant":
                    final_message = event.message
                await self._notify_event(event)
                yield event

            if final_message is None:
                raise RunError("agent finished without an assistant message")

            result = ChatResult(
                run_id=run_id,
                agent_id=agent_id,
                user_id=user_id,
                session_id=session.session_id,
                message=final_message,
            )
            for plugin in self._plugins:
                await plugin.after_agent(handle.info, result)

            finished = RunFinished(
                run_id=run_id,
                agent_id=agent_id,
                session_id=session.session_id,
                message=final_message,
            )
            await self._notify_event(finished)
            yield finished
        except Exception as exc:
            if handle is not None:
                for plugin in self._plugins:
                    await plugin.on_error(handle.info, exc)
            code = exc.code if isinstance(exc, ForgeRuntimeError) else "0001"
            failed = RunFailed(
                run_id=run_id,
                agent_id=agent_id,
                session_id=current_session_id,
                error_code=code,
                error_message=str(exc),
            )
            await self._notify_event(failed)
            yield failed

    async def _notify_event(self, event: ChatEvent) -> None:
        for plugin in self._plugins:
            await plugin.on_event(event)
