"""Project scaffolding logic: Pydantic spec + Jinja2 templates."""

from __future__ import annotations

import re
from pathlib import Path

import jinja2
from pydantic import BaseModel, field_validator

TEMPLATES_ROOT = Path(__file__).resolve().parent / "templates"

_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")


class ProjectSpec(BaseModel):
    """Validated settings used to render a project template."""

    name: str
    template: str = "base-agent"

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        value = value.strip()
        if not _NAME_RE.fullmatch(value):
            raise ValueError(
                "must start with a letter or digit and contain only letters, "
                "digits, '-' or '_'"
            )
        return value

    @property
    def module_name(self) -> str:
        """Python-friendly name (hyphens become underscores)."""
        return self.name.replace("-", "_")


class Generator:
    """Renders the files of one template into a target directory."""

    def __init__(self, spec: ProjectSpec) -> None:
        self.spec = spec
        self.template_root = TEMPLATES_ROOT / spec.template
        if not self.template_root.is_dir():
            raise ValueError(f"Unknown template: {spec.template!r}")
        self.env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(self.template_root),
            keep_trailing_newline=True,
        )

    def generate(self, target: Path) -> list[Path]:
        target.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for src in sorted(self.template_root.rglob("*")):
            if not src.is_file():
                continue
            if src.name.endswith((".pyc", ".pyo", "~")) or src.name in {
                ".DS_Store",
                "__pycache__",
            }:
                continue
            rel = src.relative_to(self.template_root)
            dest_name = rel.name[:-3] if rel.name.endswith(".j2") else rel.name
            dest = target / rel.parent / dest_name
            rendered = self.env.get_template(rel.as_posix()).render(spec=self.spec)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(rendered, encoding="utf-8")
            written.append(dest)
        return written
