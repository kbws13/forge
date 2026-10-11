# Migration to Forge 2

Forge 2 focuses on service scaffolding, Agent/model/tool execution, structured
output, execution controls, token usage and Trace logs. Business approval,
device scheduling, application tests and reports belong to the consuming app.

## Package compatibility

Upgrade CLI and runtime together when adopting generated service code. CLI 2.0
generates `kbws-forge-runtime>=2.0.0,<3`; a CLI upgrade does not rewrite existing
applications. Back up the application and its local data before migration.
Keep applications requiring Eval on their compatible 1.x dependencies until
their Eval integrations are removed or moved outside Forge.

## Remove Eval integration

1. Remove imports from `kbws_forge_runtime.evals` and root Eval exports such as
   `EvalSuite`, `EvalRunner`, `EvalStore`, graders and dataset helpers.
2. Remove Eval initialization from the generated lifespan, Eval routes and
   trace-to-Eval lookups. Remove `evals/` suite examples and their dedicated tests.
3. Remove calls to `forge eval` and `/api/v1/evals` or
   `/api/v1/traces/{run_id}/eval` from scripts and clients. Forge 2 supplies no
   replacement grading or CI-gate API.
4. Retain ordinary unit, API, integration and browser tests. Move necessary
   application assertions into those tests rather than silently dropping them.
5. Archive historical `logs/evals/` results if needed; Forge 2 does not read or
   migrate them. Remove Eval-specific configuration and ignore rules manually.

## Review Trace and usage consumers

Generated services store traces in `logs/traces.json`; standalone `TraceStore`
is memory-only unless given `persist_path`. Writes use atomic replacement after each
event, not fsync durability. Use only one process/worker per file; multi-process
coordination, distributed storage and automatic task recovery are out of scope.
Bounded history may prune older runs, so export records needed for longer retention.

Persisted runs lacking a terminal state become `interrupted` on reload. Clients
must tolerate this status and must not treat it as success. No work resumes
automatically. Trace reload does not restore in-memory sessions or conversations.

Display unknown usage explicitly; display partial usage as incomplete. Do not
sum missing fields as zero or present reported subtotals as final consumption.
Legacy traces cannot reconstruct missing provider usage. Configure compatible
model clients to request streaming usage and verify the provider response.
Forge does not estimate money from token counts or maintain model pricing.

Structured-output calls must return a fresh result for the current turn. A
failed turn must not reuse an earlier turn's parsed output; handle that failure
in application code rather than treating stale data as a successful response.

## Validate the migrated service

Regenerate a temporary `service-agent` with CLI 2.0 and compare its startup,
routes, model provider and dependencies with the existing application. Update
the lockfile, run ordinary tests, then verify startup, a chat/tool call,
structured output, cancellation and persisted Trace reload. Run checks serially.

Verify the actual configured model name and API base URL using a dedicated
provider test. Inspect the Trace UI in a real browser separately; fake-model
tests cannot establish provider compatibility or visual correctness.
