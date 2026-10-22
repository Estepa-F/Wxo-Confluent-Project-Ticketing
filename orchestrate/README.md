# watsonx Orchestrate

Everything the demo deploys on a watsonx Orchestrate instance, plus the two AWS agents that Orchestrate federates. The whole folder is deployed by [`setup_demo.sh`](../setup_demo.sh) (steps 3 to 9); the scripts below can also be run on their own.

## What gets deployed

| Object | Kind | Source | Role |
|---|---|---|---|
| `escalation_agent` | Native agent | [`agents/`](agents) | Drafts the reply and goodwill gesture for an escalated ticket |
| `ask_goodwill_agent` | Python tool | [`tools/`](tools) | A2A call from the escalation agent to the AWS Goodwill Gesture agent |
| `pii_escalation_input`, `escalation_guardrails` | Controls | [`controls/`](controls) | PII masking and content guardrails before the model |
| `support_ops_copilot` | Native agent | [`copilot/`](copilot) | Support manager's copilot on live Confluent topics |
| `confluent_rtce` | MCP toolkit | [`copilot/`](copilot) | Confluent Real-Time Context Engine tools |
| `customer_goodwill_agent` | External agent (A2A) | [`external-agents/aws-compensation/`](external-agents/aws-compensation) | Goodwill Gesture agent on AWS Bedrock AgentCore |
| `goodwill_policy_advisor` | External agent (A2A) | [`external-agents/aws-policy-advisor/`](external-agents/aws-policy-advisor) | Policy advisor on AWS, collaborator of the copilot, sends its traces to Orchestrate |
| `bedrock_cognito_a2a`, `confluent_rtce` | Connections | created by the scripts | OAuth client credentials (Cognito) for the AWS agents; Basic auth for the RTCE |

## Scripts

| File | What it does |
|---|---|
| [`rebuild_wxo.sh`](rebuild_wxo.sh) | Builds every Orchestrate object above on one instance (idempotent). `SUFFIX` / `LABEL` let several demos share an instance |
| [`add_policy_advisor.sh`](add_policy_advisor.sh) | Imports the policy advisor and declares it as a collaborator of the copilot (`--rollback` to remove it) |
| [`make_copilot_embed.py`](make_copilot_embed.py) | Writes `app/support_portal/static/copilot-config.json` for the chat bubble; `--disable-security` / `--status` for embedded chat security |
| [`wxo.env.example`](wxo.env.example) | Configuration template: copy to `wxo.env` (never committed) |

## Setup

```bash
cd orchestrate && uv sync && source .venv/bin/activate   # ADK: ibm-watsonx-orchestrate 2.17
cp wxo.env.example wxo.env                               # fill in WXO_URL, WXO_API_KEY, RTCE_*
cd .. && bash setup_demo.sh --from 3
```

Reactivate the ADK environment when the token expires (about two hours):

```bash
orchestrate env activate "$WXO_ENV_NAME" --api-key "$(grep '^WXO_API_KEY=' orchestrate/wxo.env | cut -d= -f2-)"
```

See the [installation guide](../docs/installation.md) and [governance](../docs/governance.md).
