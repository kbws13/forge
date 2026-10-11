# Changelog

## 2.0.0 — Unreleased

### Breaking changes

- Remove the runtime Eval module and root exports, Eval CLI commands, generated
  suites and API endpoints, and Trace UI Eval views. Keep engineering tests.
- CLI 2.0 generates projects depending on runtime `>=2.0.0,<3`.
- Remove the runtime's Eval-only direct `jsonschema` dependency.

### Correctness and observability

- Persist Trace events during runs with atomic replacement; mark unfinished
  persisted runs `interrupted` on restart. Document single-process storage.
- Preserve terminal state on cancellation and event-stream closure.
- Clear previous structured output between turns and reject missing fresh output.
- Request streaming usage in generated model providers and distinguish unknown
  or partial usage from known zero consumption.
- Disable implicit provider retries and default new DeepSeek configurations to
  `deepseek-flash`; existing applications keep their explicit model settings.
- Close generated SSE streams deterministically and withhold incomplete cost totals.
- Keep the Trace UI focused on execution events, token usage and errors.

See [Migration to v2](docs/migration-v2.md) for application changes and storage
limitations. Real-provider and visual acceptance checks are separate from
fake-model and static tests; this changelog does not attest to those checks.
