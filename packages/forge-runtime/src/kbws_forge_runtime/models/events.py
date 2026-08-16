from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from kbws_forge_runtime.models.messages import ChatMessage


class EventBase(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    agent_id: str
    session_id: str


class RunStarted(EventBase):
    type: Literal["run_started"] = "run_started"


class MessageCreated(EventBase):
    type: Literal["message_created"] = "message_created"
    message: ChatMessage


class TextDelta(EventBase):
    type: Literal["text_delta"] = "text_delta"
    text: str
    node_name: str | None = None


class ToolStarted(EventBase):
    type: Literal["tool_started"] = "tool_started"
    tool_name: str
    tool_input: Any = None


class ToolFinished(EventBase):
    type: Literal["tool_finished"] = "tool_finished"
    tool_name: str
    tool_output: str


class RunFinished(EventBase):
    type: Literal["run_finished"] = "run_finished"
    message: ChatMessage
    parsed: Any | None = None


class RunFailed(EventBase):
    type: Literal["run_failed"] = "run_failed"
    error_code: str
    error_message: str


ChatEvent = Annotated[
    RunStarted | MessageCreated | TextDelta | ToolStarted | ToolFinished | RunFinished | RunFailed,
    Field(discriminator="type"),
]
