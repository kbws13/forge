from __future__ import annotations

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
