"""forge eval commands: run / compare / dataset (HTTP layer mocked)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from kbws_forge_cli.cli import app

runner = CliRunner()


def _run_payload() -> dict[str, Any]:
    return {
        "eval_run_id": "ev-12345678",
        "suite_id": "smoke",
        "status": "finished",
        "average_score": 0.5,
        "provenance": {"mode": "live", "model": "deepseek-chat"},
        "totals": {"total": 2, "passed": 1, "failed": 1, "not_evaluated": 0, "evaluated": 2},
        "cases": [
            {
                "case_id": "add_tool",
                "status": "passed",
                "score": 1.0,
                "run_ids": ["r1"],
                "failure_reasons": [],
                "graders": [],
            },
            {
                "case_id": "time_tool",
                "status": "failed",
                "score": 0.0,
                "run_ids": ["r2"],
                "failure_reasons": ["tools not called: ['current_time']"],
                "graders": [],
            },
        ],
    }


def _fake_client(routes: dict[tuple[str, str], Any]) -> Any:
    def get(path: str) -> Any:
        return routes.get(("GET", path))

    def post(path: str, body: dict | None = None) -> Any:
        return routes.get(("POST", path))

    return type(
        "FakeClient", (), {"get": staticmethod(get), "post": staticmethod(post)}
    )()


def test_eval_run_prints_summary(monkeypatch) -> None:
    monkeypatch.setattr("kbws_forge_cli.eval_commands.api_client", lambda *_: _fake_client({("POST", "/evals/smoke/run"): _run_payload()}))
    result = runner.invoke(app, ["eval", "run", "smoke"])
    assert result.exit_code == 0, result.output
    assert "1/2" in result.output
    assert "tools not called" in result.output


def test_eval_run_fail_under_gate(monkeypatch) -> None:
    monkeypatch.setattr("kbws_forge_cli.eval_commands.api_client", lambda *_: _fake_client({("POST", "/evals/smoke/run"): _run_payload()}))
    passed = runner.invoke(app, ["eval", "run", "smoke", "--fail-under", "0.5"])
    assert passed.exit_code == 0, passed.output
    failed = runner.invoke(app, ["eval", "run", "smoke", "--fail-under", "0.6"])
    assert failed.exit_code == 1
    assert "GATE FAILED" in failed.output


def test_eval_run_writes_json_and_junit_reports(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("kbws_forge_cli.eval_commands.api_client", lambda *_: _fake_client({("POST", "/evals/smoke/run"): _run_payload()}))
    result = runner.invoke(
        app,
        ["eval", "run", "smoke", "--report", "json", "--report", "junit", "-o", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output
    json_path = tmp_path / "smoke-ev-12345.json"
    xml_path = tmp_path / "smoke-ev-12345.xml"
    assert json_path.is_file()
    assert json.loads(json_path.read_text())["suite_id"] == "smoke"

    xml = xml_path.read_text()
    assert "<testsuites" in xml
    assert 'failures="1"' in xml
    assert '<testcase name="add_tool"' in xml
    assert '<failure message="tools not called' in xml


def test_eval_run_replay_mode_passes_mode(monkeypatch) -> None:
    sent: dict[str, Any] = {}

    def post(path: str, body: dict | None = None) -> Any:
        sent["body"] = body
        return _run_payload()

    client = type(
        "FakeClient", (), {"get": staticmethod(lambda _, p: None), "post": staticmethod(post)}
    )()
    monkeypatch.setattr("kbws_forge_cli.eval_commands.api_client", lambda *_: client)
    runner.invoke(app, ["eval", "run", "smoke", "--mode", "replay", "--cases", "add_tool,time_tool", "--repetitions", "2"])
    assert sent["body"] == {"mode": "replay", "case_ids": ["add_tool", "time_tool"], "repetitions": 2}


def test_eval_compare_detects_regression(monkeypatch) -> None:
    baseline = _run_payload()
    candidate = _run_payload()
    candidate["cases"][0]["status"] = "failed"  # add_tool 回归
    candidate["cases"][0]["failure_reasons"] = ["regressed"]
    candidate["average_score"] = 0.0
    routes = {
        ("GET", "/evals/runs/base"): baseline,
        ("GET", "/evals/runs/cand"): candidate,
    }
    monkeypatch.setattr("kbws_forge_cli.eval_commands.api_client", lambda *_: _fake_client(routes))
    result = runner.invoke(app, ["eval", "compare", "--baseline", "base", "--candidate", "cand"])
    assert result.exit_code == 1
    assert "add_tool" in result.output
    assert "regressions" in result.output


def test_eval_compare_no_regression_exits_zero(monkeypatch) -> None:
    routes = {
        ("GET", "/evals/runs/base"): _run_payload(),
        ("GET", "/evals/runs/cand"): _run_payload(),
    }
    monkeypatch.setattr("kbws_forge_cli.eval_commands.api_client", lambda *_: _fake_client(routes))
    result = runner.invoke(app, ["eval", "compare", "--baseline", "base", "--candidate", "cand"])
    assert result.exit_code == 0, result.output


def test_eval_dataset_export_writes_jsonl(monkeypatch, tmp_path: Path) -> None:
    suite = {
        "id": "smoke",
        "cases": [
            {"id": "a", "input": "x", "expected": "y", "graders": ["exact"]},
            {"id": "b", "input": "z", "expected": ["t"], "graders": ["tool_trajectory"]},
        ],
    }
    routes = {("GET", "/evals/smoke"): suite}
    monkeypatch.setattr("kbws_forge_cli.eval_commands.api_client", lambda *_: _fake_client(routes))
    out = tmp_path / "cases.jsonl"
    result = runner.invoke(app, ["eval", "dataset", "export", "smoke", "-o", str(out)])
    assert result.exit_code == 0, result.output
    lines = out.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["graders"] == ["exact"]


def test_eval_dataset_import_generates_module(tmp_path: Path) -> None:
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text(
        '{"id": "math", "input": "1+1?", "expected": "2", "graders": ["exact"]}\n'
        '{"id": "tool", "input": "now", "expected": ["current_time"], "graders": ["tool_trajectory"]}\n',
        encoding="utf-8",
    )
    out = tmp_path / "evals"
    result = runner.invoke(
        app,
        ["eval", "dataset", "import", str(dataset), "--name", "golden", "--agent", "test_agent", "-o", str(out)],
    )
    assert result.exit_code == 0, result.output
    module = (out / "golden.py").read_text(encoding="utf-8")
    assert "id='golden'" in module
    assert "agent_id='test_agent'" in module
    assert 'EvalCase(\n                id="math"' in module
    assert '_GRADERS["exact"]()' in module


def test_eval_dataset_import_rejects_unknown_grader(tmp_path: Path) -> None:
    dataset = tmp_path / "bad.jsonl"
    dataset.write_text('{"id": "c", "input": "x", "graders": ["llm_judge"]}\n', encoding="utf-8")
    result = runner.invoke(
        app,
        ["eval", "dataset", "import", str(dataset), "--name", "bad", "--agent", "a", "-o", str(tmp_path / "evals")],
    )
    assert result.exit_code == 1
    assert "unknown grader" in result.output
