from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any
from uuid import uuid4

from kbws_forge_runtime._internal.agent_handle import AgentHandle
from kbws_forge_runtime._internal.graph_agent import GraphAgent
from kbws_forge_runtime._internal.registry import AgentRegistry
from kbws_forge_runtime._internal.sessions import SessionManager
from kbws_forge_runtime.errors import (
    ForgeRuntimeError,
    RunCancelledError,
    RunError,
)
from kbws_forge_runtime.execution import (
    RunContext,
    RunPolicy,
    ToolApprovalHandler,
    UsageResolver,
    bind_run_context,
    default_usage_resolver,
    reset_run_context,
)
from kbws_forge_runtime.models import (
    AgentInfo,
    ChatEvent,
    ChatMessage,
    ChatPart,
    ChatRequest,
    ChatResult,
    MessageCreated,
    RunCancelled,
    RunFailed,
    RunFinished,
    RunStarted,
    UserSession,
)
from kbws_forge_runtime.plugins import Plugin
from kbws_forge_runtime.sinks import EventSink
from kbws_forge_runtime.workflow.graph import ChatGraph

logger = logging.getLogger("kbws_forge_runtime")


class AgentRuntime:
    """
    Register agents, create Sessions, and run chat requests.
    """

    def __init__(
        self,
        *,
        plugins: Sequence[Plugin] = (),
        default_policy: RunPolicy | None = None,
        event_sinks: Sequence[EventSink] = (),
        tool_approval_handler: ToolApprovalHandler | None = None,
        usage_resolver: UsageResolver = default_usage_resolver,
    ) -> None:
        self._registry = AgentRegistry()
        self._sessions = SessionManager()
        self._plugins = tuple(plugins)
        self._default_policy = default_policy or RunPolicy()
        self._event_sinks = tuple(event_sinks)
        self._tool_approval_handler = tool_approval_handler
        self._usage_resolver = usage_resolver
        self._active_runs: dict[str, RunContext] = {}

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
        policy: RunPolicy | None = None,
    ) -> ChatResult:
        async for event in self.chat_stream(
            agent_id,
            user_id,
            messages,
            session_id,
            variables=variables,
            policy=policy,
        ):
            if isinstance(event, RunCancelled):
                raise RunError(event.reason, code=event.error_code)
            if isinstance(event, RunFailed):
                raise RunError(event.error_message, code=event.error_code)
            if isinstance(event, RunFinished):
                return ChatResult(
                    run_id=event.run_id,
                    agent_id=event.agent_id,
                    user_id=user_id,
                    session_id=event.session_id,
                    message=event.message,
                    parsed=event.parsed,
                    duration_ms=event.duration_ms,
                    model_calls=event.model_calls,
                    tool_calls=event.tool_calls,
                    usage=event.usage,
                )
        raise RunError("chat stream finished without a result")

    async def chat_parts(
        self,
        agent_id: str,
        user_id: str,
        parts: Sequence[ChatPart],
        session_id: str | None = None,
        variables: dict[str, Any] | None = None,
        policy: RunPolicy | None = None,
    ):
        message = ChatMessage(role="user", parts=tuple(parts))
        return await self.chat(
            agent_id,
            user_id,
            message,
            session_id,
            variables=variables,
            policy=policy,
        )

    async def chat_stream(
        self,
        agent_id: str,
        user_id: str,
        message: str | ChatMessage,
        session_id: str | None = None,
        variables: dict[str, Any] | None = None,
        policy: RunPolicy | None = None,
    ) -> AsyncIterator[ChatEvent]:
        request_message = ChatMessage.user(message) if isinstance(message, str) else message
        request = ChatRequest(
            agent_id=agent_id,
            user_id=user_id,
            message=request_message,
            session_id=session_id,
            variables=variables,
        )
        run_id = str(uuid4())
        current_session_id = session_id or ""
        handle: AgentHandle | None = None
        context: RunContext | None = None

        try:
            handle = self._registry.get(agent_id)
            if session_id is None:
                session = self._sessions.create(agent_id, user_id)
            else:
                session = self._sessions.get(session_id, agent_id=agent_id, user_id=user_id)
            current_session_id = session.session_id
            context = RunContext(
                run_id=run_id,
                agent_id=agent_id,
                user_id=user_id,
                session_id=session.session_id,
                policy=policy or self._default_policy,
                approval_handler=self._tool_approval_handler,
                usage_resolver=self._usage_resolver,
            )
            self._active_runs[run_id] = context

            started = RunStarted(
                run_id=run_id,
                agent_id=agent_id,
                session_id=session.session_id,
                sequence=context.next_sequence(),
                policy=context.policy.model_dump(mode="json"),
            )
            await self._notify_event(started)
            yield started

            input_event = MessageCreated(
                run_id=run_id,
                agent_id=agent_id,
                session_id=session.session_id,
                sequence=context.next_sequence(),
                message=request_message,
            )
            await self._notify_event(input_event)
            yield input_event

            for plugin in self._plugins:
                await plugin.on_user_message(request, session)
                await plugin.before_agent(handle.info, session)

            graph_agent: GraphAgent = handle.graph
            graph_stream = graph_agent.stream(
                request_message,
                run_id=run_id,
                session_id=session.session_id,
                variables=variables,
                run_context=context,
            ).__aiter__()

            async def next_graph_event():
                token = bind_run_context(context)
                try:
                    return await graph_stream.__anext__()
                finally:
                    reset_run_context(token)

            while True:
                try:
                    event = await context.await_controlled(next_graph_event)
                except StopAsyncIteration:
                    break
                # 终态副作用在发布事件之前完成，避免 after_agent 失败时同时
                # 产生 run_finished 和 run_failed 两个终态。
                if isinstance(event, RunFinished):
                    result = ChatResult(
                        run_id=run_id,
                        agent_id=agent_id,
                        user_id=user_id,
                        session_id=session.session_id,
                        message=event.message,
                        parsed=event.parsed,
                        duration_ms=event.duration_ms,
                        model_calls=event.model_calls,
                        tool_calls=event.tool_calls,
                        usage=event.usage,
                    )
                    for plugin in self._plugins:
                        await plugin.after_agent(handle.info, result)
                await self._notify_event(event)
                yield event
        except RunCancelledError as exc:
            cancelled = RunCancelled(
                run_id=run_id,
                agent_id=agent_id,
                session_id=current_session_id,
                sequence=context.next_sequence() if context is not None else 0,
                error_code=exc.code,
                reason=str(exc),
                duration_ms=context.elapsed_ms if context is not None else None,
                model_calls=context.model_calls if context is not None else 0,
                tool_calls=context.tool_calls if context is not None else 0,
                usage=context.usage if context is not None else {},
            )
            await self._notify_event(cancelled)
            yield cancelled
        except Exception as exc:
            if handle is not None:
                for plugin in self._plugins:
                    await plugin.on_error(handle.info, exc)
            runtime_error = _find_runtime_error(exc)
            code = runtime_error.code if runtime_error is not None else "0001"
            failed = RunFailed(
                run_id=run_id,
                agent_id=agent_id,
                session_id=current_session_id,
                sequence=context.next_sequence() if context is not None else 0,
                error_code=code,
                error_message=str(runtime_error or exc),
                duration_ms=context.elapsed_ms if context is not None else None,
                model_calls=context.model_calls if context is not None else 0,
                tool_calls=context.tool_calls if context is not None else 0,
                usage=context.usage if context is not None else {},
            )
            await self._notify_event(failed)
            yield failed
        finally:
            self._active_runs.pop(run_id, None)

    def cancel(self, run_id: str, reason: str = "run cancelled") -> bool:
        context = self._active_runs.get(run_id)
        if context is None:
            return False
        context.cancel(reason)
        return True

    def active_run_ids(self) -> tuple[str, ...]:
        return tuple(self._active_runs)

    async def _notify_event(self, event: ChatEvent) -> None:
        for sink in self._event_sinks:
            try:
                await sink.emit(event)
            except Exception:
                logger.exception(
                    "event sink failed sink=%s event_type=%s run_id=%s",
                    type(sink).__name__,
                    event.type,
                    event.run_id,
                )
        for plugin in self._plugins:
            await plugin.on_event(event)


def _find_runtime_error(error: BaseException) -> ForgeRuntimeError | None:
    if isinstance(error, ForgeRuntimeError):
        return error
    if isinstance(error, BaseExceptionGroup):
        for nested in error.exceptions:
            if found := _find_runtime_error(nested):
                return found
    if error.__cause__ is not None:
        if found := _find_runtime_error(error.__cause__):
            return found
    if error.__context__ is not None:
        return _find_runtime_error(error.__context__)
    return None
