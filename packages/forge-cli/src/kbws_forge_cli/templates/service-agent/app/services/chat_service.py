"""Chat orchestration: session + chat + SSE stream mapping, SDK error -> business code."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from kbws_forge_runtime import AgentRuntime
from kbws_forge_runtime.errors import ForgeRuntimeError

from app.core.enums import ErrorCode
from app.core.exceptions import AppException
from app.core.utils import sse_frame
from app.schemas.chat import ChatResponse

logger = logging.getLogger("demo.services.chat")

# SDK 字符串错误码 -> 业务数字码
_SDK_TO_BUSINESS: dict[str, int] = {
    "E0001": ErrorCode.NOT_FOUND,  # 智能体不存在
    "0002": ErrorCode.NOT_FOUND,  # 会话不存在
    "0003": ErrorCode.FORBIDDEN,  # 会话归属错误
    "0004": ErrorCode.PARAMS_ERROR,  # 非法参数
    "0005": ErrorCode.OPERATION_ERROR,
    "0006": ErrorCode.OPERATION_ERROR,
    "0007": ErrorCode.OPERATION_ERROR,  # run cancelled
    "0008": ErrorCode.OPERATION_ERROR,  # run timeout
    "0009": ErrorCode.OPERATION_ERROR,  # run budget exceeded
    "0010": ErrorCode.OPERATION_ERROR,  # tool not allowed
    "0011": ErrorCode.OPERATION_ERROR,  # tool approval required
    "0012": ErrorCode.OPERATION_ERROR,  # usage unavailable
}

# 业务码 -> HTTP 状态（业务码与 HTTP 语义对齐）
_HTTP_BY_CODE: dict[int, int] = {
    ErrorCode.PARAMS_ERROR: 400,
    ErrorCode.NOT_LOGIN: 401,
    ErrorCode.NO_AUTH: 403,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.NOT_FOUND: 404,
}


def _to_app_exception(exc: ForgeRuntimeError) -> AppException:
    code = _map_code(exc)
    return AppException(code, exc.message, http_status=_HTTP_BY_CODE.get(code, 400))


class ChatService:
    def __init__(self, runtime: AgentRuntime) -> None:
        self._runtime = runtime

    # --- session ---

    def create_session(self, agent_id: str, user_id: str):
        try:
            return self._runtime.create_session(agent_id, user_id)
        except ForgeRuntimeError as exc:
            raise _to_app_exception(exc) from exc

    # --- chat ---

    async def chat(
        self,
        agent_id: str,
        user_id: str,
        message: str,
        session_id: str | None,
        variables: dict | None = None,
    ) -> ChatResponse:
        try:
            result = await self._runtime.chat(
                agent_id, user_id, message, session_id=session_id, variables=variables
            )
        except ForgeRuntimeError as exc:
            raise _to_app_exception(exc) from exc
        return ChatResponse(
            run_id=result.run_id,
            agent_id=result.agent_id,
            session_id=result.session_id,
            content=result.content,
            parsed=result.parsed,
            duration_ms=result.duration_ms,
            model_calls=result.model_calls,
            tool_calls=result.tool_calls,
            usage=result.usage,
        )

    async def chat_stream(
        self,
        agent_id: str,
        user_id: str,
        message: str,
        session_id: str | None,
        variables: dict | None = None,
    ) -> AsyncIterator[str]:
        # 流式路径不抛异常：未知 agent / 会话错误以 run_failed 事件发出
        async for event in self._runtime.chat_stream(
            agent_id, user_id, message, session_id=session_id, variables=variables
        ):
            yield sse_frame(event.type, event)


def _map_code(exc: ForgeRuntimeError) -> int:
    return _SDK_TO_BUSINESS.get(exc.code, ErrorCode.OPERATION_ERROR)
