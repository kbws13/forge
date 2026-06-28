from dataclasses import dataclass, field
from typing import Literal
from uuid import uuid4


# Message 是对话事实，后续会进入 transcript，所以设为不可变
@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant", "system"]
    content: str
    id: str = field(default_factory=lambda: str(uuid4()))
