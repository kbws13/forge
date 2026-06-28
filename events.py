from dataclasses import dataclass

from messages import Message


@dataclass(frozen=True)
class TurnStarted:
    turn_id: str


@dataclass(frozen=True)
class MessageCreated:
    message: Message

@dataclass(frozen=True)
class AssistantDelta:
    text: str

@dataclass(frozen=True)
class TurnFinished:
    turn_id: str

@dataclass(frozen=True)
class TurnFailed:
    turn_id: str
    error: str

@dataclass(frozen=True)
class TurnCancelled:
    turn_id: str
    reason: str

@dataclass(frozen=True)
class ToolResultCreated:
    tool_use_id: str
    content: str

@dataclass(frozen=True)
class ToolFailed:
    tool_use_id: str
    error: str