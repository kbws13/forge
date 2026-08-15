from __future__ import annotations

from importlib import resources
from pathlib import Path, PurePosixPath
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool


class SkillLoader:
    def __init__(self):
        self._roots: list[Any] = []

    def add_directory(self, path: str | Path) -> None:
        root = Path(path).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"skill directory does not exist: {root}")
        self._roots.append(root)

    def add_package(self, package: str, resource: str) -> None:
        root = resources.files(package).joinpath(resource)
        if not root.is_dir():
            raise ValueError(f"skill package resource does not exist: {package}:{resource}")
        self._roots.append(root)

    def _skills(self) -> dict[str, Any]:
        found: dict[str, Any] = {}
        for root in self._roots:
            if root.joinpath("SKILL.md").is_file():
                found[root.name] = root
            for child in root.iterdir():
                if child.is_dir() and child.joinpath("SKILL.md").is_file():
                    found[child.name] = child
        return found

    def list_skills(self) -> list[str]:
        return sorted(self._skills())

    def read_file(self, skill_name: str, relative_path: str = "SKILL.md") -> str:
        path = PurePosixPath(relative_path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("skill file must stay inside its skill directory")
        try:
            skill_root = self._skills()[skill_name]
        except KeyError as exc:
            raise ValueError(f"skill does not exist: {skill_name}") from exc
        target = skill_root.joinpath(*path.parts)
        if not target.is_file():
            raise ValueError(f"skill file does not exist: {skill_name}/{relative_path}")
        return target.read_text(encoding="utf-8")

    def as_tool(self) -> list[BaseTool]:
        return [
            StructuredTool.from_function(
                self.list_skills, name="list_skills", description="List the available skills."
            ),
            StructuredTool.from_function(
                self.read_file,
                name="read_skill_file",
                description="Read SKILL.md or another file form one available skill.",
            ),
        ]
