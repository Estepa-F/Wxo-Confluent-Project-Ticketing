# AGENTS.md

This file provides guidance to agents when working with code in this repository.

## Project overview

Live demo app for a conference talk (Data Streaming World Tour 2026). One FastAPI app (`app/support_portal/`) + three Terraform stacks (`terraform/base`, `terraform/app-hosting`, `terraform/confluent-intelligence`). No test suite exists in this repo.

## Running the app locally

All commands run from `app/` using `uv`:

```bash
cd app
uv run python -m support_portal             # runs with generator enabled
uv run python -m support_portal --disable-generator   # no synthetic tickets
uv run python -m support_portal --port 9000 --generator-rate 0.05
```

The app boots and serves REST/MCP even without Confluent Cloud credentials (`CC_BOOTSTRAP_SERVERS` unset) — Kafka producer/consumer silently no-op. No linter or test runner is configured; `pyproject.toml` has no `[tool.ruff]`, `[tool.pytest]`, or similar sections.

## Deploy

```bash
python3 deploy.py                        # stage: base (Confluent infra)
python3 deploy.py --stage app            # build Docker image + ECS deploy
python3 deploy.py --stage intelligence   # Flink jobs + triage agent
python3 deploy.py --stage all            # all three in order
python3 deploy.py --stage all --destroy  # tear down in reverse order
```

Credentials go in `credentials.env` (copy from `credentials.env.example`). App config goes in `app/.env` (copy from `app/.env.example`); `deploy.py --stage base` writes `app/.env` automatically from Terraform outputs.

## Critical config gotchas

- `MCP_ALLOWED_HOSTS` **must** include the public CloudFront hostname before deploying — the `mcp` SDK's DNS-rebinding protection returns HTTP 421 otherwise (confirmed live; broke Confluent Flink's MCP client in production).
- `MCP_ALLOWED_HOSTS` also needs the raw ECS ingress hostname (`*.ecs.<region>.on.aws`) because CloudFront rewrites the `Host` header to the origin domain. This requires a third Terraform pass after the service is first created.
- `GENERATOR_RATE=0.1` (not `0.5` as in `.env.example`) is the live-demo default in `config.py` — `.env.example` value is higher and will flood Bedrock quotas when the triage agent is enabled.
- `MATCH_THRESHOLD=50` in `config.py` (tuned against real `tickets.csv` + `knowledge_base.csv`). The `.env.example` and Terraform default say `50`, but the original `65` is wrong for this KB — median real-ticket match score is ~47, so `65` only resolves ~2.4% of tickets.

## Architecture: module-level singletons

All shared state is **process-global module-level singletons**, not on `app.state`:
- `messaging/producer.py` exports a singleton `producer = TicketProducer()`
- `tickets/service.py` exports a singleton `store = TicketStore()`
- `dashboard/service.py` holds all dashboard state as module-level dicts/sets

`app.state` only holds `producer`, `account_pool`, and `portal_state` for the few routes that need them via `Request`. Most domain modules import `service.store` or `messaging.producer.producer` directly.

## MCP mount wiring (non-obvious)

The MCP sub-app mounts at `/` (catch-all, registered last in `main.py`) not at `/mcp` — mounting at `/mcp` causes Starlette to 307-redirect bare `/mcp` POSTs to `/mcp/`, which some MCP HTTP clients don't follow. The MCP server's internal route stays as `/mcp` by the SDK default. FastAPI routers must be registered before the mount so they take priority over the catch-all.

The MCP session manager must be entered explicitly inside `lifespan` via `async with mcp_server.session_manager.run()` — Starlette does not propagate a mounted sub-app's lifespan automatically.

## Kafka/serialization non-obvious facts

- `tickets.metrics` uses **Avro** (not JSON-Schema) because `ML_FORECAST` returns a `TIMESTAMP(6)` field that Confluent Cloud's `json-registry` format can't represent (max precision 3). `DashboardConsumer` uses a separate `AvroDeserializer` for this topic and merges the Avro key (where `window_end` lives) back into the value dict before dispatching handlers.
- `DashboardConsumer` forces `OFFSET_BEGINNING` on the very first partition assignment (using `assign()`, not `seek()` — `seek()` inside `on_assign` doesn't reliably take effect per confluent-kafka's issue tracker) so the in-memory dashboard state rebuilds from history on restart.
- User reply re-enters triage: `store.add_reply()` returns `conversation_context()` (full thread as plain text), which is re-published to `tickets.raw` — not just the new message in isolation.

## Code style

- Python 3.10+, no `from __future__ import annotations` in app modules (only in `deploy.py` for Python 3.9 compat on the host).
- `Pydantic BaseModel` for all wire formats; `@dataclass` for internal-only structs (e.g. `KnownIssue`, `TicketRecord`).
- Module docstrings explain the architectural decision, not the API surface.
- UTC datetimes via `datetime.now(timezone.utc)` — always timezone-aware, never `utcnow()`.
- `TicketStatus` and `TicketEventType` are `Literal` type aliases, not `Enum` subclasses.
- Kafka handlers (`handle_message`, `handle_agent_action`) are plain sync functions dispatched via `loop.call_soon_threadsafe` — they can safely `asyncio.create_task()` for WebSocket broadcasts.
- `secrets.compare_digest` for all credential comparisons (MCP Basic auth).
- Late imports inside function bodies (not at module top) are intentional to break circular imports — e.g. `tickets/service.py` imports `orchestrate.drafts` inside `handle_agent_action`; `orchestrate/drafts.py` imports `tickets.service.store` inside `request_draft` and `handle_draft_message`. Do not hoist these.
- `is_synthetic_user_id(user_id)` from `accounts/pool.py` is the canonical check for gating synthetic-ticket-specific behavior (used in store, generator, orchestrate/drafts).
- `BURST_CANDIDATES_BY_SERVICE` in `generator/synthetic.py` is computed once at module import time against the live KB+threshold — it will re-run whenever the module is reloaded, which is only at process start.
- `mcp 2.x` renamed `FastMCP` to `MCPServer`; import from `mcp.server.mcpserver`, not `mcp.server.fastmcp` (raises `ModuleNotFoundError` on the installed version).

## Orchestrate integration non-obvious facts

- `EscalationDraft` Kafka model (`messaging/schemas.py`) uses French field names (`reponse_suggeree`, `geste_commercial`, `note_conseiller`) as wire-format identifiers — consumed by RTCE SQL queries and the Support Ops Copilot. **Do not rename** even though all agent instructions are in English.
- The AWS goodwill agent is wired as a **tool** (not a collaborator) in `escalation_agent.yaml`. As a collaborator it "takes over" and terminates the turn with raw JSON, preventing the escalation agent from writing its synthesis. This is documented in the YAML header.
- `orchestrate controls import` always appends a random 6-char suffix to the technical name. `rebuild_wxo.sh` purges existing `pii_escalation_input*` controls before each import. If adding a new control, follow the same delete-then-import pattern.
- `rebuild_wxo.sh` patches `goodwill_tool.py` via `sed` (rewrites `AGENTCORE_URL = ...` and `APP_ID = ...` lines). Keep those assignments as simple single-line strings — multi-line or renamed variables break the substitution.
- `wxo_include_synthetic` defaults to `False` — prevents each synthetic escalation from calling the AWS goodwill agent. Set to `True` only for end-to-end testing.
- `orchestrate/` is a **separate** `uv` project (its own `pyproject.toml` + `.venv`) — do not install its dependencies from `app/`.
