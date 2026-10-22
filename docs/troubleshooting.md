# Troubleshooting

Symptoms met while building and running the demo, grouped by layer. For the deployment steps themselves, see the [installation guide](installation.md).

## Confluent, Flink and the app

| Symptom | Likely cause and fix |
|---|---|
| Agent statement DEGRADED on startup | Claude Sonnet 4.5 not enabled in Bedrock in `TF_VAR_region` |
| Tickets stay in triage, nothing in `tickets.agent-actions` | The triage agent does not answer: check the statement errors in Flink, then the Bedrock quotas |
| Triage statement Failed with MCP 421 | `MCP_ALLOWED_HOSTS` misses a host: drop the `tickets.agent-actions` table in a Flink workspace, then run `terraform apply -replace='confluent_flink_statement.run_triage_agent[0]'` in `terraform/confluent-intelligence` (with `credentials.env` loaded) |
| `Connection portal_mcp_connection already exists in catalog` | A partial destroy left it: `DROP CONNECTION portal_mcp_connection;` in a Flink workspace, then re-run |
| Region error in `bedrock_inference_profile_prefix` | `TF_VAR_region` is neither `us-east-1` nor `eu-west-1`: add its inference profile prefix in `03_statements_triage_agent.tf` |
| AWS "name already exists" | `TF_VAR_name_prefix` collides with another deployment in the same account |

## watsonx Orchestrate and the AWS agents

| Symptom | Likely cause and fix |
|---|---|
| Step 6: `ERROR: toolkit confluent_rtce not imported` / 401 | Wrong `RTCE_KEY` / `RTCE_SECRET`, or the engine is not enabled on the `RTCE_URL` cluster: run the `curl` test in the [installation guide, section 5](installation.md#5-configure-the-orchestrate-and-aws-part) |
| Copilot answers "live ticket data is unavailable" | Same cause as above, or the topic is not enabled in the Real-Time Context Engine ([installation guide, section 4](installation.md#4-manual-step-enable-the-real-time-context-engine)) |
| `Policy binding with name ... already exists` | A control with this name exists on the instance: `orchestrate controls list`, then `orchestrate controls remove -n <name>` and re-run step 6 |
| `Token has expired` | ADK token expired (about 2 h): re-activate the environment ([installation guide, section 7](installation.md#7-end-to-end-checks)) |
| Step 8: "Could not get CRN" / 403 | Set `WXO_CRN` in `wxo.env` ([installation guide, section 6](installation.md#6-aws-agents-orchestrate-and-app-wiring-setup_demosh)) |
| Step 9: CodeBuild or ECR errors from another AWS account | A `.bedrock_agentcore.yaml` copied from elsewhere: `enable_tracing.sh` regenerates it for the current account; delete it by hand if needed |
| Bubble in the wrong language | `EMBED_LOCALE` in `wxo.env`, then `bash setup_demo.sh --from 8` |
| Changes in a YAML not visible in the app's bubble | Re-import and deploy the agent (`bash setup_demo.sh --only 6`); the bubble uses the **live** version |
