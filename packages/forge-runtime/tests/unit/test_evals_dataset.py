"""JSONL dataset export/import: roundtrip, grader resolution, errors."""

from __future__ import annotations

import json

import pytest

from kbws_forge_runtime import (
    BUILTIN_GRADERS,
    ChatMessage,
    EvalCase,
    EvalSuite,
    exact,
    export_suite,
    load_cases,
    regex,
    tool_trajectory,
)


def sample_suite() -> EvalSuite:
    return EvalSuite(
        id="ds",
        agent_id="a",
        cases=(
            EvalCase(id="math", input="1+1?", expected="2", graders=(exact(),)),
            EvalCase(
                id="date",
                input="日期",
                expected=r"\d{4}-\d{2}-\d{2}",
                graders=(regex(),),
            ),
            EvalCase(
                id="time_tool",
                input="几点",
                expected=["current_time"],
                graders=(tool_trajectory(),),
                tags=("tools",),
                metadata={"weight": 2},
            ),
            EvalCase(
                id="conv",
                conversation=(ChatMessage.user("a"), ChatMessage.user("b")),
                expected="x",
                graders=(exact(),),
            ),
        ),
    )


def test_export_import_roundtrip(tmp_path) -> None:
    path = tmp_path / "cases.jsonl"
    written = export_suite(sample_suite(), path)
    assert written == 4
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4
    # grader 以名字序列化
    assert json.loads(lines[0])["graders"] == ["exact"]

    cases = load_cases(path)
    assert [case.id for case in cases] == ["math", "date", "time_tool", "conv"]
    math = cases[0]
    assert math.expected == "2"
    assert math.graders[0].key == "exact"
    assert cases[2].tags == ("tools",)
    assert cases[2].metadata == {"weight": 2}
    assert cases[3].conversation is not None
    assert cases[3].input is None
    assert [m.parts[0].text for m in cases[3].conversation] == ["a", "b"]


def test_unknown_grader_name_raises(tmp_path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text(
        json.dumps({"id": "c", "input": "x", "graders": ["llm_judge"]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown grader 'llm_judge'"):
        load_cases(path)


def test_custom_grader_registry(tmp_path) -> None:
    class CustomGrader:
        key = "custom"

        async def grade(self, case, result, events):
            from kbws_forge_runtime import EvalStatus, GraderResult

            return GraderResult(key="custom", status=EvalStatus.PASSED, score=1.0)

    path = tmp_path / "custom.jsonl"
    path.write_text(
        json.dumps({"id": "c", "input": "x", "graders": ["custom"]}),
        encoding="utf-8",
    )
    cases = load_cases(path, grader_registry={"custom": CustomGrader()})
    assert cases[0].graders[0].key == "custom"


def test_invalid_json_line_raises(tmp_path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text('{"id": "ok"}\nnot-json\n', encoding="utf-8")
    with pytest.raises(ValueError, match="line 2"):
        load_cases(path)


def test_builtin_registry_has_deterministic_graders() -> None:
    assert set(BUILTIN_GRADERS) == {
        "exact",
        "contains",
        "regex",
        "json_schema",
        "tool_trajectory",
    }
    for grader in BUILTIN_GRADERS.values():
        assert grader.key in BUILTIN_GRADERS
