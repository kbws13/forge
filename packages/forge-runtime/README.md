# kbws-forge-runtime

[![PyPI version](https://img.shields.io/pypi/v/kbws-forge-runtime)](https://pypi.org/project/kbws-forge-runtime/)
[![Python versions](https://img.shields.io/pypi/pyversions/kbws-forge-runtime)](https://pypi.org/project/kbws-forge-runtime/)
[![License](https://img.shields.io/pypi/l/kbws-forge-runtime)](https://pypi.org/project/kbws-forge-runtime/)

A framework-agnostic runtime for building coding agents in Python. It manages
agents, sessions and chat flows on top of [LangGraph](https://www.langchain.com/langgraph),
while keeping the core API clean, typed and free of web-framework coupling.

## Highlights

- **AgentRuntime** — register agents, create sessions, run blocking or streaming chats with plugin hooks
- **Composable prompts** — code-first prompt blocks (`Prompt`/`Message`/`compose`) with automatic session-history injection
- **Agent directory convention** — one agent = one directory (`agent.py` + `prompts.py` + `tools.py`), auto-discovered by `load_agents`
- **Workflow builders** — chat, sequence, parallel and loop graphs over a typed state
- **Tools** — local tools, MCP (stdio/SSE), and SKILL.md skill loading
- **Typed events** — a discriminated union of stream events, easy to serialize (e.g. to SSE)

## Install

```bash
pip install kbws-forge-runtime
# optional integrations
pip install "kbws-forge-runtime[mcp]"      # MCP tool loading
pip install "kbws-forge-runtime[openai]"   # OpenAI-compatible chat models
```

Requires Python ≥ 3.13.

## Quick start

```python
import asyncio

from langchain_openai import ChatOpenAI

from kbws_forge_runtime import AgentInfo, AgentRuntime
from kbws_forge_runtime.workflow import build_chat_graph


async def main() -> None:
    model = ChatOpenAI(model="deepseek-chat", api_key="sk-...")

    runtime = AgentRuntime()
    runtime.register_agent(
        AgentInfo(agent_id="assistant", name="Assistant"),
        build_chat_graph(model, instruction="You are a helpful assistant."),
    )

    # blocking chat — sessions and memory are handled for you
    result = await runtime.chat("assistant", "user-1", "Hello!")
    print(result.content)

    # streaming chat — typed events
    async for event in runtime.chat_stream("assistant", "user-1", "Tell me more"):
        print(event.type, event)


asyncio.run(main())
```

## Core API

### AgentRuntime

| Method | Description |
| --- | --- |
| `register_agent(info, graph)` | Register an agent (any object satisfying the `ChatGraph` protocol) |
| `list_agents()` | Registered agents as `AgentInfo` |
| `create_session(agent_id, user_id)` | Create a session; idempotent per (agent, user) |
| `get_session(session_id)` | Look up a session |
| `chat(agent_id, user_id, message, session_id=None, variables=None)` | Blocking chat, returns `ChatResult` |
| `chat_stream(...)` | Async iterator of `ChatEvent`s |
| `chat_parts(agent_id, user_id, parts, ...)` | Chat with structured content parts |

### Stream events

All events share `run_id` / `agent_id` / `session_id` and a discriminated `type`:

`run_started` · `message_created` · `text_delta` · `tool_started` · `tool_finished` · `run_finished` · `run_failed`

### Composable prompts

Prompts are plain Python objects — compose, partially apply, reuse:

```python
from kbws_forge_runtime.prompts import Message, Prompt, compose

persona = Prompt(name="persona", messages=[Message.system("You are a {role}.")])
task = Prompt(name="task", messages=[Message.human("Weekly data:\n{data}")])

weekly = compose(persona, task, name="weekly", extra_messages=[Message.history()])

# pass variables per call; history is injected at the placeholder automatically
result = await runtime.chat(
    "assistant", "user-1", "Write the report.",
    variables={"role": "engineering lead", "data": "...git stats..."},
)
```

`build_chat_graph` accepts a plain `str`, a composable `Prompt`, or any
langchain chat prompt template — so full flexibility (few-shot, example
selectors, …) is one import away.

### Agent directory convention

```python
from kbws_forge_runtime import AgentRuntime
from kbws_forge_runtime.agent import load_agents

runtime = AgentRuntime()
await load_agents("agents", runtime, model_factory=lambda: model)
```

Any directory under `agents/` containing an `agent.py` that exports an `agent`
object is registered automatically. Directories without one (e.g. `shared/`)
are skipped:

```
agents/
├── weekly-report/
│   ├── agent.py       # agent = Agent(agent_id=..., prompt=..., tools=...)
│   ├── prompts.py     # Prompt components
│   └── tools.py       # this agent's tools
└── shared/            # shared components, not loaded as an agent
```

An `Agent` aggregates its prompt, tools, MCP config and skills, and builds its
own graph:

```python
from kbws_forge_runtime.agent import Agent

agent = Agent(
    agent_id="weekly-report",
    name="Weekly Report",
    prompt=weekly,
    tools=[git_summary, jira_stats],
    mcp=[StdioMcpServer(name="jira", command="jira-mcp", args=[])],
)
```

### Workflow builders

`build_chat_graph(model, *, instruction, tools=(), checkpointer=None)` builds a
single chat agent (with a tool loop when tools are given). `build_sequence`,
`build_parallel` and `build_loop` compose multiple agents over a typed
`WorkflowState`. Memory is on by default (`InMemorySaver`) keyed by
`session_id`; pass your own langgraph saver to persist elsewhere.

### Tools, MCP & skills

```python
from kbws_forge_runtime.tools import McpToolLoader, SkillLoader, ToolBox, tool

@tool
def current_time() -> str:
    """Return the current UTC time in ISO 8601 format."""
    return datetime.now(UTC).isoformat()

tools = ToolBox([current_time])
tools.extend(await McpToolLoader([StdioMcpServer(name="db", command="mcp-db", args=[]) ]).load())
```

### Plugins

```python
from kbws_forge_runtime.plugins import LoggingPlugin, Plugin

runtime = AgentRuntime(plugins=[LoggingPlugin()])
```

`Plugin` hooks: `on_user_message` · `before_agent` · `on_event` · `after_agent` · `on_error`.

### Errors

Exceptions inherit `ForgeRuntimeError` and carry a stable `code`:

`E0001` agent not found · `0002` session not found · `0003` session ownership · `0004` illegal parameter · `0005` run error · `0006` MCP config

## Development

```bash
uv sync --all-extras
uv run pytest packages/forge-runtime/tests          # unit + API (fake models)
RUN_REAL_PROVIDER_TESTS=1 uv run pytest packages/forge-runtime/tests  # + real LLM calls
```

## License

MIT License
