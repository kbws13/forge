import asyncio
import socket
import sys
from pathlib import Path

import pytest
import uvicorn
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from mcp.server.fastmcp import FastMCP

from kbws_forge_runtime import (
    AgentInfo,
    AgentRuntime,
    RunFinished,
    ToolStarted,
)
from kbws_forge_runtime.tools import McpToolLoader, SseMcpServer, StdioMcpServer
from kbws_forge_runtime.workflow import build_chat_graph

pytestmark = pytest.mark.real_provider


async def test_real_provider_calls_stdio_and_sse_mcp_tools(
    real_model: ChatOpenAI,
) -> None:
    mcp_server = FastMCP("sse-test-tools")

    @mcp_server.tool()
    def multiply(left: int, right: int) -> int:
        """Multiply two integers."""
        return left * right

    server_socket = socket.socket()
    server_socket.bind(("127.0.0.1", 0))
    server_socket.listen(128)
    port = server_socket.getsockname()[1]
    web_server = uvicorn.Server(
        uvicorn.Config(mcp_server.sse_app(), log_level="warning", lifespan="off")
    )
    server_task = asyncio.create_task(web_server.serve(sockets=[server_socket]))
    while not web_server.started:
        if server_task.done():
            await server_task
        await asyncio.sleep(0.01)

    try:
        server_path = Path(__file__).parents[1] / "fixtures" / "mcp_server.py"
        tools = await McpToolLoader(
            [
                StdioMcpServer(
                    name="stdio-test",
                    command=sys.executable,
                    args=(str(server_path),),
                ),
                SseMcpServer(name="sse-test", url=f"http://127.0.0.1:{port}/sse"),
            ]
        ).load()
        assert {item.name for item in tools} == {"add", "multiply"}

        runtime = AgentRuntime(plugins=[])
        runtime.register_agent(
            AgentInfo(agent_id="mcp", name="MCP"),
            build_chat_graph(
                real_model,
                instruction=(
                    "You must call both tools. Call add with left=2 and right=3. "
                    "Call multiply with left=2 and right=4. Do not do arithmetic yourself. "
                    "After both tools return, reply exactly: ADD=5; MULTIPLY=8"
                ),
                tools=tools,
                checkpointer=InMemorySaver(),
            ),
        )
        events = [event async for event in runtime.chat_stream("mcp", "user-1", "Run now.")]
    finally:
        web_server.should_exit = True
        await asyncio.wait_for(server_task, timeout=5)
        server_socket.close()

    started_tools = {
        event.tool_name for event in events if isinstance(event, ToolStarted)
    }
    assert started_tools == {"add", "multiply"}
    assert isinstance(events[-1], RunFinished)
    assert "ADD=5" in events[-1].message.text
    assert "MULTIPLY=8" in events[-1].message.text
