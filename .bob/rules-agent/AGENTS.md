# AGENTS.md — Agent (coding) mode

This file provides guidance to agents when working with code in this repository.

## Editing rules

- **No test runner exists** — validate Python changes by reading the code, not by running tests.
- **No linter config** — follow the existing style (see root AGENTS.md) rather than running ruff/flake8.
- All Confluent Cloud Flink SQL lives in `terraform/confluent-intelligence/` as `.tf` files (inside `flink_statement` resources), not as standalone `.sql` files.
- Late imports inside function bodies in `tickets/service.py` and `orchestrate/drafts.py` are intentional circular-import breaks — do not hoist them to module level.
- Import the MCP server class as `from mcp.server.mcpserver import MCPServer` (mcp 2.x renamed `FastMCP`; `mcp.server.fastmcp` raises `ModuleNotFoundError`).

## Adding a new route

Register the router in `main.py` before `app.mount("/", mcp_asgi_app)` — this catch-all mount must stay last or new routes will be silently swallowed by the MCP sub-app.

## Adding a new Kafka topic handler

Add the handler to `KAFKA_HANDLERS` in `main.py`. Handlers are plain sync functions (called from the Kafka consumer's background thread via `loop.call_soon_threadsafe`); they can use `asyncio.create_task()` for async work (e.g., WebSocket broadcasts).

## Adding a new config field

Extend `Settings` in `config.py` (pydantic-settings). The field name becomes the env var name (uppercased), read automatically from `.env` at import time. The `__main__.py` CLI shim must set `os.environ[...]` *before* importing `config` if it needs to override the field from a CLI flag (the `Settings()` singleton is created at import).

## Producing to Kafka

Always use `TicketProducer.produce_model(topic, key, model_instance)` — the producer handles JSON-Schema serialization against Schema Registry. Do not call `confluent_kafka.Producer.produce()` directly with raw bytes; Schema Registry schema IDs must be embedded in the message for RTCE and Flink to deserialize them.

## Synthetic tickets

Call `tickets_service.store.create(...)` before producing to Kafka when adding a new synthetic path — without a `TicketRecord`, `handle_agent_action` will silently no-op when the pipeline's response arrives for that `ticket_id`.

## Orchestrate tool / agent naming

- `rebuild_wxo.sh` rewrites `AGENTCORE_URL` and `APP_ID` lines in `goodwill_tool.py` using `sed` before importing — do not restructure those assignments (multi-line or renamed variables will break the sed substitution).
- `orchestrate controls import` always appends a random 6-char suffix to the control name. `rebuild_wxo.sh` explicitly lists and deletes all existing `pii_escalation_input*` controls before re-importing for idempotency — any new control must follow the same pattern.
- `EscalationDraft` in `messaging/schemas.py` has French field names (`reponse_suggeree`, `geste_commercial`, `note_conseiller`) — these are Kafka wire-format identifiers consumed by RTCE and the copilot's SQL queries. **Do not rename them**, even though all UI and agent text is now in English.
- `wxo_include_synthetic` defaults to `False` — synthetic escalations never auto-draft to avoid each one calling the AWS goodwill agent. Only real escalations trigger `request_draft`.
