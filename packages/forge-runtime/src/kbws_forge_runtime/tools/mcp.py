from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

from langchain_core.tools import BaseTool

from kbws_forge_runtime.errors import McpConfigError


@dataclass(frozen=True, slots=True)
class StdioMcpServer:
    name: str
    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SseMcpServer:
    name: str
    url: str


McpServer = StdioMcpServer | SseMcpServer


class McpToolLoader:
    def __init__(self, servers: list[McpServer]) -> None:
        self._servers = servers

    def adapter_config(self) -> dict[str, dict[str, object]]:
        result: dict[str, dict[str, object]] = {}
        for server in self._servers:
            if isinstance(server, StdioMcpServer):
                result[server.name] = {
                    "transport": "stdio",
                    "command": server.command,
                    "args": list(server.args),
                    "env": server.env,
                }
            elif isinstance(server, SseMcpServer):
                result[server.name] = {"transport": "sse", "url": server.url}
            else:
                raise McpConfigError(f"unsupported MCP config: {server!r}")
        return result

    async def load(self) -> list[BaseTool]:
        try:
            from langchain_mcp_adapters.client import MultiServerMCPClient
        except ImportError as exc:
            raise McpConfigError(
                "MCP support is not installed; install kbws-forge-runtime-demo[mcp]"
            ) from exc

        # 配置字典与 langchain_mcp_adapters 的 Connection 结构一致，但它是可选依赖，
        # 不能在此处静态引用其类型，故 cast 为 Any 绕过。
        client = MultiServerMCPClient(cast(Any, self.adapter_config()))
        return list(await client.get_tools())
