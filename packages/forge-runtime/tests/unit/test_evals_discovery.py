"""Eval suite discovery from an ``evals/`` directory."""

from __future__ import annotations

from pathlib import Path

import pytest

from kbws_forge_runtime.evals.discovery import load_eval_suites


def _write(root: Path, name: str, body: str) -> Path:
    module = root / f"{name}.py"
    module.write_text(body, encoding="utf-8")
    return module


def test_discovers_single_suite(tmp_path: Path) -> None:
    evals_dir = tmp_path / "suite_evals"
    evals_dir.mkdir()
    _write(
        evals_dir,
        "basic",
        "from kbws_forge_runtime import EvalCase, EvalSuite, exact\n"
        "suite = EvalSuite(\n"
        "    id='basic', agent_id='a',\n"
        "    cases=(EvalCase(id='c', input='x', expected='y', graders=(exact(),)),),\n"
        ")\n",
    )
    suites = load_eval_suites(evals_dir)
    assert [suite.id for suite in suites] == ["basic"]
    assert suites[0].cases[0].expected == "y"


def test_discovers_multiple_suites_from_one_module(tmp_path: Path) -> None:
    evals_dir = tmp_path / "multi_evals"
    evals_dir.mkdir()
    _write(
        evals_dir,
        "multi",
        "from kbws_forge_runtime import EvalCase, EvalSuite\n"
        "suites = [\n"
        "    EvalSuite(id='s1', agent_id='a', cases=(EvalCase(id='c', input='x'),)),\n"
        "    EvalSuite(id='s2', agent_id='a', cases=(EvalCase(id='c', input='x'),)),\n"
        "]\n",
    )
    assert [suite.id for suite in load_eval_suites(evals_dir)] == ["s1", "s2"]


def test_skips_modules_without_suite_and_init(tmp_path: Path) -> None:
    evals_dir = tmp_path / "skip_evals"
    evals_dir.mkdir()
    _write(evals_dir, "__init__", "")
    _write(evals_dir, "shared_graders", "from kbws_forge_runtime import exact\nG = exact()\n")
    assert load_eval_suites(evals_dir) == []


def test_rejects_non_suite_export(tmp_path: Path) -> None:
    evals_dir = tmp_path / "bad_evals"
    evals_dir.mkdir()
    _write(evals_dir, "bad", "suite = 42\n")
    with pytest.raises(ValueError, match="must export an `EvalSuite`"):
        load_eval_suites(evals_dir)


def test_rejects_duplicate_ids(tmp_path: Path) -> None:
    evals_dir = tmp_path / "dup_evals"
    evals_dir.mkdir()
    _write(
        evals_dir,
        "a",
        "from kbws_forge_runtime import EvalCase, EvalSuite\n"
        "suite = EvalSuite(id='dup', agent_id='a', cases=(EvalCase(id='c', input='x'),))\n",
    )
    _write(
        evals_dir,
        "b",
        "from kbws_forge_runtime import EvalCase, EvalSuite\n"
        "suite = EvalSuite(id='dup', agent_id='a', cases=(EvalCase(id='c', input='x'),))\n",
    )
    with pytest.raises(ValueError, match="duplicate eval suite id"):
        load_eval_suites(evals_dir)


def test_missing_directory_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        load_eval_suites(tmp_path / "nope")


@pytest.mark.asyncio
async def test_discovered_suite_runs_end_to_end(tmp_path: Path) -> None:
    """真实链路：evals/ 发现 → EvalRunner(live) → 真实 runtime + fake model。"""
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    from langgraph.checkpoint.memory import InMemorySaver

    from kbws_forge_runtime import AgentInfo, AgentRuntime
    from kbws_forge_runtime.agent import Agent
    from kbws_forge_runtime.evals.runner import EvalRunner
    from kbws_forge_runtime.evals.store import EvalStore
    from kbws_forge_runtime.prompts import Message, Prompt

    evals_dir = tmp_path / "e2e_evals"
    evals_dir.mkdir()
    _write(
        evals_dir,
        "hello",
        "from kbws_forge_runtime import EvalCase, EvalSuite, exact, contains\n"
        "suite = EvalSuite(\n"
        "    id='hello', agent_id='t1',\n"
        "    cases=(\n"
        "        EvalCase(id='pass', input='hi', expected='ok', graders=(exact(),)),\n"
        "        EvalCase(id='word', input='hi', expected='ok', graders=(contains('k'),)),\n"
        "        EvalCase(id='fail', input='hi', expected='nope', graders=(exact(),)),\n"
        "    ),\n"
        ")\n",
    )
    suites = load_eval_suites(evals_dir)
    assert len(suites) == 1

    agent = Agent(
        agent_id="t1",
        name="T1",
        prompt=Prompt(name="p", messages=[Message.system("你是助手")]),
        checkpointer=InMemorySaver(),
    )
    runtime = AgentRuntime(plugins=[])
    runtime.register_agent(
        AgentInfo(agent_id="t1", name="T1"),
        await agent.build_graph(lambda: FakeListChatModel(responses=["ok"])),
    )

    runner = EvalRunner(runtime, store=EvalStore(persist_dir=tmp_path / "evals-store"))
    eval_run = await runner.run(suites[0])

    assert eval_run.status == "finished"
    by_id = {case.case_id: case for case in eval_run.cases}
    assert by_id["pass"].status.value == "passed"
    assert by_id["word"].status.value == "passed"
    assert by_id["fail"].status.value == "failed"
    # 真实 TraceStore 记录了 run，且 EvalRunner 能从事件里取数据
    run_id = by_id["pass"].run_ids[0]
    assert runtime.trace_store.get_run(run_id) is not None
