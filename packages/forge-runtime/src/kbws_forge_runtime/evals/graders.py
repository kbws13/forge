"""Deterministic graders + optional LLM-as-judge.

Graders are plain objects with a ``key`` and an async ``grade`` method, so they
compose like LangSmith evaluators. Deterministic graders read
``case.expected`` by default (a fixed override is also accepted). The
LLM-judge grader reuses the service's ``model_factory``; it is opt-in per
grader and its failures surface as ``NOT_EVALUATED`` (never ``FAILED``).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from typing import Any

from jsonschema import ValidationError
from jsonschema import validate as jsonschema_validate
from langchain_core.messages import HumanMessage, SystemMessage

from kbws_forge_runtime.models import ChatResult

from .models import EvalCase, EvalStatus, Grader, GraderResult


def _expected(case: EvalCase, override: Any, label: str) -> Any:
    value = case.expected if override is None else override
    if value is None:
        raise ValueError(f"grader {label} needs case.expected (or an explicit value)")
    return value


def _normalize(value: str) -> str:
    return " ".join(value.strip().split())


class _ExactGrader:
    def __init__(
        self,
        expected: str | None,
        *,
        key: str,
        normalize: bool,
    ) -> None:
        self.key = key
        self._expected = expected
        self._normalize = normalize

    async def grade(self, case: EvalCase, result: ChatResult, events) -> GraderResult:
        expected = str(_expected(case, self._expected, self.key))
        actual = result.content
        if self._normalize:
            expected, actual = _normalize(expected), _normalize(actual)
        passed = actual == expected
        return GraderResult(
            key=self.key,
            status=EvalStatus.PASSED if passed else EvalStatus.FAILED,
            score=1.0 if passed else 0.0,
            reason="" if passed else f"expected {expected!r}, got {result.content!r}",
            detail={"expected": expected, "actual": actual},
        )


class _ContainsGrader:
    def __init__(self, substring: str | None, *, key: str) -> None:
        self.key = key
        self._substring = substring

    async def grade(self, case: EvalCase, result: ChatResult, events) -> GraderResult:
        substring = str(_expected(case, self._substring, self.key))
        passed = substring in result.content
        return GraderResult(
            key=self.key,
            status=EvalStatus.PASSED if passed else EvalStatus.FAILED,
            score=1.0 if passed else 0.0,
            reason="" if passed else f"missing substring {substring!r}",
            detail={"substring": substring},
        )


class _RegexGrader:
    def __init__(self, pattern: str | None, *, key: str, flags: int) -> None:
        self.key = key
        self._pattern = pattern
        self._flags = flags

    async def grade(self, case: EvalCase, result: ChatResult, events) -> GraderResult:
        pattern = str(_expected(case, self._pattern, self.key))
        try:
            match = re.search(pattern, result.content, self._flags)
        except re.error as exc:
            return GraderResult(
                key=self.key,
                status=EvalStatus.NOT_EVALUATED,
                reason=f"invalid regex pattern: {exc}",
                detail={"pattern": pattern},
            )
        passed = match is not None
        return GraderResult(
            key=self.key,
            status=EvalStatus.PASSED if passed else EvalStatus.FAILED,
            score=1.0 if passed else 0.0,
            reason="" if passed else f"pattern {pattern!r} did not match",
            detail={"pattern": pattern, "matched": match.group(0) if match else None},
        )


class _JsonSchemaGrader:
    def __init__(self, schema: dict | None, *, key: str) -> None:
        self.key = key
        self._schema = schema

    async def grade(self, case: EvalCase, result: ChatResult, events) -> GraderResult:
        schema = _expected(case, self._schema, self.key)
        if not isinstance(schema, dict):
            return GraderResult(
                key=self.key,
                status=EvalStatus.NOT_EVALUATED,
                reason="json_schema grader requires a dict schema",
            )
        payload: Any = result.parsed
        if payload is None:
            try:
                payload = json.loads(result.content)
            except (json.JSONDecodeError, TypeError) as exc:
                return GraderResult(
                    key=self.key,
                    status=EvalStatus.FAILED,
                    score=0.0,
                    reason=f"output is not valid JSON: {exc}",
                )
        try:
            jsonschema_validate(payload, schema)
        except ValidationError as exc:
            return GraderResult(
                key=self.key,
                status=EvalStatus.FAILED,
                score=0.0,
                reason=f"output does not match schema: {exc.message}",
                detail={"path": list(exc.absolute_path)},
            )
        return GraderResult(key=self.key, status=EvalStatus.PASSED, score=1.0)


def _tool_names(events: Sequence[dict[str, Any]]) -> list[str]:
    return [
        event.get("tool_name", "")
        for event in events
        if event.get("type") == "tool_started" and event.get("tool_name")
    ]


class _ToolTrajectoryGrader:
    def __init__(
        self,
        expected: Sequence[str] | None,
        *,
        require_all: bool,
        ordered: bool,
        key: str,
    ) -> None:
        self.key = key
        self._expected = expected
        self._require_all = require_all
        self._ordered = ordered

    async def grade(self, case: EvalCase, result: ChatResult, events) -> GraderResult:
        expected = list(_expected(case, self._expected, self.key))
        if not isinstance(expected, (list, tuple)) or not all(
            isinstance(name, str) for name in expected
        ):
            return GraderResult(
                key=self.key,
                status=EvalStatus.NOT_EVALUATED,
                reason="tool_trajectory expects case.expected to be a list of tool names",
            )
        actual = _tool_names(events)
        if self._require_all:
            missing = [name for name in expected if name not in actual]
            passed = not missing
            reason = "" if passed else f"tools not called: {missing}"
        else:
            passed = any(name in actual for name in expected)
            reason = "" if passed else f"none of {expected} were called"
        if passed and self._ordered:
            actual_ordered = [name for name in actual if name in expected]
            passed = actual_ordered == expected
            reason = (
                ""
                if passed
                else f"tool order mismatch: expected {expected}, got {actual_ordered}"
            )
        return GraderResult(
            key=self.key,
            status=EvalStatus.PASSED if passed else EvalStatus.FAILED,
            score=1.0 if passed else 0.0,
            reason=reason,
            detail={"expected": expected, "actual": actual},
        )


class _LlmJudge:
    def __init__(
        self,
        model_factory: Callable[[], Any],
        rubric: str,
        *,
        key: str,
        pass_threshold: float,
    ) -> None:
        self.key = key
        self._model_factory = model_factory
        self._rubric = rubric
        self._pass_threshold = pass_threshold

    async def grade(self, case: EvalCase, result: ChatResult, events) -> GraderResult:
        prompt = (
            "You are an evaluation judge. Grade the agent's response against the rubric.\n"
            f"RUBRIC:\n{self._rubric}\n\n"
            f"CASE INPUT:\n{case.input or ''}\n\n"
            f"EXPECTED:\n{case.expected if case.expected is not None else '(none)'}\n\n"
            f"ACTUAL RESPONSE:\n{result.content}\n\n"
            'Reply with a single JSON object: {"score": 0.0 to 1.0, "reason": "..."}'
        )
        try:
            model = self._model_factory()
            response = await model.ainvoke(
                [
                    SystemMessage(content="You are a strict, fair evaluation judge."),
                    HumanMessage(content=prompt),
                ]
            )
            payload = json.loads(response.content)
        except Exception as exc:  # judge 基础设施失败 → NOT_EVALUATED，不污染结果
            return GraderResult(
                key=self.key,
                status=EvalStatus.NOT_EVALUATED,
                reason=f"llm judge failed: {exc}",
            )
        score = float(payload.get("score", 0.0))
        score = max(0.0, min(1.0, score))
        reason = str(payload.get("reason", ""))
        return GraderResult(
            key=self.key,
            status=EvalStatus.PASSED if score >= self._pass_threshold else EvalStatus.FAILED,
            score=score,
            reason=reason,
            detail={"raw": payload},
        )


def exact(expected: str | None = None, *, key: str = "exact", normalize: bool = True) -> Grader:
    """String equality against ``case.expected`` (whitespace-normalized by default)."""
    return _ExactGrader(expected, key=key, normalize=normalize)


def contains(substring: str | None = None, *, key: str = "contains") -> Grader:
    """Substring presence in the response (``case.expected`` by default)."""
    return _ContainsGrader(substring, key=key)


def regex(pattern: str | None = None, *, key: str = "regex", flags: int = 0) -> Grader:
    """Regex search on the response (``case.expected`` by default)."""
    return _RegexGrader(pattern, key=key, flags=flags)


def json_schema(schema: dict | None = None, *, key: str = "json_schema") -> Grader:
    """Validate ``result.parsed`` (or parsed content) against a JSON Schema."""
    return _JsonSchemaGrader(schema, key=key)


def tool_trajectory(
    expected: Sequence[str] | None = None,
    *,
    require_all: bool = True,
    ordered: bool = False,
    key: str = "tool_trajectory",
) -> Grader:
    """Check the run's tool trajectory against expected tool names."""
    return _ToolTrajectoryGrader(
        expected, require_all=require_all, ordered=ordered, key=key
    )


def llm_judge(
    model_factory: Callable[[], Any],
    rubric: str,
    *,
    key: str = "llm_judge",
    pass_threshold: float = 0.5,
) -> Grader:
    """LLM-as-judge reusing the service's model factory (opt-in per grader)."""
    return _LlmJudge(
        model_factory, rubric, key=key, pass_threshold=pass_threshold
    )


__all__ = [
    "contains",
    "exact",
    "json_schema",
    "llm_judge",
    "regex",
    "tool_trajectory",
]
