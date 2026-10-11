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
- **Model middlewares** — deepagents-style hooks (`before_model`/`after_model`/`wrap_model_call`) around every model call
- **Structured output** — pass any pydantic schema, get parsed results in `ChatResult.parsed` / `RunFinished.parsed`
- **Agent directory convention** — one agent = one directory (`agent.py` + `prompts.py` + `tools.py`), auto-discovered by `load_agents`
- **Workflow builders** — chat, sequence, parallel and loop graphs over a typed state
- **Tools** — local tools, MCP (stdio/SSE), and SKILL.md skill loading
- **Execution policies** — enforce deadlines, cancellation, call/token/cost budgets, concurrency and tool permissions
- **Typed action events** — ordered model/tool/run events with timing and usage metadata, ready for SSE or a trace UI

## Install

```bash
pip install "kbws-forge-runtime>=2,<3"
# optional integrations
pip install "kbws-forge-runtime[mcp]>=2,<3"      # MCP tool loading
pip install "kbws-forge-runtime[openai]>=2,<3"   # OpenAI-compatible chat models
```

Requires Python ≥ 3.13.

Version 2 removes the Eval package and all Eval exports. Chat, tools, structured
output, execution controls and tracing remain the runtime's scope. CLI 2.0
generates services requiring runtime `>=2.0.0,<3`. See the
[migration guide](https://github.com/kbws13/forge/blob/main/docs/migration-v2.md)
before upgrading existing applications.

## Quick start

```python
import asyncio
import os

from langchain_openai import ChatOpenAI

from kbws_forge_runtime import AgentInfo, AgentRuntime
from kbws_forge_runtime.workflow import build_chat_graph


async def main() -> None:
    model = ChatOpenAI(
        model=os.environ["DEEPSEEK_MODEL"],
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        stream_usage=True,
    )

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
| `cancel(run_id, reason="run cancelled")` | Cancel an active run |
| `active_run_ids()` | IDs of runs active in this runtime process |

### Execution policies

Policies can be configured as the runtime default or supplied per call. Defaults
are unlimited, so existing applications keep their current behavior.

```python
from kbws_forge_runtime import AgentRuntime, RunPolicy, ToolPolicy

policy = RunPolicy(
    timeout_seconds=30,
    max_model_calls=6,
    max_tool_calls=10,
    max_total_tokens=20_000,
    max_concurrency=4,
    tool_policy=ToolPolicy(
        allowed_tools={"search", "read_file"},
        approval_required={"read_file"},
    ),
)

runtime = AgentRuntime(default_policy=policy, tool_approval_handler=approve_tool)
result = await runtime.chat("assistant", "user-1", "Investigate this issue.")
```

Model and tool retries are disabled by default. Tool retries additionally require
the tool name in `ToolPolicy.retryable_tools`, preventing accidental retries of
side-effecting operations. Token and cost budgets fail closed when the provider
does not expose the required usage metadata; pass `usage_resolver` to normalize a
provider-specific response.

Graphs created by `build_chat_graph` (including `Agent.build_graph`) route model
calls, tool calls and structured-output repair calls through `ModelExecutor` /
`ToolExecutor`. Custom `ChatGraph` implementations must use those executors
themselves when they need call budgets, retries or tool-policy enforcement;
runtime-level timeout and cancellation still apply to the whole graph.
`InMemoryEventSink` is available for tests and local trace viewers; implement
`EventSink.emit(event)` to export events elsewhere. Sink failures are logged and
isolated so observability outages cannot fail an agent run.

### Stream events

All events share `run_id` / `agent_id` / `session_id` and a discriminated `type`:

`run_started` · `message_created` · `model_started` · `text_delta` ·
`model_finished` · `model_failed` · `tool_started` · `tool_finished` ·
`tool_failed` · `run_finished` · `run_failed` · `run_cancelled`

Events also carry `event_id`, UTC `created_at` and a run-local `sequence`. Action
events include call/parent IDs and duration; terminal events include model/tool
call counts and accumulated usage. These fields form the data contract for a
Trace UI and application observability integrations.

### Trace and usage boundaries

`TraceStore` records model, tool and terminal events in memory by default.
Pass `persist_path` to enable file storage; generated `service-agent` projects
use `logs/traces.json`. History is bounded and persisted with atomic replacement
after each event. Only one process may write a trace file; use one server worker. Runs
loaded without a terminal event become `interrupted` after restart. This is a
record of interruption, not a resume/replay mechanism or a durable task queue.
Session memory is separate and is not restored by loading traces.
Defaults retain 200 runs and 2,000 events per run. Event pruning preserves the
first and newest events; `events_dropped` marks incomplete evidence. Store large
attachments separately and pass references instead of embedding image data.

Atomic replacement is not fsync durability: power loss, disk failures and
write errors can still lose trace data. Sink errors are logged and isolated
from the business run. Protect trace access because inputs, tool arguments
and outputs may contain application data.

Token usage can be known, unknown or partial across calls. Missing metadata
must not be treated as zero; a partial total includes only reported usage.
Request streaming usage from compatible providers and verify their actual
responses. Forge has no pricing catalogue or billing engine; supplied cost
metadata can still be used by existing execution policies. Run-level cost is
`null` unless all model attempts report cost; known token subtotals remain visible.
Token/cost budgets fail closed when required measurements are incomplete.

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

### Model middlewares

Intercept every model call (deepagents-style):

```python
from kbws_forge_runtime.middleware import (
    AppendSystemContextMiddleware,
    CallCountMiddleware,
    LoggingMiddleware,
)

runtime.register_agent(
    AgentInfo(agent_id="assistant", name="Assistant"),
    build_chat_graph(
        model,
        instruction="...",
        middleware=[
            LoggingMiddleware(),
            AppendSystemContextMiddleware("Reply in Chinese."),
        ],
    ),
)
```

Implement your own via `ModelMiddleware` (`before_model` / `after_model` / `wrap_model_call`).

### Structured output

Pass any pydantic schema; the model answers via a tool call whose arguments are parsed into the schema:

```python
from pydantic import BaseModel, Field


class Scientist(BaseModel):
    name: str = Field(description="全名")
    birth_year: int = Field(description="出生年份")
    fields: list[str] = Field(description="研究领域")


result = await runtime.chat("sci", "u1", "介绍牛顿")
assert isinstance(result.parsed, Scientist)   # ChatResult.parsed
# streaming: RunFinished.parsed
```

Schemas are supplied by the caller — nothing is hard-coded; nested models,
lists and enums all work. Structured output coexists with regular tools and
model middlewares (via `Agent(middleware=..., output_schema=...)` too).

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

`E0001` agent not found · `0002` session not found · `0003` session ownership ·
`0004` illegal parameter · `0005` run error · `0006` MCP config · `0007` cancelled ·
`0008` timeout · `0009` budget exceeded · `0010` tool denied ·
`0011` approval required · `0012` usage unavailable

## Development

```bash
uv sync --all-packages --all-extras
uv run pytest packages/forge-runtime/tests          # unit + API (fake models)
RUN_REAL_PROVIDER_TESTS=1 uv run pytest packages/forge-runtime/tests  # + real LLM calls
```

## License

MIT License
