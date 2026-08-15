from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field


class UserSession(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
