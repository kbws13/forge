
from typer.testing import CliRunner

from kbws_forge_cli.cli import app

runner = CliRunner()


def test_version_matches_package_release() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == "forge 1.2.2"


def _invoke_in(tmp_path, monkeypatch, *args):
    monkeypatch.chdir(tmp_path)
    return runner.invoke(app, list(args))


def test_init_default_template_is_service_agent(tmp_path, monkeypatch) -> None:
    """默认模板应生成完整分层服务（service-agent）。"""
    result = _invoke_in(tmp_path, monkeypatch, "init", "my-agent")
    assert result.exit_code == 0, result.output
    assert "service-agent" in result.output

    proj = tmp_path / "my-agent"
    assert (proj / "pyproject.toml").is_file()
    assert (proj / "app" / "main.py").is_file()
    assert (proj / "app" / "core").is_dir()
    assert (proj / "agents").is_dir()
    assert (proj / ".env.example").is_file()

    from kbws_forge_cli.generator import RUNTIME_MIN_VERSION

    pyproject = (proj / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "my-agent"' in pyproject
    assert f"kbws-forge-runtime[openai]>={RUNTIME_MIN_VERSION}" in pyproject
    assert "forge trace" in (proj / "README.md").read_text(encoding="utf-8")


def test_init_base_agent_template_creates_hello_world(tmp_path, monkeypatch) -> None:
    """显式 -t base-agent 仍生成最小 FastAPI HelloWorld。"""
    result = _invoke_in(tmp_path, monkeypatch, "init", "my-agent", "-t", "base-agent")
    assert result.exit_code == 0, result.output

    proj = tmp_path / "my-agent"
    assert (proj / "main.py").is_file()
    main = (proj / "main.py").read_text(encoding="utf-8")
    assert "FastAPI" in main
    assert "Hello World" in main

    pyproject = (proj / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "my-agent"' in pyproject
    assert "fastapi" in pyproject


def test_init_renders_name_into_template(tmp_path, monkeypatch) -> None:
    result = _invoke_in(tmp_path, monkeypatch, "init", "my-agent")
    assert result.exit_code == 0, result.output
    main = (tmp_path / "my-agent" / "app" / "main.py").read_text(encoding="utf-8")
    assert 'title="my-agent Agent Service"' in main


def test_init_rejects_invalid_name(tmp_path, monkeypatch) -> None:
    result = _invoke_in(tmp_path, monkeypatch, "init", "bad name!")
    assert result.exit_code == 1
    assert "Invalid project name" in result.output


def test_init_rejects_unknown_template(tmp_path, monkeypatch) -> None:
    result = _invoke_in(tmp_path, monkeypatch, "init", "demo", "--template", "nope")
    assert result.exit_code == 1
    assert "Unknown template" in result.output


def test_interactive_prompts_when_args_omitted(tmp_path, monkeypatch) -> None:
    """交互模式：缺参数时询问项目名和模板（Vite 风格）。"""
    monkeypatch.setattr("kbws_forge_cli.cli._is_interactive", lambda: True)
    monkeypatch.setattr("kbws_forge_cli.cli._prompt_name", lambda: "interactive-agent")
    monkeypatch.setattr("kbws_forge_cli.cli._prompt_template", lambda: "service-agent")

    result = _invoke_in(tmp_path, monkeypatch, "init")
    assert result.exit_code == 0, result.output
    assert (tmp_path / "interactive-agent" / "app" / "main.py").is_file()
    assert "service-agent" in result.output


def test_non_interactive_without_name_fails(tmp_path, monkeypatch) -> None:
    """非交互（CI/管道）且缺项目名：明确报错而不是挂起。"""
    monkeypatch.setattr("kbws_forge_cli.cli._is_interactive", lambda: False)
    result = _invoke_in(tmp_path, monkeypatch, "init")
    assert result.exit_code != 0
    assert "project name is required" in result.output


def test_templates_discovered_dynamically() -> None:
    from kbws_forge_cli.cli import _available_templates

    templates = _available_templates()
    assert "service-agent" in templates
    assert "base-agent" in templates


def test_init_refuses_non_empty_existing_dir(tmp_path, monkeypatch) -> None:
    existing = tmp_path / "my-agent"
    existing.mkdir()
    (existing / "keep.txt").write_text("x", encoding="utf-8")
    result = _invoke_in(tmp_path, monkeypatch, "init", "my-agent")
    assert result.exit_code == 1
    assert "--force" in result.output


def test_init_force_overwrites(tmp_path, monkeypatch) -> None:
    existing = tmp_path / "my-agent"
    existing.mkdir()
    (existing / "old.txt").write_text("x", encoding="utf-8")
    result = _invoke_in(tmp_path, monkeypatch, "init", "my-agent", "--force")
    assert result.exit_code == 0, result.output
    assert (tmp_path / "my-agent" / "app" / "main.py").is_file()


def test_trace_command_serves_loopback_ui_without_opening_browser(monkeypatch) -> None:
    class FakeServer:
        server_port = 9876
        api_url = "http://127.0.0.1:9000/api/v1"
        served = False
        closed = False

        def serve_forever(self) -> None:
            self.served = True

        def server_close(self) -> None:
            self.closed = True

    server = FakeServer()
    opened: list[str] = []
    monkeypatch.setattr("kbws_forge_cli.cli.create_trace_server", lambda **_: server)
    monkeypatch.setattr("kbws_forge_cli.cli.webbrowser.open", opened.append)

    result = runner.invoke(
        app,
        ["trace", "--api-url", server.api_url, "--port", "9876", "--no-open"],
    )

    assert result.exit_code == 0, result.output
    assert "http://127.0.0.1:9876/" in result.output
    assert server.api_url in result.output
    assert server.served is True
    assert server.closed is True
    assert opened == []


def test_trace_command_rejects_invalid_api_url() -> None:
    result = runner.invoke(app, ["trace", "--api-url", "file:///tmp/agent"])

    assert result.exit_code == 1
    assert "absolute http:// or https:// URL" in result.output


def test_runtime_min_version_tracks_local_runtime() -> None:
    """CLI 声明的 runtime 最低版本必须 <= 工作区 runtime 的实际版本（防忘记同步）。"""
    import re
    from pathlib import Path

    from kbws_forge_cli.generator import RUNTIME_MIN_VERSION

    runtime_pyproject = (
        Path(__file__).resolve().parents[2] / "forge-runtime" / "pyproject.toml"
    )
    match = re.search(
        r'^version = "([^"]+)"', runtime_pyproject.read_text(encoding="utf-8"), re.MULTILINE
    )
    assert match, "forge-runtime pyproject missing version"
    local_version = match.group(1)
    assert _version_tuple(RUNTIME_MIN_VERSION) <= _version_tuple(local_version), (
        f"RUNTIME_MIN_VERSION {RUNTIME_MIN_VERSION} exceeds local runtime {local_version}; "
        "bump RUNTIME_MIN_VERSION only after the runtime release"
    )


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))
