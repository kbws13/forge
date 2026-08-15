from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AgentInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
