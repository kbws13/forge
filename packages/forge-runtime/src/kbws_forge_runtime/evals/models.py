"""Eval data models: cases, suites, graders, results.

Definitions (``EvalCase`` / ``EvalSuite`` / graders) are code objects and stay
in memory; results (``GraderResult`` / ``EvalCaseResult`` / ``EvalRun``) are
pydantic models so they serialize to the EvalStore and the trace UI.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from kbws_forge_runtime.execution import RunPolicy
from kbws_forge_runtime.models import ChatMessage, ChatResult


class EvalStatus(StrEnum):
    """Three-state grading status (ADK semantics: a failed grader is
    ``NOT_EVALUATED``, not ``FAILED`` — infrastructure failures must not be
    mistaken for quality failures)."""

    NOT_EVALUATED = "not_evaluated"
    PASSED = "passed"
    FAILED = "failed"


class GraderResult(BaseModel):
    """One metric's verdict, shaped like LangSmith feedback (key/score/comment)."""

    model_config = ConfigDict(frozen=True)

    key: str
    status: EvalStatus = EvalStatus.NOT_EVALUATED
    score: float | None = Field(default=None, ge=0, le=1)
    reason: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)


class Grader(Protocol):
    """A scoring function. ``events`` is the run's recorded trace events (as
    JSON dicts from the TraceStore), used by trajectory-style graders."""

    key: str

    async def grade(
        self,
        case: EvalCase,
        result: ChatResult,
        events: Sequence[dict[str, Any]],
    ) -> GraderResult: ...


@dataclasses.dataclass(frozen=True)
class EvalCase:
    """One evaluation item: a single input or a multi-turn conversation."""

    id: str
    input: str | ChatMessage | None = None
    conversation: tuple[ChatMessage, ...] | None = None
    expected: Any = None
    graders: tuple[Grader, ...] = ()
    variables: dict[str, Any] | None = None
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        if (self.input is None) == (self.conversation is None):
            raise ValueError("EvalCase requires exactly one of `input` or `conversation`")
        if self.conversation is not None and not self.conversation:
            raise ValueError("EvalCase conversation must not be empty")


@dataclasses.dataclass(frozen=True)
class EvalSuite:
    """A set of cases evaluated against one agent, with shared graders/policy."""

    id: str
    agent_id: str
    name: str = ""
    description: str = ""
    cases: tuple[EvalCase, ...] = ()
    graders: tuple[Grader, ...] = ()
    policy: RunPolicy | None = None
    repetitions: int = 1
    user_id: str = "eval_user"
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.repetitions < 1:
            raise ValueError("EvalSuite.repetitions must be >= 1")
        if not self.cases:
            raise ValueError(f"EvalSuite {self.id!r} has no cases")


class GraderCaseResult(BaseModel):
    """One grader's aggregated result across a case's repetitions."""

    model_config = ConfigDict(frozen=True)

    key: str
    status: EvalStatus = EvalStatus.NOT_EVALUATED
    score: float | None = None
    reason: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)


class EvalCaseResult(BaseModel):
    """One case's outcome: run ids, per-grader scores, failure reasons."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    run_ids: tuple[str, ...] = ()
    status: EvalStatus = EvalStatus.NOT_EVALUATED
    score: float | None = None
    graders: tuple[GraderCaseResult, ...] = ()
    failure_reasons: tuple[str, ...] = ()
    duration_ms: float | None = None
    error: str | None = None


class EvalRun(BaseModel):
    """One execution of a suite: provenance + per-case results."""

    model_config = ConfigDict(frozen=True)

    eval_run_id: str = Field(default_factory=lambda: str(uuid4()))
    suite_id: str
    agent_id: str
    status: str = "running"  # running | finished | failed
    started_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    completed_at: str | None = None
    repetitions: int = 1
    provenance: dict[str, Any] = Field(default_factory=dict)
    cases: tuple[EvalCaseResult, ...] = ()
    error: str | None = None

    @property
    def totals(self) -> dict[str, int]:
        counted = [case for case in self.cases if case.status != EvalStatus.NOT_EVALUATED]
        return {
            "total": len(self.cases),
            "passed": sum(1 for case in self.cases if case.status == EvalStatus.PASSED),
            "failed": sum(1 for case in self.cases if case.status == EvalStatus.FAILED),
            "not_evaluated": sum(
                1 for case in self.cases if case.status == EvalStatus.NOT_EVALUATED
            ),
            "evaluated": len(counted),
        }

    @property
    def average_score(self) -> float | None:
        scored = [
            case.score for case in self.cases if case.score is not None
        ]
        return sum(scored) / len(scored) if scored else None


def worst_status(statuses: Sequence[EvalStatus]) -> EvalStatus:
    """FAILED > NOT_EVALUATED > PASSED (conservative aggregation)."""
    if any(status == EvalStatus.FAILED for status in statuses):
        return EvalStatus.FAILED
    if any(status == EvalStatus.NOT_EVALUATED for status in statuses):
        return EvalStatus.NOT_EVALUATED
    return EvalStatus.PASSED


__all__ = [
    "EvalCase",
    "EvalCaseResult",
    "EvalRun",
    "EvalStatus",
    "EvalSuite",
    "Grader",
    "GraderCaseResult",
    "GraderResult",
    "worst_status",
]
