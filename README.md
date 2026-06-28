# Forge

> A production-grade coding agent framework written in Python, inspired by the architectural patterns of modern coding agents.

## Features（Roadmap）

### Runtime and Model

- [ ] AgentRuntime facade with async event streaming.
- [ ] Message and event model.
- [ ] Input normalization for prompts, commands, and attachments.
- [ ] System prompt builder with project rules and memory.
- [ ] OpenAI-compatible model provider through LangChain `ChatOpenAI`.
- [ ] Retry, timeout, and fallback policy around model calls.

### Tools

- [ ] LangChain tool wrappers for built-in tools.
- [ ] Tool registry with duplicate detection and lookup.
- [ ] Read-only file search and read tools.
- [ ] File mutation tools with path guards.
- [ ] Shell tool with a strict allowlist.
- [ ] Tool result conversion for model feedback.

### Permissions and Security

- [ ] Allow, ask, and deny permission decisions.
- [ ] Permission context with runtime mode, cwd, agent id, and interactivity.
- [ ] Session, project, and user scoped permission rules.
- [ ] Headless JSON permission request and response flow.
- [ ] CLI approval prompts.
- [ ] PathGuard for workspace boundaries.
- [ ] Security policy and audit redaction.

### Session, Memory, and Context

- [ ] SessionStore with JSONL transcript persistence.
- [ ] Resume by session id.
- [ ] Project, user, agent, and session memory layers.
- [ ] Durable memory save tool.
- [ ] Session memory markdown updates after each turn.
- [ ] Memory dedupe, expiry, and relevant memory prefetch.
- [ ] Context budget and deterministic compaction before model calls.
- [ ] LangGraph checkpoint backend.

### Workflow

- [ ] Todo and Plan Mode.
- [ ] Subagent tool with isolated runtime state.
- [ ] Background task scheduler.
- [ ] Task output and cancellation.
- [ ] Hook registry for lifecycle events.
- [ ] Command registry for workflow commands such as `/model`, `/permissions`, `/compact`, `/resume`, and `/memory`.

### Integrations

- [ ] MCP client adapter that exposes remote MCP tools as LangChain tools.
- [ ] Plugin loader for commands, tools, hooks, and agents.
- [ ] Browser and IDE adapters.
- [ ] Git workflow helpers for status, diff, and review loops.

### Observability and Release

- [ ] Local structured logs.
- [ ] LangSmith tracing metadata.
- [ ] Metrics for usage, tool duration, and task state.
- [ ] Eval scenarios for end-to-end behavior.
- [ ] Docker image and Compose smoke tests.
- [ ] Release checklist and migration runner.

## Getting Started

Create the Conda environment:

```shell
conda env create -f environment.yml
conda activate forge
```

Install current dependencies:

```shell
pip install -r requirements.txt
```

## License

MIT License
