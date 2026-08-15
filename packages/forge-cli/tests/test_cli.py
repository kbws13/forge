from pathlib import Path

from typer.testing import CliRunner

from kbws_forge_cli.cli import app

runner = CliRunner()


def _invoke_in(tmp_path, monkeypatch, *args):
    monkeypatch.chdir(tmp_path)
    return runner.invoke(app, list(args))


def test_init_creates_hello_world_project(tmp_path, monkeypatch) -> None:
    result = _invoke_in(tmp_path, monkeypatch, "init", "my-agent")
    assert result.exit_code == 0, result.output

    proj = tmp_path / "my-agent"
    assert proj.is_dir()
    assert (proj / "pyproject.toml").is_file()
    assert (proj / "main.py").is_file()
    assert (proj / ".gitignore").is_file()

    pyproject = (proj / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "my-agent"' in pyproject
    assert "fastapi" in pyproject

    main = (proj / "main.py").read_text(encoding="utf-8")
    assert "FastAPI" in main
    assert "Hello World" in main

    readme = (proj / "README.md").read_text(encoding="utf-8")
    assert "uv run fastapi dev" in readme


def test_init_renders_name_into_template(tmp_path, monkeypatch) -> None:
    result = _invoke_in(tmp_path, monkeypatch, "init", "my-agent")
    assert result.exit_code == 0, result.output
    main = (tmp_path / "my-agent" / "main.py").read_text(encoding="utf-8")
    assert 'title="my-agent"' in main


def test_init_rejects_invalid_name(tmp_path, monkeypatch) -> None:
    result = _invoke_in(tmp_path, monkeypatch, "init", "bad name!")
    assert result.exit_code == 1
    assert "Invalid project name" in result.output


def test_init_rejects_unknown_template(tmp_path, monkeypatch) -> None:
    result = _invoke_in(tmp_path, monkeypatch, "init", "demo", "--template", "nope")
    assert result.exit_code == 1
    assert "Unknown template" in result.output


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
    assert (tmp_path / "my-agent" / "main.py").is_file()
