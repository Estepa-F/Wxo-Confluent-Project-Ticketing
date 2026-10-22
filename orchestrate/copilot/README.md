# Support Ops Copilot (act 4)

watsonx Orchestrate agent that answers in French about the current state of support,
read live from Confluent topics via the Real-Time Context Engine (RTCE).

## 1. Confluent side (console)

1. **Enable RTCE on topics**: Topics → "Real-Time Context Engine" column → "Off" → enable,
   for `tickets.agent-actions`, `tickets.escalation-drafts` and `tickets.metrics`.
   Required role: OrganizationAdmin, EnvironmentAdmin, CloudClusterAdmin, or
   ResourceOwner on the topic.
2. **Create a Global API key** (not a cluster key): Administration →
   API keys → Add API key, attached to your user account. This is the step
   that failed with 403 when Terraform created it using the service account;
   try it from the console under your own account.
3. **Note the identifiers** for the MCP address:
   - `ORG_ID`: Settings → Organization settings;
   - `ENV_ID` and `LKC_ID`: `terraform -chdir=terraform/base output environment_id cluster_id`.

   Address (cluster in AWS us-east-1):
   `https://mcp.us-east-1.aws.confluent.cloud/mcp/v1/context-engine/organizations/<ORG_ID>/environments/<ENV_ID>/kafka-clusters/<LKC_ID>`

## 2. Orchestrate side (ADK, in the orchestrate/copilot folder)

Replace `SERVER_URL` in `confluent_rtce_toolkit.yaml`, then:

```
orchestrate connections add -a confluent_rtce
orchestrate connections configure -a confluent_rtce --env draft --type team --kind basic
orchestrate connections configure -a confluent_rtce --env live --type team --kind basic
orchestrate connections set-credentials -a confluent_rtce --env draft -u <GLOBAL_KEY> -p <GLOBAL_SECRET>
orchestrate connections set-credentials -a confluent_rtce --env live -u <GLOBAL_KEY> -p <GLOBAL_SECRET>
orchestrate toolkits import -f confluent_rtce_toolkit.yaml -a confluent_rtce
orchestrate tools list
```

Check in `orchestrate tools list` the exact names of the three tools
(expected: `confluent_rtce:listTopics`, `confluent_rtce:getMetadata`,
`confluent_rtce:queryData`) and update `support_ops_copilot.yaml` if needed.

```
orchestrate agents import -f support_ops_copilot.yaml
orchestrate agents deploy -n support_ops_copilot
```

Alternative without CLI: in the interface, MCP catalogue → "IBM Confluent
Real-Time Context Engine" → same address and key, as Daniel did.

## 3. Demo questions

1. "Which topics can you read?" (proof that context comes from Confluent)
2. "What were the last 5 decisions from the triage agent?"
3. "Which service has the most escalations?"
4. "Which commercial gesture proposals have been prepared, and which one
   requires human approval?"
5. Live: create a ticket from the audience, wait for escalation, then
   "What happened with the last escalated ticket?"

The "wow" moment: question 5, where the copilot describes a ticket created by
someone in the audience two minutes earlier, along with the escalation agent's
proposal.
