<h1 align="center">Real-Time AI: Confluent Intelligence × watsonx Orchestrate</h1>
<p align="center">
<strong>From a customer ticket to a governed agent.<br>
  Fresh data from Confluent. Controlled action from watsonx Orchestrate.</strong>
</p>
<!-- BADGES -->
<p align="center">
<img src="https://img.shields.io/badge/version-1.0.0-blue.svg" alt="Version">
<img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License">
<img src="https://img.shields.io/badge/python-3.12+-blue.svg" alt="Python">
<img src="https://img.shields.io/badge/Confluent_Cloud-Kafka_·_Flink-0A3D62.svg?logo=apachekafka&logoColor=white" alt="Confluent Cloud">
<img src="https://img.shields.io/badge/Apache_Flink-SQL_·_Streaming_Agents-E6526F.svg?logo=apacheflink&logoColor=white" alt="Apache Flink">
<img src="https://img.shields.io/badge/IBM-watsonx_Orchestrate-052FAD.svg?logo=ibm&logoColor=white" alt="IBM watsonx Orchestrate">
<img src="https://img.shields.io/badge/AWS-Bedrock_·_AgentCore-232F3E.svg?logo=amazonwebservices&logoColor=white" alt="AWS Bedrock">
<img src="https://img.shields.io/badge/Terraform-844FBA.svg?logo=terraform&logoColor=white" alt="Terraform">
</p>
<!-- CTA VIDEO: replace VIDEO_URL with the YouTube link once the video is published -->
<p align="center">
<a href="VIDEO_URL">
<img src="https://img.shields.io/badge/▶️_Watch_Demo_on_YouTube-red?style=for-the-badge&logo=youtube&logoColor=white" alt="Watch demo on YouTube" height="50">
</a>
  &nbsp;&nbsp;
  <a href="https://www.linkedin.com/in/estepa/">
<img src="https://img.shields.io/badge/💬_Discuss_on_LinkedIn-0A66C2?style=for-the-badge&logo=linkedin&logoColor=white" alt="Discuss on LinkedIn" height="50">
</a>
</p>
<p align="center">
<em>Live demo presented at Data Streaming World Tour Paris, October 1, 2026.</em>
</p>

A customer opens a support ticket. Confluent triages it in the stream, watsonx Orchestrate prepares the answer with an agent running on AWS, a human validates it, and every step stays governed and traced.

The project combines:
- **Confluent Cloud**: Kafka, Schema Registry, Flink SQL with AI functions, Streaming Agents, Real-Time Context Engine
- **IBM watsonx Orchestrate**: native agents, controls, observability, agent directory
- **AWS**: the support portal (ECS, CloudFront), Bedrock models, two partner agents on Bedrock AgentCore (A2A)

## 🎯 The problem

Support teams want AI agents, but two things get in the way:

- 🕐 **Stale context.** Tickets are exported in batches; the agent decides on yesterday's data and misses the incident happening right now.
- 🔓 **Agents without control.** An agent that reads customer messages can leak personal data, be hijacked by a fake ticket, or promise a refund nobody approved.
- 🧩 **Agents everywhere.** Each team builds agents on its own platform, with no single place to see or govern them.

## 💡 The solution

Four acts, one ticket:

1. **Triage in the stream (Confluent).** The ticket becomes a Kafka event, is enriched with the live service status and the customer's sentiment, the support load is forecast, and a Streaming Agent decides: resolve or escalate.
2. **Escalation with a human in the loop (Orchestrate + AWS).** The escalation agent drafts a reply and asks the Customer Relations agent on AWS for a goodwill gesture. The advisor reviews, edits and sends. No agent answers the customer on its own.
3. **Governance (Orchestrate).** Personal data is masked and injection attempts are blocked before the model sees the ticket; every step is traced; external agents are registered in one directory.
4. **Ops copilot on live context (Confluent + Orchestrate).** The support manager asks a copilot that reads the Kafka topics live, and hands policy questions to a second AWS agent.

> Confluent turns events into decisions. watsonx Orchestrate turns decisions into controlled actions.

## 🏗️ Architecture

```
 Customer
    │ ticket
    ▼
┌──────────────────┐   tickets.raw    ┌──────────────────────────────────────────┐
│ support_portal   │ ───────────────► │ Confluent Cloud                          │
│ AWS ECS + CDN    │                  │  Flink SQL · AI_SENTIMENT · ML_FORECAST  │
│                  │ ◄─────────────── │  triage_agent (Streaming Agent + MCP)    │
└──────────────────┘   agent-actions  │  Real-Time Context Engine                │
   │          ▲                       └─────────────────────┬────────────────────┘
   │escalated │draft                                        │ MCP
   ▼          │                                             ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│ IBM watsonx Orchestrate                                                        │
│  escalation_agent ── A2A tool ──► Goodwill Gesture agent (AWS AgentCore)       │
│    controls: PII filter · content guardrails · human review                    │
│  support_ops_copilot ── A2A ──► Goodwill Policy Advisor (AWS AgentCore)        │
└────────────────────────────────────────────────────────────────────────────────┘
```

Detailed diagrams, components and topics: [`docs/architecture.md`](docs/architecture.md).

## Project structure

- [`app/`](app/) — FastAPI support portal: customer form, presenter dashboard, support admin console, MCP server
- [`terraform/`](terraform/) — Confluent foundation, AWS app hosting, Flink statements and triage agent
- [`orchestrate/`](orchestrate/) — watsonx Orchestrate agents, controls, tools, copilot, and the two AWS agents
- [`docs/`](docs/) — installation, architecture, governance, demo scenario, troubleshooting, slide deck
- [`deploy.py`](deploy.py) — deploys Confluent and the app (three Terraform stages)
- [`setup_demo.sh`](setup_demo.sh) — deploys the AWS agents and Orchestrate, and wires the app, in one command

## Quick start

### 1. Try the app locally

```bash
cd app
uv run python -m support_portal --disable-generator
# http://localhost:8000 · /dashboard · /support-admin
```

### 2. Configure

```bash
cp credentials.env.example credentials.env            # Confluent org key, AWS profile, regions
cp orchestrate/wxo.env.example orchestrate/wxo.env    # Orchestrate instance, RTCE key
```

### 3. Deploy

```bash
python3 deploy.py --stage base             # Confluent environment, cluster, topics
python3 deploy.py --stage app              # portal on AWS
python3 deploy.py --stage intelligence     # Flink, then again with the triage agent enabled
# Confluent console: enable the Real-Time Context Engine on the topics (manual step)

(cd orchestrate && uv sync) && source orchestrate/.venv/bin/activate
bash setup_demo.sh                         # AWS agents, Orchestrate, app wiring
```

Step-by-step guide with checks: [`docs/installation.md`](docs/installation.md). The Flink pool, ECS, AgentCore and Bedrock calls cost money while they run: [tear down](docs/installation.md#9-tear-down) after rehearsals.

## Documentation

### Per folder

- [`app/README.md`](app/README.md)
- [`terraform/README.md`](terraform/README.md)
- [`orchestrate/README.md`](orchestrate/README.md), with [`agents/`](orchestrate/agents/README.md), [`controls/`](orchestrate/controls/README.md), [`tools/`](orchestrate/tools/README.md), [`copilot/`](orchestrate/copilot/README.md) and the two [AWS agents](orchestrate/external-agents/)

### Guides in [`docs/`](docs/)

- [`docs/installation.md`](docs/installation.md) — deploy everything on your own accounts
- [`docs/architecture.md`](docs/architecture.md) — end-to-end and app diagrams, components, topics, design choices
- [`docs/governance.md`](docs/governance.md) — schemas, controls, human in the loop, traces, agents on other platforms
- [`docs/scenario-demo.md`](docs/scenario-demo.md) — the four acts minute by minute: what to show, what to say
- [`docs/troubleshooting.md`](docs/troubleshooting.md) — symptoms and fixes
- [`docs/project-spec.md`](docs/project-spec.md) and [`docs/specs/`](docs/specs/) — design decisions and detailed specs
- [`docs/DSWT2026-demo-walkthrough.pptx`](docs/DSWT2026-demo-walkthrough.pptx) — slide deck built from the demo, with the script in the speaker notes

## 🔒 Security

Never commit `credentials.env`, `app/.env`, `orchestrate/wxo.env`, `*.tfstate`, `.bedrock_agentcore.yaml`, `.bob/mcp.json` or `copilot-config.json` (all in `.gitignore`). Terraform state files hold API keys in plain text. `EMBED_DISABLE_SECURITY=true` opens the embedded chat of the **whole** Orchestrate instance: use it only on a dedicated demo instance.

## 🎥 External resources

- 🎬 [Full demo video on YouTube](VIDEO_URL)
- 💼 [LinkedIn](https://www.linkedin.com/in/estepa/)

## ⚖️ License

This project is distributed under the MIT license. See [LICENSE](LICENSE) for details.

## 🙏 Credits

Built by François Estepa (IBM) and Daniel Petisme (Confluent) with:
- [Confluent Cloud](https://www.confluent.io/confluent-cloud/): Kafka, Flink SQL, Streaming Agents, Real-Time Context Engine
- [IBM watsonx Orchestrate](https://www.ibm.com/products/watsonx-orchestrate) and its [ADK](https://developer.watson-orchestrate.ibm.com/)
- [Amazon Bedrock](https://aws.amazon.com/bedrock/) and [Bedrock AgentCore](https://aws.amazon.com/bedrock/agentcore/), with [Strands Agents](https://strandsagents.com/)
- [FastAPI](https://fastapi.tiangolo.com/), [Terraform](https://www.terraform.io/)

---

<p align="center">
  ⭐ If this project inspired you, star the repo: it helps other architects find it.<br>
  💬 Questions? Open an issue or reach out on <a href="https://www.linkedin.com/in/estepa/">LinkedIn</a>.
</p>
