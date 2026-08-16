from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from kbws_forge_runtime.execution import ModelUsage
from kbws_forge_runtime.models.messages import ChatMessage


class ChatResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    agent_id: str
    user_id: str
    session_id: str
    message: ChatMessage
    parsed: Any | None = None
    duration_ms: float | None = None
    model_calls: int = 0
    tool_calls: int = 0
    usage: ModelUsage = ModelUsage()

    @property
    def content(self) -> str:
        return self.message.text
