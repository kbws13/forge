from __future__ import annotations

from pydantic import BaseModel


class AgentVO(BaseModel):
    agent_id: str
    name: str
    description: str = ""
