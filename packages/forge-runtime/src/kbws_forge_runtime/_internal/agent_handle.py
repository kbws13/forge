from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kbws_forge_runtime.models import AgentInfo


@dataclass(frozen=True, slots=True)
class AgentHandle:
    info: AgentInfo
    graph: Any
