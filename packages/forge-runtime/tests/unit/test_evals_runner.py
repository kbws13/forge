"""EvalRunner: execution, grading isolation, repetitions, persistence."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from kbws_forge_runtime import (
    ChatMessage,
    ChatResult,
    EvalCase,
    EvalRunner,
    EvalStatus,
    EvalStore,
    EvalSuite,
    ForgeRuntimeError,
    RunPolicy,
    contains,
    exact,
    tool_trajectory,
)


class StubTraceStore:
    def __init__(self) -> None:
        self._runs: dict[str, dict] = {}

    def record(self, run_id: str, events: list[dict]) -> None:
        self._runs[run_id] = {"run_id": run_id, "events": events}

    def get_run(self, run_id: str) -> dict | None:
        return self._runs.get(run_id)


class FakeRuntime:
    def __init__(self, responses: list[tuple[str, list[dict]]]) -> None:
        self._responses = responses
        self._index = 0
        self.trace_store = StubTraceStore()
        self.sessions_created = 0
        self.policies_seen: list[RunPolicy | None] = []

    async def chat(
        self,
        agent_id,
        user_id,
        message,
        session_id=None,
        variables=None,
        policy=None,
    ) -> ChatResult:
        self.policies_seen.append(policy)
        self._index += 1
        content, events = self._responses[(self._index - 1) % len(self._responses)]
        run_id = f"run-{self._index}"
        self.trace_store.record(run_id, events)
        return ChatResult(
            run_id=run_id,
            agent_id=agent_id,
            user_id=user_id,
            session_id=session_id or f"sess-{self._index}",
            message=ChatMessage.assistant(content),
        )

    def create_session(self, agent_id, user_id):
        self.sessions_created += 1
        return SimpleNamespace(session_id=f"session-{self.sessions_created}")


def make_suite(cases: tuple[EvalCase, ...], **kwargs) -> EvalSuite:
    return EvalSuite(
        id="basic",
        agent_id="test_agent",
        cases=cases,
        **kwargs,
    )


@pytest.fixture
def runner(tmp_path) -> EvalRunner:
    runtime = FakeRuntime([("2", [{"type": "tool_started", "tool_name": "add"}])])
    store = EvalStore(persist_dir=tmp_path / "evals")
    return EvalRunner(runtime, store=store)


@pytest.mark.asyncio
async def test_runner_happy_path(runner: EvalRunner) -> None:
    suite = make_suite(
        (
            EvalCase(id="math", input="1+1?", expected="2", graders=(exact(),)),
            EvalCase(id="tool", input="now?", expected=["add"], graders=(tool_trajectory(),)),
            EvalCase(id="word", input="say hi", expected="hi", graders=(contains(),)),
        )
    )
    eval_run = await runner.run(suite)

    assert eval_run.status == "finished"
    assert eval_run.totals["total"] == 3
    assert eval_run.totals["passed"] == 2
    assert eval_run.totals["failed"] == 1
    assert eval_run.average_score == pytest.approx(2 / 3)

    by_id = {case.case_id: case for case in eval_run.cases}
    assert by_id["math"].status == EvalStatus.PASSED
    assert by_id["tool"].status == EvalStatus.PASSED
    assert by_id["word"].status == EvalStatus.FAILED
    assert by_id["word"].failure_reasons == ("missing substring 'hi'",)
    assert by_id["math"].run_ids == ("run-1",)


@pytest.mark.asyncio
async def test_runner_grader_exception_is_not_evaluated(runner: EvalRunner) -> None:
    class ExplodingGrader:
        key = "explode"

        async def grade(self, case, result, events):
            raise RuntimeError("boom")

    suite = make_suite(
        (
            EvalCase(id="a", input="x", expected="3", graders=(exact(), ExplodingGrader())),
        )
    )
    eval_run = await runner.run(suite)
    case = eval_run.cases[0]
    assert case.status == EvalStatus.FAILED  # exact 失败（期望 3，实际 2）
    by_key = {g.key: g for g in case.graders}
    assert by_key["explode"].status == EvalStatus.NOT_EVALUATED
    assert "boom" in by_key["explode"].reason


@pytest.mark.asyncio
async def test_runner_infra_error_isolates_case(tmp_path) -> None:
    class BrokenRuntime(FakeRuntime):
        async def chat(self, *args, **kwargs):
            raise ForgeRuntimeError("agent not found", code="E0001")

    runner = EvalRunner(
        BrokenRuntime([]), store=EvalStore(persist_dir=tmp_path / "evals")
    )
    suite = make_suite((EvalCase(id="a", input="x", graders=(exact(),)),))
    eval_run = await runner.run(suite)
    case = eval_run.cases[0]
    assert case.status == EvalStatus.FAILED
    assert case.error and "agent not found" in case.error


@pytest.mark.asyncio
async def test_runner_repetitions_average(runner: EvalRunner) -> None:
    runtime = runner._runtime  # noqa: SLF001
    runtime._responses = [("2", []), ("3", [])]  # 一过一挂
    suite = make_suite(
        (EvalCase(id="m", input="1+1?", expected="2", graders=(exact(),)),),
        repetitions=2,
    )
    eval_run = await runner.run(suite)
    case = eval_run.cases[0]
    assert len(case.run_ids) == 2
    assert case.score == pytest.approx(0.5)
    assert case.status == EvalStatus.FAILED  # 任一 repetition 失败 → 保守 FAILED


@pytest.mark.asyncio
async def test_runner_no_graders_not_evaluated(runner: EvalRunner) -> None:
    suite = make_suite((EvalCase(id="a", input="x"),))
    eval_run = await runner.run(suite)
    assert eval_run.cases[0].status == EvalStatus.NOT_EVALUATED
    assert "no graders configured" in eval_run.cases[0].failure_reasons


@pytest.mark.asyncio
async def test_runner_policy_passed_and_provenance(tmp_path) -> None:
    runtime = FakeRuntime([("2", [])])
    policy = RunPolicy(max_concurrency=2, timeout_seconds=30)
    runner = EvalRunner(runtime, store=EvalStore(persist_dir=tmp_path / "evals"))
    suite = make_suite(
        (EvalCase(id="a", input="x", expected="2", graders=(exact(),)),),
        policy=policy,
    )
    eval_run = await runner.run(suite, provenance={"model": "deepseek-chat"})
    assert runtime.policies_seen == [policy]
    assert eval_run.provenance["model"] == "deepseek-chat"
    assert eval_run.provenance["policy"]["max_concurrency"] == 2
    assert eval_run.provenance["repetitions"] == 1
    assert "git_sha" in eval_run.provenance


@pytest.mark.asyncio
async def test_runner_conversation_multi_turn(tmp_path) -> None:
    runtime = FakeRuntime([("first reply", []), ("final reply", [])])
    runner = EvalRunner(runtime, store=EvalStore(persist_dir=tmp_path / "evals"))
    suite = make_suite(
        (
            EvalCase(
                id="conv",
                conversation=(ChatMessage.user("q1"), ChatMessage.user("q2")),
                expected="final reply",
                graders=(exact(),),
            ),
        )
    )
    eval_run = await runner.run(suite)
    case = eval_run.cases[0]
    assert len(case.run_ids) == 2
    assert case.status == EvalStatus.PASSED
    assert runtime.sessions_created == 1  # 多轮共用同一会话


@pytest.mark.asyncio
async def test_runner_case_filter(runner: EvalRunner) -> None:
    suite = make_suite(
        (
            EvalCase(id="a", input="x", expected="2", graders=(exact(),)),
            EvalCase(id="b", input="y", expected="2", graders=(exact(),)),
        )
    )
    eval_run = await runner.run(suite, case_ids=["b"])
    assert [case.case_id for case in eval_run.cases] == ["b"]


@pytest.mark.asyncio
async def test_runner_modes(runner: EvalRunner) -> None:
    suite = make_suite((EvalCase(id="a", input="x", graders=(exact(),)),))
    with pytest.raises(NotImplementedError):
        await runner.run(suite, mode="replay")
    with pytest.raises(ValueError):
        await runner.run(suite, mode="bogus")


@pytest.mark.asyncio
async def test_runner_persists_to_store(runner: EvalRunner) -> None:
    suite = make_suite((EvalCase(id="a", input="x", expected="2", graders=(exact(),)),))
    eval_run = await runner.run(suite)
    loaded = runner.store.get_run(eval_run.eval_run_id)
    assert loaded is not None
    assert loaded["status"] == "finished"
    assert loaded["cases"][0]["case_id"] == "a"


@pytest.mark.asyncio
async def test_store_by_run_id(runner: EvalRunner) -> None:
    suite = make_suite((EvalCase(id="a", input="x", expected="2", graders=(exact(),)),))
    eval_run = await runner.run(suite)
    run_id = eval_run.cases[0].run_ids[0]
    hits = runner.store.by_run_id(run_id)
    assert len(hits) == 1
    assert hits[0]["case_id"] == "a"
    assert hits[0]["suite_id"] == "basic"
