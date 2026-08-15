from pathlib import Path

import pytest

from kbws_forge_runtime.tools import (
    McpToolLoader,
    SkillLoader,
    SseMcpServer,
    StdioMcpServer,
    ToolBox,
    tool,
)


@tool
def upper(word: str) -> str:
    """Convert one word to uppercase."""
    return word.upper()


def test_toolbox_collects_local_tools() -> None:
    toolbox = ToolBox([upper])
    assert [item.name for item in toolbox.tools] == ["upper"]
    with pytest.raises(ValueError, match="already exists"):
        toolbox.add(upper)


def test_mcp_loader_builds_stdio_and_sse_config() -> None:
    loader = McpToolLoader(
        [
            StdioMcpServer(name="local", command="python", args=("server.py",)),
            SseMcpServer(name="remote", url="https://example.com/sse"),
        ]
    )
    assert loader.adapter_config()["local"]["transport"] == "stdio"
    assert loader.adapter_config()["remote"] == {
        "transport": "sse",
        "url": "https://example.com/sse",
    }


def test_skill_loader_reads_skill_files(tmp_path: Path) -> None:
    skill_dir = tmp_path / "skills" / "writer"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# Writer", encoding="utf-8")
    (skill_dir / "reference.md").write_text("reference", encoding="utf-8")
    loader = SkillLoader()
    loader.add_directory(tmp_path / "skills")
    assert loader.list_skills() == ["writer"]
    assert loader.read_file("writer") == "# Writer"
    assert loader.read_file("writer", "reference.md") == "reference"
    with pytest.raises(ValueError, match="stay inside"):
        loader.read_file("writer", "../secret")


def test_skill_loader_reads_package_resources() -> None:
    loader = SkillLoader()
    loader.add_package("tests.fixtures.java_parity_agent", "skills")

    assert loader.list_skills() == ["project-planning"]
    assert loader.read_file("project-planning").startswith("# Project Planning")
