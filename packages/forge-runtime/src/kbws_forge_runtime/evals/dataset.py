"""JSONL dataset interchange for eval cases.

A dataset is one case per line: ``{id, input|conversation, expected,
variables, tags, metadata, graders: [names]}``. Graders travel by *name* —
the code stays the source of truth. Import resolves names from a registry
(builtin deterministic graders by default) and errors on unknown names.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from kbws_forge_runtime.evals.graders import contains, exact, json_schema, regex, tool_trajectory
from kbws_forge_runtime.evals.models import EvalCase, EvalSuite, Grader
from kbws_forge_runtime.models import ChatMessage

# 参数化 grader 走 case.expected，因此可以单例复用
BUILTIN_GRADERS: dict[str, Grader] = {
    "exact": exact(),
    "contains": contains(),
    "regex": regex(),
    "json_schema": json_schema(),
    "tool_trajectory": tool_trajectory(),
}


def _case_input(case: EvalCase) -> str | dict[str, Any]:
    if case.input is None:
        return ""
    return case.input if isinstance(case.input, str) else case.input.model_dump(mode="json")


def case_to_row(case: EvalCase) -> dict[str, Any]:
    """Serialize a case to one dataset row (graders as names)."""
    row: dict[str, Any] = {"id": case.id}
    if case.conversation is not None:
        row["conversation"] = [
            message.model_dump(mode="json") for message in case.conversation
        ]
    else:
        row["input"] = _case_input(case)
    if case.expected is not None:
        row["expected"] = case.expected
    if case.variables:
        row["variables"] = case.variables
    if case.tags:
        row["tags"] = list(case.tags)
    if case.metadata:
        row["metadata"] = case.metadata
    row["graders"] = [grader.key for grader in case.graders]
    return row


def export_suite(suite: EvalSuite, path: str | Path) -> int:
    """Write a suite's cases as JSONL; returns the number of cases written."""
    target = Path(path)
    lines = [
        json.dumps(case_to_row(case), ensure_ascii=False, sort_keys=True)
        for case in suite.cases
    ]
    target.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return len(lines)


def _resolve_grader(
    key: str, registry: Mapping[str, Grader]
) -> Grader:
    grader = registry.get(key)
    if grader is None:
        raise ValueError(
            f"dataset references unknown grader {key!r}; available: {sorted(registry)}"
        )
    return grader


def load_cases(
    path: str | Path,
    *,
    grader_registry: Mapping[str, Grader] | None = None,
) -> list[EvalCase]:
    """Read JSONL cases; graders resolved by name (builtin + custom registry)."""
    registry = {**BUILTIN_GRADERS, **(grader_registry or {})}
    cases: list[EvalCase] = []
    for line_number, line in enumerate(
        (line for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()),
        start=1,
    ):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"dataset line {line_number} is not valid JSON: {exc}") from exc
        case_id = row.get("id")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError(f"dataset line {line_number} is missing a string `id`")

        conversation = row.get("conversation")
        raw_input = row.get("input")
        if conversation is not None:
            if not isinstance(conversation, list) or not conversation:
                raise ValueError(f"dataset line {line_number} has an invalid `conversation`")
            messages = tuple(ChatMessage.model_validate(item) for item in conversation)
        elif isinstance(raw_input, dict):
            messages = None
            raw_input = ChatMessage.model_validate(raw_input)
        else:
            messages = None

        grader_keys = row.get("graders", [])
        if not isinstance(grader_keys, list):
            raise ValueError(f"dataset line {line_number} has an invalid `graders` list")
        graders = tuple(_resolve_grader(str(key), registry) for key in grader_keys)

        cases.append(
            EvalCase(
                id=case_id,
                input=None if messages is not None else (raw_input or ""),
                conversation=messages,
                expected=row.get("expected"),
                graders=graders,
                variables=row.get("variables"),
                tags=tuple(row.get("tags", [])),
                metadata=row.get("metadata", {}),
            )
        )
    return cases


__all__ = ["BUILTIN_GRADERS", "case_to_row", "export_suite", "load_cases"]
