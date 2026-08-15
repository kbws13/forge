"""Session endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from kbws_forge_runtime import AgentRuntime

from app.api.deps import get_runtime
from app.core.response import ok
from app.core.security import require_api_key
from app.schemas.session import SessionCreateRequest, SessionVO
from app.services.chat_service import ChatService

router = APIRouter(tags=["sessions"], dependencies=[Depends(require_api_key)])


@router.post("/sessions")
async def create_session(
    req: SessionCreateRequest,
    runtime: Annotated[AgentRuntime, Depends(get_runtime)],
) -> dict:
    service = ChatService(runtime)
    session = service.create_session(req.agent_id, req.user_id)
    return ok(SessionVO(**session.model_dump()).model_dump()).model_dump()
