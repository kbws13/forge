# kbws-forge-cli

Generate Python Agent services and inspect their execution traces locally.
Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/).

## Install and generate

```bash
pip install "kbws-forge-cli>=2,<3"
forge init my-agent -t service-agent
cd my-agent
uv sync
# Copy .env.example to .env; configure API_KEY and DEEPSEEK_*.
uv run uvicorn app.main:app --reload
uv run pytest
```

Run `forge init` without arguments for an interactive picker. CLI 2.0 generates
projects requiring `kbws-forge-runtime>=2.0.0,<3`. Installation does not modify
existing generated applications; migrate those applications explicitly.

## Templates

- `service-agent` (default): FastAPI service with `agents/` for prompts and tools,
  `app/` for configuration, authentication, APIs and model providers, and `tests/`
  for unit, API and opt-in real-provider tests. Includes structured-output examples.
- `base-agent`: minimal FastAPI Hello World, without Agent or Trace endpoints.

Generated service endpoints include health, agents, sessions, chat, streaming
chat and traces under `/api/v1`. All except health use API-key authentication
when configured. Responses use `{code, info, data}`; chat streaming uses SSE.
Model names and base URLs are configurable; provider compatibility requires
verification with the intended API account and model.

## Trace UI

With a generated `service-agent` running, open another terminal:

```bash
forge trace --api-url http://127.0.0.1:8000/api/v1
```

The UI listens on `127.0.0.1:8765` and displays sessions, turns, model/tool events,
timing, token usage and raw JSON. It refreshes traces created by other clients
through `GET /api/v1/traces` and `GET /api/v1/traces/{run_id}`.
Connection settings, including an optional API key, are stored in localStorage.

The service persists bounded trace history to `logs/traces.json` using atomic
replacement after each event. Use one server process/worker per trace file.
After restart, unfinished runs are marked `interrupted`; they are not resumed.
Atomic replacement is not fsync durability and cannot guarantee survival of
power loss or disk failure. Trace persistence does not persist conversation memory.

Usage may be known, unknown or partial. Unknown usage is not zero; a partial
total is not the complete token consumption. Forge does not maintain pricing or
calculate billing. Treat trace contents as application data when configuring
access and retention.

## Version 2 migration

Version 2 removes `forge eval`, Eval API endpoints, generated `evals/` modules
and all Eval views. This does not remove regular engineering tests. Existing
Eval applications must remain on compatible 1.x packages until migrated. See
[migration-v2.md](https://github.com/kbws13/forge/blob/main/docs/migration-v2.md).

## Development

From the repository root:

```bash
uv sync --all-packages --all-extras
uv run pytest packages/forge-cli/tests
```

Browser regression tests use a local stub API and require Node, npm and
Chrome/Chromium. Set `FORGE_E2E=1`, then run
`uv run pytest packages/forge-cli/tests/test_e2e_trace_ui.py -v`.
The harness installs Playwright dependencies if needed. Fake-model tests do
not establish real DeepSeek compatibility or constitute visual acceptance.

## License

MIT License
