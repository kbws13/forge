"""Chat endpoints: blocking + SSE streaming."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from kbws_forge_runtime import AgentRuntime

from app.api.deps import get_runtime
from app.core.constants import SSE_MEDIA_TYPE
from app.core.response import ok
from app.core.security import require_api_key
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_service import ChatService

router = APIRouter(tags=["chat"], dependencies=[Depends(require_api_key)])


@router.post("/chat")
async def chat(
    req: ChatRequest,
    runtime: Annotated[AgentRuntime, Depends(get_runtime)],
) -> dict:
    service = ChatService(runtime)
    result: ChatResponse = await service.chat(
        req.agent_id,
        req.user_id,
        req.message,
        session_id=req.session_id,
        variables=req.variables,
    )
    return ok(result.model_dump()).model_dump()


@router.post("/chat_stream")
async def chat_stream(
    req: ChatRequest,
    runtime: Annotated[AgentRuntime, Depends(get_runtime)],
) -> StreamingResponse:
    service = ChatService(runtime)
    stream = service.chat_stream(
        req.agent_id,
        req.user_id,
        req.message,
        session_id=req.session_id,
        variables=req.variables,
    )
    return StreamingResponse(stream, media_type=SSE_MEDIA_TYPE)
