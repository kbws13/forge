from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SessionCreateRequest(BaseModel):
    agent_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)


class SessionVO(BaseModel):
    session_id: str
    agent_id: str
    user_id: str
    created_at: datetime
