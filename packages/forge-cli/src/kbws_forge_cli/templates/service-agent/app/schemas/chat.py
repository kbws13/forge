from __future__ import annotations

from typing import Any

from kbws_forge_runtime import ModelUsage
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    agent_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    session_id: str | None = None
    variables: dict[str, str] | None = None


class ChatResponse(BaseModel):
    run_id: str
    agent_id: str
    session_id: str
    content: str
    parsed: Any | None = None
    duration_ms: float | None = None
    model_calls: int = 0
    tool_calls: int = 0
    usage: ModelUsage = ModelUsage()
