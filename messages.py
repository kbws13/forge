from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant", "system"]
    content: str
   