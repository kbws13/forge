"""Eval models: case validation, status aggregation, run totals."""

from __future__ import annotations

import pytest

from kbws_forge_runtime import (
    ChatMessage,
    EvalCase,
    EvalCaseResult,
    EvalRun,
    EvalStatus,
    EvalSuite,
    GraderResult,
    RunPolicy,
    exact,
)
from kbws_forge_runtime.evals.models import worst_status


def test_case_requires_input_xor_conversation() -> None:
    with pytest.raises(ValueError):
        EvalCase(id="c", input=None, conversation=None)
    with pytest.raises(ValueError):
        EvalCase(id="c", input="hi", conversation=(ChatMessage.user("hi"),))
    with pytest.raises(ValueError):
        EvalCase(id="c", conversation=())
    assert EvalCase(id="c", input="hi")
    assert EvalCase(id="c", conversation=(ChatMessage.user("a"), ChatMessage.user("b")))


def test_suite_validation() -> None:
    with pytest.raises(ValueError):
        EvalSuite(id="s", agent_id="a")
    with pytest.raises(ValueError):
        EvalSuite(id="s", agent_id="a", cases=(EvalCase(id="c", input="x"),), repetitions=0)
    suite = EvalSuite(
        id="s",
        agent_id="a",
        cases=(EvalCase(id="c", input="x"),),
        policy=RunPolicy(max_concurrency=2),
    )
    assert suite.policy is not None
    assert suite.policy.max_concurrency == 2


def test_grader_result_shapes() -> None:
    ok = GraderResult(key="exact", status=EvalStatus.PASSED, score=1.0)
    assert ok.model_dump(mode="json")["status"] == "passed"
    fail = GraderResult(
        key="contains",
        status=EvalStatus.FAILED,
        score=0.0,
        reason="missing substring 'x'",
    )
    assert fail.reason


def test_worst_status_precedence() -> None:
    assert worst_status([EvalStatus.PASSED, EvalStatus.PASSED]) == EvalStatus.PASSED
    assert (
        worst_status([EvalStatus.PASSED, EvalStatus.NOT_EVALUATED])
        == EvalStatus.NOT_EVALUATED
    )
    assert (
        worst_status([EvalStatus.NOT_EVALUATED, EvalStatus.FAILED])
        == EvalStatus.FAILED
    )


def test_eval_run_totals_and_average() -> None:
    run = EvalRun(
        suite_id="s",
        agent_id="a",
        status="finished",
        cases=(
            EvalCaseResult(case_id="p", status=EvalStatus.PASSED, score=1.0),
            EvalCaseResult(case_id="f", status=EvalStatus.FAILED, score=0.0),
            EvalCaseResult(case_id="n", status=EvalStatus.NOT_EVALUATED, score=None),
        ),
    )
    assert run.totals == {
        "total": 3,
        "passed": 1,
        "failed": 1,
        "not_evaluated": 1,
        "evaluated": 2,
    }
    assert run.average_score == 0.5


def test_suite_can_hold_graders() -> None:
    suite = EvalSuite(
        id="s",
        agent_id="a",
        graders=(exact(),),
        cases=(EvalCase(id="c", input="x", expected="y"),),
    )
    assert suite.graders[0].key == "exact"
