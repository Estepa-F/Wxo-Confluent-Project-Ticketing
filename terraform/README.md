# Terraform

Three independent stages, applied in this order by [`deploy.py`](../deploy.py) from the project root. Never run them with someone else's `terraform.tfstate`: see the [installation guide](../docs/installation.md#0-rules-before-you-start).

| Stage | Folder | Command | Creates |
|---|---|---|---|
| 1 | [`base/`](base) | `python3 deploy.py --stage base` | Confluent environment (Stream Governance Essentials), Basic cluster, service account and API keys, topics `tickets.raw`, `services.status`, `tickets.escalation-drafts`; writes `app/.env` |
| 2 | [`app-hosting/`](app-hosting) | `python3 deploy.py --stage app` | ECR repository, Docker image, ECS Express service, CloudFront distribution, MCP allowed hosts |
| 3 | [`confluent-intelligence/`](confluent-intelligence) | `python3 deploy.py --stage intelligence` | Flink compute pool and statements, Bedrock connection and IAM user, MCP connection to the app, triage agent, RTCE Global API key |

## `confluent-intelligence/` files

| File | Content |
|---|---|
| `01_statements_ticket_metrics.tf` | Per-service counts on 15-minute windows + `ML_FORECAST` → `tickets.metrics` (Avro) |
| `02_statements_ticket_enrichment.tf` | Current service status table + temporal join + `AI_SENTIMENT` → `tickets.enriched` |
| `03_statements_triage_agent.tf` | Bedrock model, MCP connection and tools, `triage_agent`, `AI_RUN_AGENT` statement → `tickets.agent-actions` |
| `bedrock_iam.tf` | Dedicated IAM user limited to `bedrock:InvokeModel` on Anthropic models |
| `rtce.tf` | Global API key for the Real-Time Context Engine (enabling the engine per topic is a manual console step) |

## Feature flags (`credentials.env`)

| Variable | Default | Effect |
|---|---|---|
| `TF_VAR_intelligence_enable_bedrock_model` | `false` | Creates the Bedrock connection and model |
| `TF_VAR_intelligence_enable_agent` | `false` | Creates the triage agent and its statement |
| `TF_VAR_intelligence_enable_ai_sentiment` | `true` | `false` if `AI_SENTIMENT` is not available for your organisation |
| `TF_VAR_intelligence_create_rtce_key` | `true` | `false` with EnvironmentAdmin rights only (create the key in the console) |

Keep the `.terraform.lock.hcl` files: ECS Express Mode requires the AWS 6.x provider. Never change `TF_VAR_name_prefix` or `TF_VAR_region` after the first deployment.
