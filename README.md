# Real-Time AI: Confluent Intelligence & watsonx Orchestrate

> **Data Streaming World Tour Paris 2026 — live demo**
>
> From a customer ticket to a governed agent: Confluent Cloud processes every support ticket in real time (Kafka, Flink SQL, Streaming Agents, Real-Time Context Engine), and IBM watsonx Orchestrate makes agents act under control (escalation agent, agents on AWS, controls, human in the loop, end-to-end traces).

---

## What the demo shows

An e-commerce customer opens a support ticket. We follow it end to end, in four acts:

| Act | What happens | Built with |
|---|---|---|
| **1. Triage in the stream** | The ticket is published to Kafka, enriched with the live service status and the customer's sentiment, the support load is forecast, and a Streaming Agent decides: resolve automatically or escalate. | Kafka, Schema Registry, Flink SQL (`AI_SENTIMENT`, `ML_FORECAST`, `AI_RUN_AGENT`), MCP tools exposed by the app |
| **2. Escalation, human in the loop** | For an escalated ticket, the Orchestrate escalation agent drafts a reply and asks the Customer Relations agent on AWS for a goodwill gesture. The support advisor reviews, edits and sends. | watsonx Orchestrate native agent, AWS Bedrock AgentCore agent (A2A), `/support-admin` console |
| **3. Governance** | Personal data is masked before the model sees it, prompt-injection attempts in tickets are blocked, every step is traced, and external agents are registered in one directory. | Orchestrate controls (PII filter, content guardrails), Observability, AI Gateway / agent directory |
| **4. Ops copilot on live context** | The support manager asks a copilot about current escalations and volumes. It reads the Kafka topics live, and hands goodwill-policy questions to a second AWS agent. | Confluent Real-Time Context Engine (MCP), Orchestrate copilot, AWS Goodwill Policy Advisor as collaborator |

```
 Customer / generator
        │ POST /api/tickets
        ▼
 ┌───────────────────────────────┐   MCP tools (Basic auth)   ┌─────────────────────────────────────┐
 │ support_portal (FastAPI)      │◄───────────────────────────│ Confluent Cloud                     │
 │ AWS ECS Express + CloudFront  │── tickets.raw ────────────►│  Flink: enrichment, ML_FORECAST,    │
 │ portal · dashboard · admin    │◄── tickets.agent-actions ──│  triage_agent (AI_RUN_AGENT)        │
 └──────────────┬────────────────┘                            │  Real-Time Context Engine           │
                │ escalated ticket (API call)                 └──────────────┬──────────────────────┘
                │                                                            │ MCP
                ▼                                                            ▼
 ┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
 │ IBM watsonx Orchestrate                                                                          │
 │  escalation_agent ──(A2A tool)──► Goodwill Gesture agent (AWS AgentCore)                         │
 │     controls: PII filter, content guardrails                                                     │
 │     the app publishes each draft to tickets.escalation-drafts                                    │
 │  support_ops_copilot ──(collaborator, A2A)──► Goodwill Policy Advisor (AWS AgentCore)            │
 │  Observability, agent directory, AI Gateway                                                      │
 └──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Repository layout

```
.
├── app/                         # FastAPI app (one Docker image): portal, dashboard, support admin, MCP server
│   └── support_portal/
│       ├── generator/           # Synthetic baseline + on-cue burst generator
│       ├── incidents/           # Known-issues KB + service-status state
│       ├── mcp/                 # MCP server (search_known_issues, get_account_context)
│       ├── messaging/           # Kafka producer + consumers (Avro + JSON Schema)
│       ├── orchestrate/         # Calls the escalation agent, parses its drafts
│       ├── tickets/             # Ticket lifecycle
│       └── static/              # HTML/CSS/JS front-ends, copilot bubble
├── terraform/
│   ├── base/                    # Confluent environment, cluster, topics, service account
│   ├── app-hosting/             # AWS ECR, ECS Express, CloudFront
│   └── confluent-intelligence/  # Flink statements, Bedrock connection, triage agent, RTCE key
├── orchestrate/
│   ├── agents/                  # escalation_agent.yaml
│   ├── controls/                # pii_control.yaml, escalation_guardrails.yaml
│   ├── copilot/                 # Support Ops Copilot + RTCE MCP toolkit
│   ├── tools/                   # goodwill_tool.py (A2A call to the AWS agent)
│   ├── external-agents/
│   │   ├── aws-compensation/    # Goodwill Gesture agent (AgentCore, A2A)
│   │   └── aws-policy-advisor/  # Goodwill Policy Advisor (AgentCore, A2A, traces to Orchestrate)
│   ├── rebuild_wxo.sh           # Builds all Orchestrate objects on one instance
│   ├── add_policy_advisor.sh    # Adds the advisor as a collaborator of the copilot
│   ├── make_copilot_embed.py    # Generates the copilot bubble config for the app
│   └── wxo.env.example          # Configuration template for the Orchestrate/AWS part
├── specs/                       # Detailed specs (ticket lifecycle, dashboard, admin)
├── deploy.py                    # Confluent + AWS app deployment (three Terraform stages)
├── setup_demo.sh                # AWS agents + Orchestrate + app wiring, in one command
├── DEPLOYMENT.md                # Step-by-step reproduction guide
└── PROJECT_SPEC.md              # Design notes and decision log
```

---

## Quick start

Full instructions, verifications and troubleshooting are in [`DEPLOYMENT.md`](DEPLOYMENT.md).

**Try the app locally** (no cloud needed, Kafka calls are no-ops):

```bash
cd app
uv run python -m support_portal --disable-generator
# http://localhost:8000 · /dashboard · /support-admin
```

**Deploy everything:**

```bash
cp credentials.env.example credentials.env                 # Confluent org key, AWS profile, regions
python3 deploy.py --stage base                             # Confluent foundation
python3 deploy.py --stage app                              # app on AWS
python3 deploy.py --stage intelligence                     # Flink, then again with the agent enabled
# Confluent console: enable the Real-Time Context Engine on the topics (manual)

cp orchestrate/wxo.env.example orchestrate/wxo.env         # Orchestrate instance, RTCE values
(cd orchestrate && uv sync) && source orchestrate/.venv/bin/activate   # ADK 2.17
bash setup_demo.sh                                         # AWS agents, Orchestrate, app wiring
```

**Tear down:** see [`DEPLOYMENT.md`, section 9](DEPLOYMENT.md#9-tear-down). The Flink pool, the ECS service, AgentCore and the Bedrock calls from the generator cost money while they run.

---

## Security

- Never commit `credentials.env`, `app/.env`, `orchestrate/wxo.env`, `*.tfstate`, `.bedrock_agentcore.yaml` or `app/support_portal/static/copilot-config.json`. They are in `.gitignore`.
- Terraform state files contain API keys and passwords in plain text: never share them.
- `.bob/mcp.json` (IBM Bob MCP configuration) holds Basic credentials: copy `.bob/mcp.json.example` and keep the real file local.
- `EMBED_DISABLE_SECURITY=true` turns off embedded-chat security on the **whole** Orchestrate instance. Use it only on a dedicated demo instance.

---

## Architecture notes

- **Single app, multiple surfaces** — the ticket form, the presenter dashboard and the support admin queue are routes of one FastAPI process.
- **MCP mount at `/` (catch-all, last)** — mounting at `/mcp` makes Starlette 307-redirect bare POSTs, which Confluent's Flink MCP client does not follow.
- **MCP Basic auth** — unauthenticated bot traffic probed the open `/mcp` endpoint within hours of the first deployment.
- **`tickets.metrics` uses Avro** — `ML_FORECAST` returns a `TIMESTAMP(6)` field that the JSON Schema format cannot represent.
- **The AWS goodwill agent is called as a tool, not a collaborator** — as a collaborator it takes over the turn and the escalation agent can no longer write its synthesis. The policy advisor, on the other hand, is a collaborator of the copilot (A2A).
- **Controls before the model** — the PII filter and the content guardrails run on `agent_pre_invoke`: the model never sees the raw personal data or the injection attempt.

See [`PROJECT_SPEC.md`](PROJECT_SPEC.md) for the full decision log.

---

## License

This project is a conference demo. No license is granted for production use.
