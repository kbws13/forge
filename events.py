from dataclasses import dataclass

from messages import Message


@dataclass(frozen=True)
class TurnStarted:
    turn_id: str


@dataclass(frozen=True)
class MessageCreated:
    message: Message


@dataclass(frozen=True)
class TurnFinished:
    turn_id: str
