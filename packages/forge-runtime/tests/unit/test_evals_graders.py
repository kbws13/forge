"""Deterministic graders: pass/fail/edge cases + llm_judge wiring."""

from __future__ import annotations

import pytest

from kbws_forge_runtime import (
    ChatMessage,
    ChatResult,
    EvalCase,
    EvalStatus,
    contains,
    exact,
    json_schema,
    llm_judge,
    regex,
    tool_trajectory,
)

AGENT = {"agent_id": "a", "user_id": "u", "session_id": "s"}


def result(content: str, parsed=None) -> ChatResult:
    return ChatResult(
        run_id="r1",
        message=ChatMessage.assistant(content),
        parsed=parsed,
        **AGENT,
    )


def events(*tool_names: str) -> list[dict]:
    return [
        {"type": "tool_started", "tool_name": name}
        for name in tool_names
    ]


async def grade(grader, case, content="", parsed=None, evs=None):
    return await grader.grade(case, result(content, parsed), evs or [])


@pytest.mark.asyncio
async def test_exact() -> None:
    grader = exact()
    case = EvalCase(id="c", input="x", expected="2")
    passed = await grade(grader, case, "2")
    assert passed.status == EvalStatus.PASSED
    failed = await grade(grader, case, "3")
    assert failed.status == EvalStatus.FAILED
    # whitespace normalization
    normalized = await grade(grader, EvalCase(id="c", input="x", expected="a b"), " a   b ")
    assert normalized.status == EvalStatus.PASSED


@pytest.mark.asyncio
async def test_exact_explicit_override() -> None:
    grader = exact("fixed")
    assert (await grade(grader, EvalCase(id="c", input="x"), "fixed")).status == EvalStatus.PASSED


@pytest.mark.asyncio
async def test_contains() -> None:
    grader = contains("UTC")
    case = EvalCase(id="c", input="x", expected="UTC")
    passed = await grade(grader, case, "当前 UTC 时间是…")
    assert passed.status == EvalStatus.PASSED
    failed = await grade(grader, case, "没有时间")
    assert failed.status == EvalStatus.FAILED


@pytest.mark.asyncio
async def test_regex() -> None:
    grader = regex(r"\d{4}-\d{2}-\d{2}")
    case = EvalCase(id="c", input="x", expected=r"\d{4}-\d{2}-\d{2}")
    passed = await grade(grader, case, "2026-08-16")
    assert passed.status == EvalStatus.PASSED
    failed = await grade(grader, case, "no date")
    assert failed.status == EvalStatus.FAILED
    # 非法 pattern → NOT_EVALUATED
    bad = await grade(regex("("), EvalCase(id="c", input="x", expected="("), "x")
    assert bad.status == EvalStatus.NOT_EVALUATED
    assert "invalid regex" in bad.reason


@pytest.mark.asyncio
async def test_json_schema_parsed() -> None:
    schema = {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}
    grader = json_schema(schema)
    case = EvalCase(id="c", input="x", expected=schema)
    assert (await grade(grader, case, parsed={"name": "张三"})).status == EvalStatus.PASSED
    bad = await grade(grader, case, parsed={"age": 1})
    assert bad.status == EvalStatus.FAILED
    assert "does not match schema" in bad.reason


@pytest.mark.asyncio
async def test_json_schema_from_content() -> None:
    schema = {"type": "object", "required": ["ok"]}
    grader = json_schema(schema)
    case = EvalCase(id="c", input="x", expected=schema)
    assert (await grade(grader, case, content='{"ok": true}')).status == EvalStatus.PASSED
    bad = await grade(grader, case, content="not json")
    assert bad.status == EvalStatus.FAILED
    assert "not valid JSON" in bad.reason


@pytest.mark.asyncio
async def test_tool_trajectory() -> None:
    grader = tool_trajectory(["current_time"])
    case = EvalCase(id="c", input="x", expected=["current_time"])
    assert (await grade(grader, case, evs=events("current_time"))).status == EvalStatus.PASSED
    assert (await grade(grader, case, evs=events("add"))).status == EvalStatus.FAILED
    assert "current_time" in (await grade(grader, case, evs=events("add"))).reason


@pytest.mark.asyncio
async def test_tool_trajectory_require_all_and_ordered() -> None:
    case = EvalCase(id="c", input="x", expected=["a", "b"])
    all_grader = tool_trajectory(["a", "b"])
    assert (await grade(all_grader, case, evs=events("a", "b"))).status == EvalStatus.PASSED
    assert (await grade(all_grader, case, evs=events("a"))).status == EvalStatus.FAILED

    ordered_grader = tool_trajectory(["a", "b"], ordered=True)
    assert (await grade(ordered_grader, case, evs=events("a", "b"))).status == EvalStatus.PASSED
    assert (await grade(ordered_grader, case, evs=events("b", "a"))).status == EvalStatus.FAILED


@pytest.mark.asyncio
async def test_tool_trajectory_any_mode() -> None:
    grader = tool_trajectory(["web", "calc"], require_all=False)
    case = EvalCase(id="c", input="x", expected=["web", "calc"])
    assert (await grade(grader, case, evs=events("calc"))).status == EvalStatus.PASSED
    assert (await grade(grader, case, evs=events("other"))).status == EvalStatus.FAILED


@pytest.mark.asyncio
async def test_llm_judge_happy_path() -> None:
    class FakeJudge:
        async def ainvoke(self, messages):
            return type("Resp", (), {"content": '{"score": 0.9, "reason": "good"}'})()

    grader = llm_judge(lambda: FakeJudge(), "be helpful")
    verdict = await grade(grader, EvalCase(id="c", input="x"), "any")
    assert verdict.status == EvalStatus.PASSED
    assert verdict.score == 0.9


@pytest.mark.asyncio
async def test_llm_judge_failure_is_not_evaluated() -> None:
    def broken_factory():
        raise RuntimeError("provider down")

    grader = llm_judge(broken_factory, "rubric")
    verdict = await grade(grader, EvalCase(id="c", input="x"), "any")
    assert verdict.status == EvalStatus.NOT_EVALUATED
    assert "llm judge failed" in verdict.reason
