from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from kbws_forge_runtime.models.messages import ChatMessage


class ChatRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    message: ChatMessage
    session_id: str | None = None
    variables: dict[str, Any] | None = None

    @model_validator(mode="after")
    def required_user_message(self) -> ChatRequest:
        if self.message.role != "user":
            raise ValueError("chat request message role must be 'user'")
        return self

    @classmethod
    def text(
        cls, agent_id: str, user_id: str, text: str, session_id: str | None = None
    ) -> ChatRequest:
        return cls(
            agent_id=agent_id,
            user_id=user_id,
            message=ChatMessage.user(text),
            session_id=session_id,
        )
