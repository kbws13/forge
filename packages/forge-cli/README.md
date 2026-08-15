# kbws-forge-cli

[![PyPI version](https://img.shields.io/pypi/v/kbws-forge-cli)](https://pypi.org/project/kbws-forge-cli/)
[![Python versions](https://img.shields.io/pypi/pyversions/kbws-forge-cli)](https://pypi.org/project/kbws-forge-cli/)
[![License](https://img.shields.io/pypi/l/kbws-forge-cli)](https://pypi.org/project/kbws-forge-cli/)

Scaffolding CLI for coding-agent projects, powered by
[kbws-forge-runtime](https://pypi.org/project/kbws-forge-runtime/). Generate a
production-shaped FastAPI agent service in seconds — layered architecture,
authentication, multi-environment config, persistent logging and a full test
suite, out of the box.

## Install

```bash
pip install kbws-forge-cli
```

Requires Python ≥ 3.13 and [uv](https://docs.astral.sh/uv/).

## Usage

Run `forge init` and answer the prompts (Vite-style interactive picker):

```bash
forge init
✔ Project name: … my-agent
✔ Select a template: › service-agent
```

Or pass everything explicitly for non-interactive/scripted use:

```bash
forge init my-agent                       # name given, template picked interactively
forge init my-agent -t base-agent         # fully non-interactive
```

Then start developing:

```bash
cd my-agent
uv sync                                   # installs kbws-forge-runtime from PyPI
uv run uvicorn app.main:app --reload      # dev server
uv run pytest                             # tests (fake models, no cost)
```

## Templates

| Template | Description |
| --- | --- |
| `service-agent` *(default)* | Full layered service: business aggregation (`agents/`) + technical layering (`app/`), global exception handling, unified `{code, info, data}` responses, API-key auth, multi-environment config, persistent JSON logging, request-id tracing, and unit/API/integration tests |
| `base-agent` | Minimal FastAPI Hello World for a quick start |

New templates placed in the CLI's `templates/` directory appear in the
interactive picker automatically.

## Generated project

`forge init my-service` produces:

```
my-service/
├── agents/<module_name>/     # business units: agent.py + prompts.py + tools.py
│   ├── agent.py              #   exports `agent` (auto-discovered by load_agents)
│   ├── prompts.py            #   composable Prompt components (code-first)
│   └── tools.py              #   this agent's tools
├── app/                      # technical layering
│   ├── main.py               #   create_app() + lifespan (load_agents)
│   ├── core/                 #   config / errors / response / security / logging
│   ├── api/v1/               #   agents / sessions / chat / chat_stream / health
│   ├── schemas/              #   request & response models
│   ├── services/             #   chat orchestration
│   └── providers/            #   LLM factory
├── tests/                    # unit / api / integration (real-provider gated)
├── scripts/run.sh
└── .env.example              # multi-env config template
```

Endpoints: `GET /api/v1/health` · `GET /api/v1/agents` · `POST /api/v1/sessions` ·
`POST /api/v1/chat` · `POST /api/v1/chat_stream` (SSE), all behind
`X-API-Key` / `Bearer` auth except health.

## Development

```bash
uv sync
uv run pytest packages/forge-cli/tests
```

## License

MIT License
