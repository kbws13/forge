"""Forge CLI entry point."""

from __future__ import annotations

from pathlib import Path

import typer
from pydantic import ValidationError
from rich.console import Console

from kbws_forge_cli.generator import Generator, ProjectSpec

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
    name: str = typer.Argument(..., help="Name of the agent project, e.g. my-agent."),
    template: str = typer.Option(
        "service-agent",
        "--template",
        "-t",
        help="Template to use (service-agent | base-agent | cloudtest-agent).",
    ),
    force: bool = typer.Option(
        False, "--force", help="Overwrite the target directory if it already exists."
    ),
) -> None:
    """Scaffold a new agent project in the current directory."""
    console = Console()

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
    console.print("  uv run fastapi dev")


if __name__ == "__main__":
    app()
