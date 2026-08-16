"""EvalStore persistence: roundtrip, pruning, corrupt tolerance, by_run_id."""

from __future__ import annotations

import pytest

from kbws_forge_runtime import (
    EvalCase,
    EvalCaseResult,
    EvalRun,
    EvalStatus,
    EvalStore,
    EvalSuite,
    exact,
)
from kbws_forge_runtime.evals.runner import EvalRunner


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

    async def chat(self, agent_id, user_id, message, session_id=None, variables=None, policy=None):
        self._index += 1
        content, events = self._responses[(self._index - 1) % len(self._responses)]
        run_id = f"run-{self._index}"
        self.trace_store.record(run_id, events)
        from kbws_forge_runtime import ChatMessage, ChatResult

        return ChatResult(
            run_id=run_id,
            agent_id=agent_id,
            user_id=user_id,
            session_id=session_id or f"sess-{self._index}",
            message=ChatMessage.assistant(content),
        )


def make_run(
    *, status: str = "finished", eval_run_id: str = "ev-1", suite_id: str = "s"
) -> EvalRun:
    return EvalRun(
        eval_run_id=eval_run_id,
        suite_id=suite_id,
        agent_id="a",
        status=status,
        provenance={"model": "m"},
        cases=(
            EvalCaseResult(
                case_id="c1",
                run_ids=("run-1",),
                status=EvalStatus.PASSED,
                score=1.0,
            ),
        ),
    )


def test_save_and_reload_roundtrip(tmp_path) -> None:
    store = EvalStore(persist_dir=tmp_path / "evals")
    store._runs["ev-1"] = make_run()  # noqa: SLF001 — 直接注入后触发持久化
    store._order.append("ev-1")  # noqa: SLF001
    store._persist(store._runs["ev-1"])  # noqa: SLF001

    reloaded = EvalStore(persist_dir=tmp_path / "evals")
    run = reloaded.get_run("ev-1")
    assert run is not None
    assert run["suite_id"] == "s"
    assert run["cases"][0]["case_id"] == "c1"
    assert run["cases"][0]["run_ids"] == ["run-1"]


@pytest.mark.asyncio
async def test_store_roundtrip_via_runner(tmp_path) -> None:
    runtime = FakeRuntime([("2", [])])
    store = EvalStore(persist_dir=tmp_path / "evals")
    runner = EvalRunner(runtime, store=store)
    suite = EvalSuite(
        id="s", agent_id="a", cases=(EvalCase(id="c", input="x", expected="2", graders=(exact(),)),)
    )
    eval_run = await runner.run(suite)

    reloaded = EvalStore(persist_dir=tmp_path / "evals")
    assert reloaded.get_run(eval_run.eval_run_id) is not None
    assert reloaded.list_runs()[0]["suite_id"] == "s"


def test_list_runs_newest_first_and_pruning(tmp_path) -> None:
    store = EvalStore(persist_dir=tmp_path / "evals", max_runs=2)
    for index in range(3):
        run = make_run(eval_run_id=f"ev-{index}", suite_id=f"s-{index}")
        store._runs[run.eval_run_id] = run  # noqa: SLF001
        store._order.append(run.eval_run_id)  # noqa: SLF001
        store._persist(run)
    store._trim()  # noqa: SLF001

    ids = [run["suite_id"] for run in store.list_runs()]
    assert ids == ["s-2", "s-1"]


def test_corrupt_file_tolerated(tmp_path) -> None:
    (tmp_path / "evals").mkdir(parents=True)
    (tmp_path / "evals" / "bad.json").write_text("{not json", encoding="utf-8")
    store = EvalStore(persist_dir=tmp_path / "evals")
    assert store.list_runs() == []


def test_delete_and_clear(tmp_path) -> None:
    store = EvalStore(persist_dir=tmp_path / "evals")
    store._runs["ev-1"] = make_run()  # noqa: SLF001
    store._order.append("ev-1")  # noqa: SLF001
    store._persist(store._runs["ev-1"])  # noqa: SLF001

    assert store.delete_run("missing") is False
    assert store.delete_run("ev-1") is True
    assert store.get_run("ev-1") is None
    assert not (tmp_path / "evals" / "ev-1.json").exists()
