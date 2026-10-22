# AGENTS.md — Ask mode

This file provides guidance to agents when working with code in this repository.

## Where things actually live

- **Ticket lifecycle spec**: `specs/ticket-lifecycle/spec.md` (canonical — not PROJECT_SPEC.md section 2.2)
- **Dashboard spec**: `specs/dashboard/spec.md`
- **Support Admin spec**: `specs/ticket-management/spec.md`
- **Architecture diagram**: `support-triage-architecture.mermaid`
- **Deployment guide**: `DEPLOYMENT.md`; one-command Orchestrate/AWS setup: `setup_demo.sh`
- **All Flink SQL**: inside `.tf` files in `terraform/confluent-intelligence/`, not standalone `.sql` files
- **Orchestrate agent YAML + setup scripts**: `orchestrate/` in project root (not `app/`) — separate `uv` project with its own `pyproject.toml`

## Counterintuitive structure

- `messaging/schemas.py` contains models for Flink-produced topics (`EnrichedTicket`, `MetricsPoint`, `AgentAction`) that are **never instantiated in-app** — they exist only to document the wire contract from the Flink pipeline.
- `tickets/models.py` = in-app lifecycle models (not on Kafka); `messaging/schemas.py` = Kafka wire models. These are separate and not interchangeable.
- The MCP server is the same process as the web app — there is no separate MCP service.
- `static/console.html` **no longer exists** (retired; controls moved into `dashboard.html`). `intake.html` **no longer exists** (replaced by `new-ticket.html` served at `/`).

## Orchestrate deployment scripts

- `setup_demo.sh` (root) — the entry point: Cognito, the two AgentCore agents, then the scripts below, the copilot bubble config and the app redeploy. Re-runnable with `--from N`.
- `orchestrate/rebuild_wxo.sh` — reads `wxo.env`, uses the `orchestrate` ADK CLI: Cognito OAuth2 connection, tool import, escalation agent, PII and guardrail controls (idempotent), RTCE toolkit and copilot, SUFFIX/LABEL multi-instance naming.
- `orchestrate/add_policy_advisor.sh` — adds the AWS policy advisor as a collaborator of the copilot.

## Known open decisions (as of project spec)

- Fallback escalation timer was deliberately removed — every ticket now waits for a real `tickets.agent-actions` message with no timeout.
- `MATCH_THRESHOLD` needs tuning against live ticket phrasings during rehearsal.
- `AI_SENTIMENT` was only available in `us-east-1` at build time — re-verify before relying on this.
