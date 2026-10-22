# Deploying the DSWT 2026 demo on your own accounts

This guide rebuilds the whole demo on **your** Confluent Cloud organisation, **your** AWS account and **your** watsonx Orchestrate instance. It runs in two parts:

1. **Confluent + app** with `deploy.py` (three Terraform stages), sections 1 to 5.
2. **AWS agents + Orchestrate + app wiring** with `setup_demo.sh`, section 6.

Verify each step before moving to the next: that is what lets you see where a problem starts.

---

## 0. Rules before you start

- **Never reuse someone else's `terraform.tfstate`.** Terraform only knows your resources through these files. Run with your credentials, another person's state would either fail or, if you share the same Confluent organisation or AWS account, modify or destroy their deployment. If you received a copy of a deployed folder, delete them first:
  ```bash
  rm -f terraform/*/terraform.tfstate terraform/*/terraform.tfstate.backup
  rm -rf terraform/*/.terraform
  ```
- **Never commit or share** `credentials.env`, `app/.env`, `orchestrate/wxo.env`, the state files, `.bedrock_agentcore.yaml`, `.bob/mcp.json` or `copilot-config.json`. They contain API keys, the MCP password, the Bedrock IAM key or instance identifiers. If one of them has been shared, rotate the keys it contains.
- **Same AWS account as someone else?** Choose a different `TF_VAR_name_prefix`: IAM role, ECR repository and IAM user names are unique per account.
- **Same Orchestrate instance as someone else?** Set `SUFFIX` and `LABEL` in `orchestrate/wxo.env`: all technical names get the suffix, so the two demos do not overwrite each other.

---

## 1. Prerequisites

### Accounts and permissions

| Where | What you need |
|---|---|
| Confluent Cloud | An organisation where you are `OrganizationAdmin`, and a **Cloud resource management API key** (organisation key, not a cluster key) |
| Confluent Cloud | `AI_SENTIMENT` available for your organisation if possible (otherwise see step 3) |
| AWS | An administrator profile (IAM, ECR, ECS Express Mode, CloudFront, Bedrock, Bedrock AgentCore, Cognito) |
| AWS Bedrock | Access to **Claude Sonnet 4.5** in the Confluent region (`us-east-1` by default), with sufficient quotas |
| IBM watsonx Orchestrate | An instance, its URL and an API key (Settings > API details) |

### Tools

| Tool | Why |
|---|---|
| Terraform ≥ 1.3 | Keep the `.terraform.lock.hcl` files: ECS Express Mode needs the AWS 6.x provider |
| Docker | Builds the app image in `linux/amd64` (works on Apple Silicon) |
| AWS CLI v2 | ECR login, Cognito, account checks |
| Python ≥ 3.12 and `uv` | `deploy.py`, the app, the ADK virtual environment |
| `agentcore` | `uv tool install bedrock-agentcore-starter-toolkit` (deploys the two AWS agents) |
| watsonx Orchestrate ADK 2.17 | `cd orchestrate && uv sync && source .venv/bin/activate` (provides the `orchestrate` CLI) |

---

## 2. Regions

- **`TF_VAR_region`**: Kafka cluster, Flink **and** Bedrock calls (the Bedrock connection is built in the same region). Only `us-east-1` and `eu-west-1` are supported by the code.
- **`AWS_REGION`**: where the app runs (ECS + CloudFront).
- The two AgentCore agents and the Cognito pool are created in `us-east-1`.

Tested configuration: `TF_VAR_region=us-east-1` and `AWS_REGION=eu-west-1`. `AI_SENTIMENT` worked in `us-east-1` and failed in `eu-west-1` when the demo was built; check the current availability in the Confluent documentation. The Orchestrate instance region is independent.

---

## 3. Confluent and the app (`deploy.py`)

```bash
cp credentials.env.example credentials.env
```

First run:

```bash
TF_VAR_confluent_cloud_api_key=<organisation key>
TF_VAR_confluent_cloud_api_secret=<secret>
TF_VAR_name_prefix=my-dswt2026        # 20 characters max, lowercase, digits, - or _
TF_VAR_region=us-east-1

AWS_PROFILE=<admin profile>
AWS_REGION=eu-west-1

TF_VAR_intelligence_enable_bedrock_model=false
TF_VAR_intelligence_enable_agent=false
```

Never change `TF_VAR_name_prefix` or `TF_VAR_region` after the first deployment: Terraform would recreate everything. `TF_VAR_app_admin_token` is added automatically.

### Step 1 — Confluent foundation

```bash
python3 deploy.py --stage base
```

Creates the environment (Stream Governance Essentials), the Basic cluster, the service account and its keys, and the topics `tickets.raw`, `services.status` and `tickets.escalation-drafts`. Writes `app/.env`.

**Verify locally:** `cd app && uv run python -m support_portal --disable-generator`, create a ticket on `http://localhost:8000` and check that it appears in `tickets.raw` in the Confluent console.

### Step 2 — The app on AWS

```bash
python3 deploy.py --stage app
```

Three `terraform apply` passes: ECR repository and CloudFront distribution, then image build and ECS service, then the MCP allowed hosts. Note the **public URL** and the **admin token** printed at the end.

**Verify:** `<public URL>/status`, `/dashboard`, `/support-admin`.

### Step 3 — Flink without the agent

```bash
python3 deploy.py --stage intelligence
```

Creates the Flink compute pool, the enrichment and metrics statements and the Real-Time Context Engine key.

**Verify:** in Confluent > Flink, `services.status-current`, `tickets.enriched` and `tickets.metrics` are **RUNNING** and `tickets.enriched` receives messages.

If `tickets.enriched` goes DEGRADED or FAILED with a generic internal error, `AI_SENTIMENT` is not available for your organisation: add `TF_VAR_intelligence_enable_ai_sentiment=false` to `credentials.env` and re-run. Only the sentiment chart stays empty.

### Step 4 — The triage agent

In `credentials.env`:

```bash
TF_VAR_intelligence_enable_bedrock_model=true
TF_VAR_intelligence_enable_agent=true
```

```bash
python3 deploy.py --stage intelligence
```

Creates a dedicated IAM user (`bedrock:InvokeModel` on Anthropic models only), the Bedrock connection, the MCP connection to the app, the two tools, the agent and the `AI_RUN_AGENT` statement.

**Verify:** a ticket created from the public URL gets an automatic reply or is escalated within seconds, and `tickets.agent-actions` receives a message with `decision` and `message`.

**Costs:** every generated ticket triggers Bedrock calls. Pause the generator between sessions:

```bash
curl -X POST "<public URL>/admin/generator" -H "X-Admin-Token: <admin token>" \
  -H "Content-Type: application/json" -d '{"action": "pause"}'
```

(`"resume"` to restart, `{"action": "rate", "rate": 0.1}` to slow down.)

---

## 4. Manual step: enable the Real-Time Context Engine

There is no Terraform resource for this. In Confluent > Topics, enable the **Real-Time Context Engine** column on:

- `tickets.agent-actions`
- `tickets.escalation-drafts`
- `tickets.metrics`

Redo it whenever one of these topics is deleted and recreated. If the console answers "environment.id is required", open the topic list by navigating from the environment and the cluster rather than from a direct link.

---

## 5. Configure the Orchestrate and AWS part

```bash
cp orchestrate/wxo.env.example orchestrate/wxo.env
```

Fill in at least:

```bash
WXO_URL=https://api.<region>.watson-orchestrate.cloud.ibm.com/instances/<id>
WXO_API_KEY=<instance API key>
WXO_ENV_NAME=wxo-dswt2026
AWS_PROFILE=<admin profile>
RTCE_URL=<terraform -chdir=terraform/confluent-intelligence output -raw rtce_mcp_endpoint>
RTCE_KEY=<terraform -chdir=terraform/confluent-intelligence output -raw rtce_api_key>
RTCE_SECRET=<terraform -chdir=terraform/confluent-intelligence output -raw rtce_api_secret>
EMBED_LOCALE=en
```

The RTCE key is a Confluent **Global** API key created by the intelligence stage. If you only have EnvironmentAdmin rights (`TF_VAR_intelligence_create_rtce_key=false`), create a Global key in the Confluent console (Administration > API keys) and paste it instead.

To fill the RTCE values without displaying the secret:

```bash
K=$(terraform -chdir=terraform/confluent-intelligence output -raw rtce_api_key)
S=$(terraform -chdir=terraform/confluent-intelligence output -raw rtce_api_secret)
U=$(terraform -chdir=terraform/confluent-intelligence output -raw rtce_mcp_endpoint)
K="$K" S="$S" U="$U" python3 - <<'EOF'
import os, re
p = "orchestrate/wxo.env"; s = open(p).read()
for k, v in (("RTCE_KEY", os.environ["K"]), ("RTCE_SECRET", os.environ["S"]), ("RTCE_URL", os.environ["U"])):
    s = re.sub(rf"^{k}=.*$", lambda m: f"{k}={v}", s, flags=re.M) if re.search(rf"^{k}=", s, re.M) else s + f"\n{k}={v}\n"
open(p, "w").write(s)
EOF
unset K S U
```

**Test the RTCE key** (`200` expected, `401` means a wrong key or the engine is not enabled on this cluster):

```bash
set -a; source orchestrate/wxo.env; set +a
curl -s -o /dev/null -w '%{http_code}\n' -u "$RTCE_KEY:$RTCE_SECRET" -X POST \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}' \
  "$RTCE_URL"
```

Use a **new terminal** afterwards (or `unset SUFFIX LABEL`): variables exported from another config file take precedence over `wxo.env`.

Leave `COGNITO_*`, `AGENTCORE_ARN` and `POLICY_ADVISOR_ARN` empty: `setup_demo.sh` creates them and writes them back.

---

## 6. AWS agents, Orchestrate and app wiring (`setup_demo.sh`)

From the project root, ADK virtual environment active:

```bash
bash setup_demo.sh --list     # the 12 steps
bash setup_demo.sh            # all of them; re-runnable, resume with --from N
```

| Step | What it does |
|---|---|
| 1 | Checks the tools and lists the manual prerequisites |
| 2 | `deploy.py --stage base` (no change expected, or only the `tickets.escalation-drafts` topic) |
| 3 | Cognito pool, domain and client (OAuth client credentials) used by Orchestrate to call the AWS agents |
| 4 | Goodwill Gesture agent on AgentCore (A2A), then a test call |
| 5 | Goodwill Policy Advisor on AgentCore (A2A), then a test call |
| 6 | `orchestrate/rebuild_wxo.sh`: ADK environment, Cognito connection, `ask_goodwill_agent` tool, escalation agent, PII and content-guardrail controls, Goodwill Gesture agent in the directory, RTCE toolkit and Support Ops Copilot |
| 7 | `orchestrate/add_policy_advisor.sh`: the advisor becomes a collaborator of the copilot |
| 8 | `orchestrate/make_copilot_embed.py`: writes `app/support_portal/static/copilot-config.json` for the bubble |
| 9 | Redeploys the advisor with its traces sent to Orchestrate Observability |
| 10 | Writes the escalation agent ID and the instance URL and key to `credentials.env` |
| 11 | `deploy.py --stage app`: the app now calls the escalation agent and shows the copilot bubble |
| 12 | Prints the end-to-end checks |

Values created along the way are saved in `orchestrate/wxo.env` and `credentials.env`, so a re-run keeps what already exists.

### Switching to a new Orchestrate instance

Confluent and AWS do not change. In `orchestrate/wxo.env`, set the new `WXO_URL` and `WXO_API_KEY` and a **new** `WXO_ENV_NAME` (the ADK ignores `env add` for a name that already exists), then:

```bash
bash setup_demo.sh --from 6
```

If step 8 stops on "Could not get CRN" (403), the API key cannot read the IBM Cloud Resource Controller: copy the instance CRN from IBM Cloud > Resource list > watsonx Orchestrate, set `WXO_CRN=crn:v1:...` in `wxo.env`, and resume with `--from 8`.

---

## 7. End-to-end checks

1. **Flink:** the `...-run-triage-agent-...` statement is Running.
2. **Escalation:** from the portal, with a Gold account, a High-urgency login ticket written in an annoyed tone ("Locked out again - page reloads after I enter my password") is escalated within one or two minutes. The proposal (reply, goodwill gesture, note) appears in `/support-admin` and in `tickets.escalation-drafts`.
3. **Controls:** in the Orchestrate chat of the escalation agent, an email or phone number in the ticket is masked; a ticket asking the agent to ignore its instructions is blocked with the guardrail message.
4. **Copilot:** in the `/dashboard` bubble, ask "Which topics can you read?", then "What is our goodwill rule for a gold customer hit by a recurring payments outage?" (answered by the AWS advisor).
5. **Observability:** the escalation agent's traces show the controls, the model call and the AWS tool call; `goodwill_policy_advisor` has its own conversations.

Before an event:

- **Bedrock quotas:** check requests and tokens per minute for Claude Sonnet 4.5 cross-region inference; new accounts often have low quotas.
- **`MATCH_THRESHOLD`:** tune it during rehearsal with the phrasings you plan to use.
- **After an app redeploy:** hard-reload the dashboard, otherwise WebSockets stay attached to the old instance.
- **No fallback timer:** a ticket waits for a real message in `tickets.agent-actions`. A ticket that stays in triage means the agent is not answering.
- **Orchestrate token:** the ADK token expires after about two hours. Re-activate with `orchestrate env activate <WXO_ENV_NAME> --api-key "$(grep '^WXO_API_KEY=' orchestrate/wxo.env | cut -d= -f2-)"`.

---

## 8. Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| Agent statement DEGRADED on startup | Claude Sonnet 4.5 not enabled in Bedrock in `TF_VAR_region` |
| Tickets stay in triage, nothing in `tickets.agent-actions` | The triage agent does not answer: check the statement errors in Flink, then the Bedrock quotas |
| Triage statement Failed with MCP 421 | `MCP_ALLOWED_HOSTS` misses a host: drop the `tickets.agent-actions` table in a Flink workspace, then run `terraform apply -replace='confluent_flink_statement.run_triage_agent[0]'` in `terraform/confluent-intelligence` (with `credentials.env` loaded) |
| `Connection portal_mcp_connection already exists in catalog` | A partial destroy left it: `DROP CONNECTION portal_mcp_connection;` in a Flink workspace, then re-run |
| Region error in `bedrock_inference_profile_prefix` | `TF_VAR_region` is neither `us-east-1` nor `eu-west-1`: add its inference profile prefix in `03_statements_triage_agent.tf` |
| AWS "name already exists" | `TF_VAR_name_prefix` collides with another deployment in the same account |
| Step 6: `ERROR: toolkit confluent_rtce not imported` / 401 | Wrong `RTCE_KEY` / `RTCE_SECRET`, or the engine is not enabled on the `RTCE_URL` cluster: run the `curl` test of section 5 |
| Copilot answers "live ticket data is unavailable" | Same cause as above, or the topic is not enabled in the Real-Time Context Engine (section 4) |
| `Policy binding with name ... already exists` | A control with this name exists on the instance: `orchestrate controls list`, then `orchestrate controls remove -n <name>` and re-run step 6 |
| `Token has expired` | ADK token expired (about 2 h): re-activate the environment (section 7) |
| Step 8: "Could not get CRN" / 403 | Set `WXO_CRN` in `wxo.env` (section 6) |
| Step 9: CodeBuild or ECR errors from another AWS account | A `.bedrock_agentcore.yaml` copied from elsewhere: `enable_tracing.sh` regenerates it for the current account; delete it by hand if needed |
| Bubble in the wrong language | `EMBED_LOCALE` in `wxo.env`, then `bash setup_demo.sh --from 8` |
| Changes in a YAML not visible in the app's bubble | Re-import and deploy the agent (`bash setup_demo.sh --only 6`); the bubble uses the **live** version |

---

## 9. Tear down

**Confluent and the app:**

```bash
python3 deploy.py --stage all --destroy
```

Destroys intelligence, then app, then base.

**AWS agents** (in each of `orchestrate/external-agents/aws-compensation` and `aws-policy-advisor`):

```bash
agentcore destroy
```

Then delete the Cognito pool (domain first) and check that nothing is left in ECR, S3 (`bedrock-agentcore-*` buckets), CodeBuild and CloudWatch Logs:

```bash
aws cognito-idp delete-user-pool-domain --user-pool-id "$COGNITO_POOL_ID" --region us-east-1 \
  --domain "$(echo "$COGNITO_TOKEN_URL" | sed -E 's#https://([^.]+)\..*#\1#')"
aws cognito-idp delete-user-pool --user-pool-id "$COGNITO_POOL_ID" --region us-east-1
```

**Orchestrate:** remove the agents, tools, toolkit, controls and connections from the instance (UI, or `orchestrate agents remove`, `tools remove`, `toolkits remove`, `controls remove`, `connections remove`), or simply let a trial instance expire.

The Flink pool, the ECS service, CloudFront, AgentCore and above all the Bedrock calls from the generator cost money while they run: tear down after rehearsals.
