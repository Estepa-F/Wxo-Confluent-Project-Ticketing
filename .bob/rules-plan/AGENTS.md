# AGENTS.md — Plan mode

This file provides guidance to agents when working with code in this repository.

## Architectural constraints

- **All state is in-memory and non-persistent** — `TicketStore`, `AccountPool`, `PortalState`, and all dashboard state live only for the process lifetime. Any feature that requires state to survive a restart must either replay from Kafka or accept that it won't.
- **Single-task ECS deployment** — there is no rolling replacement; a restart leaves zero healthy targets briefly, which trips the AWS circuit-breaker if the synthetic generator is running. Plan around this for any change that requires a task restart.
- **Three-pass Terraform bootstrap for `app` stage** — `MCP_ALLOWED_HOSTS` can't be fully correct until after the ECS service is created (because the raw ECS ingress hostname isn't known until that apply), so a third apply is always required. Any plan that changes the app's public URL requires the same three-pass sequence.
- **Re-applying changed Flink statements requires manual DROP** — Flink tables created with `CREATE TABLE ... AS SELECT` fail with "table already exists" if the statement text changes; Terraform can't auto-drop a live table. Plan a manual `DROP TABLE` step in the Flink SQL workspace before any statement-text change.
- **`tickets.agent-actions` fans out to two handlers** (`dashboard_service.handle_message` and `tickets_service.handle_agent_action`). Any change to how agent decisions are parsed must be reflected consistently in both, since both call the same parsing logic.
- **`RTCE` toggle is manual** — enabling the Real-Time Context Engine on a topic is a Confluent Console click, not a Terraform resource. Must be redone after any topic drop/recreate.
- **Bedrock cross-region inference profile prefix is region-dependent** — the prefix mapping (`us-east-1 → us`, `eu-west-1 → eu`) is in `terraform/confluent-intelligence/03_statements_triage_agent.tf`. Adding a new region requires adding its prefix there; AWS's geography-prefix convention is not reliable (`apac.`, not `ap.`).
- **`AI_SENTIMENT` requires `us-east-1`** at time of build — the Confluent Cloud environment is on `us-east-1` as a result. The Terraform default for `region` is still `eu-west-1`; the actual region is set via `TF_VAR_region` in `credentials.env`.
- **Multi-presenter Orchestrate instances use SUFFIX/LABEL** — `rebuild_wxo.sh` appends `$SUFFIX` to all technical names and `$LABEL` to display names, enabling side-by-side demos on one Orchestrate instance. Any plan adding new agents or tools must propagate the same SUFFIX substitution or the multi-instance pattern breaks.
- **`orchestrate/` and `app/` are isolated `uv` environments** — running `uv sync` in `app/` won't install Orchestrate ADK tools; dependencies for the `orchestrate/` tooling are managed separately in `orchestrate/pyproject.toml`.
