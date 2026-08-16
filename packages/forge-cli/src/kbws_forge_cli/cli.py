"""Forge CLI entry point."""

from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

import questionary
import typer
from pydantic import ValidationError
from rich.console import Console

from kbws_forge_cli.generator import Generator, ProjectSpec
from kbws_forge_cli.trace_server import (
    DEFAULT_API_URL,
    DEFAULT_TRACE_PORT,
    TRACE_HOST,
    create_trace_server,
)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
DEFAULT_TEMPLATE = "service-agent"


def _available_templates() -> list[str]:
    """动态扫描模板目录，新增模板自动出现在选择列表里。"""
    return sorted(
        d.name for d in TEMPLATES_DIR.iterdir() if d.is_dir() and not d.name.startswith(".")
    )


def _is_interactive() -> bool:
    return sys.stdin.isatty()


def _prompt_name() -> str:
    return questionary.text(
        "Project name",
        default="my-agent",
        validate=lambda value: bool(value.strip()) or "project name cannot be empty",
    ).ask()


def _prompt_template() -> str:
    choices = _available_templates()
    selected = questionary.select(
        "Select a template",
        choices=choices,
        default=DEFAULT_TEMPLATE,
    ).ask()
    return selected or DEFAULT_TEMPLATE


def _resolve_name(name: str | None) -> str:
    if name is not None:
        return name
    if not _is_interactive():
        raise typer.BadParameter("project name is required in non-interactive mode")
    return _prompt_name()


def _resolve_template(template: str | None) -> str:
    if template is not None:
        return template
    if not _is_interactive():
        return DEFAULT_TEMPLATE
    return _prompt_template()


app = typer.Typer(
    name="forge",
    help="Forge CLI - coding agent scaffolding generator.",
    no_args_is_help=True,
    add_completion=False,
    invoke_without_command=True,
)


@app.callback()
def main(
    version: bool = typer.Option(False, "--version", help="Show version and exit."),
) -> None:
    """Forge CLI - coding agent scaffolding generator."""
    if version:
        from kbws_forge_cli import __version__

        typer.echo(f"forge {__version__}")
        raise typer.Exit()


@app.command("init")
def init_command(
    name: str | None = typer.Argument(
        None, help="Name of the agent project, e.g. my-agent. Omit for interactive input."
    ),
    template: str | None = typer.Option(
        None,
        "--template",
        "-t",
        help=f"Template to use. Defaults to {DEFAULT_TEMPLATE} when omitted.",
    ),
    force: bool = typer.Option(
        False, "--force", help="Overwrite the target directory if it already exists."
    ),
) -> None:
    """Scaffold a new agent project.

    Interactive prompts (Vite-style) when arguments are omitted; fully
    non-interactive when name/template are provided or stdin is not a TTY.
    """
    console = Console()

    name = _resolve_name(name)
    template = _resolve_template(template)

    try:
        spec = ProjectSpec(name=name, template=template)
    except ValidationError as exc:
        console.print("[bold red]Invalid project name:[/bold red]")
        for err in exc.errors():
            console.print(f"  - {err['msg']}")
        raise typer.Exit(1) from exc

    target = Path.cwd() / spec.name
    if target.exists() and any(target.iterdir()) and not force:
        console.print(
            f"[bold red]Directory [cyan]{spec.name}[/cyan] already exists and is not empty.[/bold red]\n"
            f"Use [bold]--force[/bold] to overwrite it."
        )
        raise typer.Exit(1)

    try:
        generator = Generator(spec)
        written = generator.generate(target)
    except ValueError as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(1) from exc

    console.print(
        f"[bold green]OK[/bold green] Project [bold cyan]{spec.name}[/bold cyan] "
        f"created from template [bold]{spec.template}[/bold].\n"
    )
    console.print("[bold]Files:[/bold]")
    for file in written:
        console.print(f"  [dim]{file.relative_to(target.parent)}[/dim]")
    console.print("\n[bold]Next steps:[/bold]")
    console.print(f"  cd {spec.name}")
    console.print("  uv sync")
    console.print("  uv run uvicorn app.main:app --reload")


@app.command("trace")
def trace_command(
    api_url: str = typer.Option(
        DEFAULT_API_URL,
        "--api-url",
        help="Forge service API base URL.",
    ),
    port: int = typer.Option(
        DEFAULT_TRACE_PORT,
        "--port",
        min=1,
        max=65535,
        help="Local port for the Trace UI.",
    ),
    open_browser: bool = typer.Option(
        True,
        "--open/--no-open",
        help="Open the Trace UI in the default browser.",
    ),
) -> None:
    """Inspect Forge agent runs in a local browser UI."""
    console = Console()
    try:
        server = create_trace_server(api_url=api_url, port=port)
    except (OSError, ValueError) as exc:
        console.print(f"[bold red]Could not start Forge Trace:[/bold red] {exc}")
        raise typer.Exit(1) from exc

    ui_url = f"http://{TRACE_HOST}:{server.server_port}/"
    console.print(f"Forge Trace: [bold cyan]{ui_url}[/bold cyan]")
    console.print(f"Agent API:   [cyan]{server.api_url}[/cyan]")
    console.print("Press Ctrl-C to stop.")

    if open_browser:
        webbrowser.open(ui_url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        console.print("\nForge Trace stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    app()
