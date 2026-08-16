from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from kbws_forge_runtime.execution import ModelUsage
from kbws_forge_runtime.models.messages import ChatMessage


class EventBase(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    sequence: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    run_id: str
    agent_id: str
    session_id: str


class RunStarted(EventBase):
    type: Literal["run_started"] = "run_started"
    policy: dict[str, Any] = Field(default_factory=dict)


class MessageCreated(EventBase):
    type: Literal["message_created"] = "message_created"
    message: ChatMessage


class TextDelta(EventBase):
    type: Literal["text_delta"] = "text_delta"
    text: str
    node_name: str | None = None


class ModelStarted(EventBase):
    type: Literal["model_started"] = "model_started"
    call_id: str
    model_name: str | None = None
    node_name: str | None = None
    parent_ids: tuple[str, ...] = ()


class ModelFinished(EventBase):
    type: Literal["model_finished"] = "model_finished"
    call_id: str
    model_name: str | None = None
    node_name: str | None = None
    parent_ids: tuple[str, ...] = ()
    duration_ms: float | None = Field(default=None, ge=0)
    usage: ModelUsage | None = None
    tool_calls: tuple[dict[str, Any], ...] = ()


class ModelFailed(EventBase):
    type: Literal["model_failed"] = "model_failed"
    call_id: str
    model_name: str | None = None
    node_name: str | None = None
    parent_ids: tuple[str, ...] = ()
    duration_ms: float | None = Field(default=None, ge=0)
    error_message: str


class ToolStarted(EventBase):
    type: Literal["tool_started"] = "tool_started"
    tool_name: str
    tool_input: Any = None
    call_id: str | None = None
    node_name: str | None = None
    parent_ids: tuple[str, ...] = ()


class ToolFinished(EventBase):
    type: Literal["tool_finished"] = "tool_finished"
    tool_name: str
    tool_output: str
    call_id: str | None = None
    node_name: str | None = None
    parent_ids: tuple[str, ...] = ()
    duration_ms: float | None = Field(default=None, ge=0)


class ToolFailed(EventBase):
    type: Literal["tool_failed"] = "tool_failed"
    tool_name: str
    error_message: str
    call_id: str | None = None
    node_name: str | None = None
    parent_ids: tuple[str, ...] = ()
    duration_ms: float | None = Field(default=None, ge=0)


class RunFinished(EventBase):
    type: Literal["run_finished"] = "run_finished"
    message: ChatMessage
    parsed: Any | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    model_calls: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    usage: ModelUsage = Field(default_factory=ModelUsage)


class RunFailed(EventBase):
    type: Literal["run_failed"] = "run_failed"
    error_code: str
    error_message: str
    duration_ms: float | None = Field(default=None, ge=0)
    model_calls: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    usage: ModelUsage = Field(default_factory=ModelUsage)


class RunCancelled(EventBase):
    type: Literal["run_cancelled"] = "run_cancelled"
    error_code: str = "0007"
    reason: str = "run cancelled"
    duration_ms: float | None = Field(default=None, ge=0)
    model_calls: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    usage: ModelUsage = Field(default_factory=ModelUsage)


ChatEvent = Annotated[
    RunStarted
    | MessageCreated
    | TextDelta
    | ModelStarted
    | ModelFinished
    | ModelFailed
    | ToolStarted
    | ToolFinished
    | ToolFailed
    | RunFinished
    | RunFailed
    | RunCancelled,
    Field(discriminator="type"),
]
