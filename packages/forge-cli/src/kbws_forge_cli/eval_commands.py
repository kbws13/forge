"""forge eval commands: run, compare, dataset.

Talks to the agent service's /api/v1/evals endpoints (like ``forge trace``).
Uses only the stdlib for HTTP so the CLI stays dependency-light.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from kbws_forge_cli.reports import write_json_report, write_junit_report

DEFAULT_API_URL = "http://127.0.0.1:8000/api/v1"
_BUILTIN_GRADER_NAMES = {"exact", "contains", "regex", "json_schema", "tool_trajectory"}

console = Console()
eval_app = typer.Typer(help="Evaluate agents, compare runs, manage datasets.", no_args_is_help=True)


def api_client(api_url: str, api_key: str):
    """Minimal JSON HTTP client for the service API (data payload returned)."""
    base = api_url.rstrip("/")

    def _request(method: str, path: str, body: dict | None = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(base + path, data=data, method=method)
        if body is not None:
            request.add_header("Content-Type", "application/json")
        if api_key:
            request.add_header("X-API-Key", api_key)
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                payload = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = json.loads(exc.read()).get("info", "")
            except (json.JSONDecodeError, AttributeError):
                pass
            console.print(f"[bold red]API {exc.code}:[/bold red] {detail or exc.reason}")
            raise typer.Exit(1) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            console.print(f"[bold red]API unreachable:[/bold red] {exc}")
            raise typer.Exit(1) from exc
        return payload.get("data")

    return type("Client", (), {"get": lambda _, p: _request("GET", p), "post": lambda _, p, b=None: _request("POST", p, b)})()


def _print_run(run: dict[str, Any]) -> None:
    totals = run.get("totals", {})
    table = Table(title=None, show_header=False, box=None, padding=(0, 2))
    table.add_column("status", style="bold")
    table.add_column("case")
    table.add_column("score", justify="right")
    table.add_column("reason", style="dim", overflow="fold")
    for case in run.get("cases", []):
        status = case.get("status", "?")
        style = {"passed": "green", "failed": "red", "not_evaluated": "yellow"}.get(status, "white")
        reason = "; ".join(case.get("failure_reasons") or [])
        table.add_row(f"[{style}]{status}[/]", case.get("case_id", ""), _fmt_score(case.get("score")), reason)
    console.print(table)
    avg = run.get("average_score")
    console.print(
        f"suite [bold]{run.get('suite_id')}[/] · run {run.get('eval_run_id', '')[:8]} · "
        f"mode={run.get('provenance', {}).get('mode', '?')} · "
        f"[bold]{totals.get('passed', 0)}/{totals.get('total', 0)}[/] passed · "
        f"avg [bold]{'–' if avg is None else f'{avg:.2f}'}[/]"
    )


def _fmt_score(score) -> str:
    return "–" if score is None else f"{score:.2f}"


@eval_app.command("run")
def eval_run(
    suite_id: str = typer.Argument(..., help="Eval suite id registered on the service"),
    api_url: str = typer.Option(DEFAULT_API_URL, "--api-url", help="Service API base URL"),
    api_key: str = typer.Option("", "--api-key", envvar="FORGE_API_KEY", help="Service API key (optional when auth is off)"),
    mode: str = typer.Option("live", "--mode", help="live (calls the model) or replay (re-grades recorded runs)"),
    cases: str = typer.Option(None, "--cases", help="Comma-separated case ids to run"),
    repetitions: int = typer.Option(None, "--repetitions", min=1, help="Override suite repetitions"),
    fail_under: float = typer.Option(None, "--fail-under", min=0.0, max=1.0, help="CI gate: exit 1 when average score is below this"),
    report: list[str] = typer.Option([], "--report", help="Report formats: json and/or junit (repeatable)"),  # noqa: B008
    output: Path = typer.Option(Path("."), "-o", "--output", help="Report output directory"),  # noqa: B008
) -> None:
    """Run an eval suite on the service and print scores."""
    if mode not in {"live", "replay"}:
        console.print(f"[bold red]unknown mode:[/bold red] {mode} (use live or replay)")
        raise typer.Exit(1)
    client = api_client(api_url, api_key)
    body: dict[str, Any] = {"mode": mode}
    if cases:
        body["case_ids"] = [part.strip() for part in cases.split(",") if part.strip()]
    if repetitions:
        body["repetitions"] = repetitions
    run = client.post(f"/evals/{suite_id}/run", body)
    _print_run(run)

    for fmt in report:
        output.mkdir(parents=True, exist_ok=True)
        base = output / f"{suite_id}-{run['eval_run_id'][:8]}"
        if fmt == "json":
            write_json_report(run, base.with_suffix(".json"))
            console.print(f"wrote {base.with_suffix('.json')}")
        elif fmt == "junit":
            write_junit_report(run, base.with_suffix(".xml"))
            console.print(f"wrote {base.with_suffix('.xml')}")
        else:
            console.print(f"[yellow]unknown report format: {fmt} (use json or junit)[/]")

    if fail_under is not None:
        score = run.get("average_score")
        if score is None or score < fail_under:
            console.print(
                f"[bold red]GATE FAILED:[/bold red] average score {_fmt_score(score)} < {fail_under:.2f}"
            )
            raise typer.Exit(1)
        console.print(f"[green]gate passed:[/green] average score {score:.2f} >= {fail_under:.2f}")


@eval_app.command("compare")
def eval_compare(
    baseline: str = typer.Option(..., "--baseline", help="Baseline eval run id"),
    candidate: str = typer.Option(None, "--candidate", help="Candidate eval run id (default: none)"),
    live: bool = typer.Option(False, "--live", help="Run the baseline's suite live as the candidate"),
    api_url: str = typer.Option(DEFAULT_API_URL, "--api-url"),
    api_key: str = typer.Option("", "--api-key", envvar="FORGE_API_KEY"),
    fail_under: float = typer.Option(None, "--fail-under", min=0.0, max=1.0),
) -> None:
    """Compare two eval runs per case; exits 1 on regressions (or below --fail-under)."""
    client = api_client(api_url, api_key)
    base = client.get(f"/evals/runs/{baseline}")
    if base is None:
        console.print(f"[bold red]baseline run not found:[/bold red] {baseline}")
        raise typer.Exit(1)
    if live:
        candidate_run = client.post(f"/evals/{base['suite_id']}/run", {"mode": "live"})
        label = f"live:{base['suite_id']}"
    else:
        if not candidate:
            console.print("[bold red]need --candidate <id> or --live[/bold red]")
            raise typer.Exit(1)
        candidate_run = client.get(f"/evals/runs/{candidate}")
        if candidate_run is None:
            console.print(f"[bold red]candidate run not found:[/bold red] {candidate}")
            raise typer.Exit(1)
        label = candidate

    base_cases = {case["case_id"]: case for case in base["cases"]}
    cand_cases = {case["case_id"]: case for case in candidate_run["cases"]}

    table = Table(title=None, show_header=True, box=None, padding=(0, 2))
    table.add_column("case")
    table.add_column("baseline", justify="right")
    table.add_column("candidate", justify="right")
    table.add_column("delta", justify="right")
    regressions: list[str] = []
    improvements: list[str] = []
    for case_id, b in base_cases.items():
        c = cand_cases.get(case_id)
        if c is None:
            continue
        b_status = b.get("status")
        c_status = c.get("status")
        if b_status == "passed" and c_status != "passed":
            regressions.append(case_id)
        elif b_status != "passed" and c_status == "passed":
            improvements.append(case_id)
        b_score = b.get("score")
        c_score = c.get("score")
        delta = None if (b_score is None or c_score is None) else c_score - b_score
        table.add_row(
            case_id,
            _fmt_score(b_score),
            _fmt_score(c_score),
            _fmt_score(delta) if delta is not None else "–",
        )
    console.print(f"baseline {baseline[:8]} · candidate {label}")
    console.print(table)
    if regressions:
        console.print(f"[bold red]regressions:[/bold red] {', '.join(regressions)}")
    if improvements:
        console.print(f"[bold green]improvements:[/bold green] {', '.join(improvements)}")
    if not regressions and not improvements:
        console.print("[dim]no per-case status changes[/]")

    failed_gate = False
    if fail_under is not None:
        score = candidate_run.get("average_score")
        if score is None or score < fail_under:
            failed_gate = True
            console.print(f"[bold red]GATE FAILED:[/bold red] candidate avg {_fmt_score(score)} < {fail_under:.2f}")
    if regressions or failed_gate:
        raise typer.Exit(1)


dataset_app = typer.Typer(help="Export/import eval case datasets (JSONL).", no_args_is_help=True)
eval_app.add_typer(dataset_app, name="dataset")


@dataset_app.command("export")
def dataset_export(
    suite_id: str = typer.Argument(..., help="Suite id to export"),
    output: Path = typer.Option(..., "-o", "--output", help="Output .jsonl file"),  # noqa: B008
    api_url: str = typer.Option(DEFAULT_API_URL, "--api-url"),
    api_key: str = typer.Option("", "--api-key", envvar="FORGE_API_KEY"),
) -> None:
    """Export a suite's cases to JSONL (grader names, one case per line)."""
    client = api_client(api_url, api_key)
    suite = client.get(f"/evals/{suite_id}")
    if suite is None:
        console.print(f"[bold red]suite not found:[/bold red] {suite_id}")
        raise typer.Exit(1)
    rows = [
        json.dumps(case, ensure_ascii=False, sort_keys=True)
        for case in suite.get("cases", [])
    ]
    output.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")
    console.print(f"exported [bold]{len(rows)}[/bold] cases to {output}")


@dataset_app.command("import")
def dataset_import(
    file: Path = typer.Argument(..., help="Input .jsonl file"),  # noqa: B008
    name: str = typer.Option(..., "--name", help="New suite id"),
    agent: str = typer.Option(..., "--agent", help="agent_id the suite targets"),
    output: Path = typer.Option(Path("evals"), "-o", "--output", help="evals/ directory to write into"),  # noqa: B008
) -> None:
    """Generate a code-first EvalSuite module from a JSONL dataset."""
    rows = _read_jsonl(file)
    cases: list[str] = []
    grader_names: set[str] = set()
    for line_number, row in enumerate(rows, start=1):
        case_id = row.get("id")
        if not isinstance(case_id, str) or not case_id:
            console.print(f"[bold red]line {line_number}: missing string `id`[/bold red]")
            raise typer.Exit(1)
        conversation = row.get("conversation")
        raw_input = row.get("input")
        if conversation is not None:
            if not isinstance(conversation, list) or not conversation:
                console.print(f"[bold red]line {line_number}: invalid conversation[/bold red]")
            raise typer.Exit(1)
            input_literal = (
                "conversation=(\n"
                + ",\n".join(f"                    ChatMessage.user({json.dumps(m.get('text', ''))})" for m in conversation)
                + ",\n                )"
            )
        elif isinstance(raw_input, dict):
            input_literal = f"input=ChatMessage.model_validate({json.dumps(raw_input, ensure_ascii=False)})"
        else:
            input_literal = f"input={json.dumps(str(raw_input or ''), ensure_ascii=False)}"
        graders = row.get("graders", [])
        if not isinstance(graders, list):
            console.print(f"[bold red]line {line_number}: invalid graders[/bold red]")
            raise typer.Exit(1)
        unknown = [g for g in graders if g not in _BUILTIN_GRADER_NAMES]
        if unknown:
            console.print(
                f"[bold red]line {line_number}: unknown grader(s) {unknown}; "
                f"builtin: {sorted(_BUILTIN_GRADER_NAMES)}[/bold red]"
            )
            raise typer.Exit(1)
        grader_names.update(graders)
        grader_literal = ", ".join(f"_GRADERS[{json.dumps(g)}]()" for g in graders) or "exact()"
        expected = row.get("expected")
        expected_literal = f"expected={json.dumps(expected, ensure_ascii=False)}" if expected is not None else ""
        parts = [f'id={json.dumps(case_id)}', input_literal, expected_literal, f"graders=({grader_literal},)"]
        cases.append("            EvalCase(\n" + ",\n".join(f"                {part}" for part in parts if part) + ",\n            )")

    module = _render_module(name, agent, cases, grader_names, file)
    output.mkdir(parents=True, exist_ok=True)
    target = output / f"{name}.py"
    target.write_text(module, encoding="utf-8")
    console.print(f"generated [bold]{target}[/bold] with {len(cases)} cases")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        (line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()),
        start=1,
    ):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            console.print(f"[bold red]line {line_number}: invalid JSON: {exc}[/bold red]")
            raise typer.Exit(1) from exc
        rows.append(row)
    return rows


def _render_module(
    name: str, agent: str, cases: list[str], grader_names: set[str], source: Path
) -> str:
    imports = "\n".join(
        f"from kbws_forge_runtime import {g}" for g in sorted(grader_names)
    )
    header = (
        f'"""Eval suite generated from dataset {source}."""\n\n'
        f"from kbws_forge_runtime import EvalCase, EvalSuite, RunPolicy\n"
        f"{imports}\n\n"
        f"_GRADERS = {{\n"
        + ",\n".join(f'    {g!r}: {g}' for g in sorted(grader_names))
        + "\n}\n"
    )
    body = (
        f"\nsuite = EvalSuite(\n"
        f"    id={name!r},\n"
        f"    name={name!r},\n"
        f"    agent_id={agent!r},\n"
        f"    policy=RunPolicy(max_concurrency=2, timeout_seconds=60, max_total_tokens=20000),\n"
        f"    cases=(\n"
        + ",\n".join(cases)
        + ",\n    ),\n)\n"
    )
    return header + body


__all__ = ["api_client", "eval_app"]
