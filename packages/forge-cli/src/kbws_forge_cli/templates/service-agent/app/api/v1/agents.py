"""Agent listing endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from kbws_forge_runtime import AgentRuntime

from app.api.deps import get_runtime
from app.core.response import ok
from app.core.security import require_api_key
from app.schemas.agent import AgentVO

router = APIRouter(tags=["agents"], dependencies=[Depends(require_api_key)])


@router.get("/agents")
async def list_agents(
    runtime: Annotated[AgentRuntime, Depends(get_runtime)],
) -> dict:
    agents = [AgentVO(**agent.model_dump()) for agent in runtime.list_agents()]
    return ok([agent.model_dump() for agent in agents]).model_dump()
