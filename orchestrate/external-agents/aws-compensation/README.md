# AWS Agent "Customer Goodwill" (AgentCore Runtime, A2A)

Agent for act 1. It decides the commercial gesture for an escalated ticket by applying `charter.md`, and responds in JSON. The Orchestrate escalation agent calls it via A2A 0.3.0, authenticated with OAuth (Cognito).

| File | Role |
|---|---|
| `charter.md` | The (fictional) compensation policy, injected into the agent's instructions |
| `agent.py` | The Strands agent exposed via A2A, following the same skeleton as the test agent that worked |
| `requirements.txt` | Dependencies installed in the runtime (A2A SDK limited to branch 0.3, the one used by Orchestrate) |
| `test_local.py` | Five test cases sent to the agent running locally |

## Deployment choices

- **Region**: `us-east-1`.
- **Model**: Claude Sonnet 4.5 via the `us.` inference profile, already validated on this account.
- **Incoming authentication**: OAuth authorizer with the A2A test Cognito pool. In IAM mode (the default), Orchestrate cannot call the agent due to missing SigV4 signing.
- **Container mode rather than Direct Code Deploy**: tracing to Orchestrate for Runtime agents works by patching the agent's **ECR image**. A direct code deployment has no image and therefore cannot be traced (per IBM documentation; verify before relying on tracing).

## Local testing (before any deployment)

The agent runs on the Mac; only the model calls go to Bedrock, on the AWS account of the profile used (about 1 cent per case, estimated).

Terminal 1:

```bash
cd orchestrate/external-agents/aws-compensation
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
AWS_PROFILE=dswt2026 AWS_REGION=us-east-1 .venv/bin/python agent.py
```

The agent listens on `http://127.0.0.1:9000` (port required by the AgentCore A2A contract). Verify: `curl http://127.0.0.1:9000/.well-known/agent-card.json`.

Terminal 2:

```bash
cd orchestrate/external-agents/aws-compensation
.venv/bin/python test_local.py      # all five cases
.venv/bin/python test_local.py 1    # single case
```

## Deployment from the Mac

The starter toolkit is announced as replaced by the new AgentCore CLI (`@aws/agentcore`), but it still works and is what was used for the successful A2A test with Orchestrate. Use it in non-interactive mode so the configuration is reproducible.

```bash
cd orchestrate/external-agents/aws-compensation
uv tool install bedrock-agentcore-starter-toolkit
export AWS_PROFILE=${AWS_PROFILE:-dswt2026} AGENTCORE_SUPPRESS_RECOMMENDATION=1

# Cognito pool and client for the A2A test (region us-east-1)
POOL_ID=us-east-1_XXXXXXXXX
CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxx

agentcore configure -e agent.py -n customer_goodwill_agent \
  --protocol A2A -r us-east-1 --deployment-type container \
  --requirements-file requirements.txt --disable-memory \
  --authorizer-config "{\"customJWTAuthorizer\":{\"discoveryUrl\":\"https://cognito-idp.us-east-1.amazonaws.com/${POOL_ID}/.well-known/openid-configuration\",\"allowedClients\":[\"${CLIENT_ID}\"]}}" \
  --request-header-allowlist Authorization \
  --non-interactive

agentcore deploy
agentcore status
```

The container build runs in AWS CodeBuild (no local Docker needed); the `.venv` folder is excluded. The `.bedrock_agentcore.yaml` file generated contains the account, role and ECR repository: do not copy it to another account; run `configure` again instead.

Note the agent **ARN** displayed by `status`: it is used to construct the invocation URL for Orchestrate:

```
https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/<encoded-ARN>/invocations?qualifier=DEFAULT
```

## Testing before Orchestrate

```bash
agentcore invoke '{"jsonrpc":"2.0","id":"1","method":"message/send","params":{"message":{"kind":"message","role":"user","messageId":"t1","parts":[{"kind":"text","text":"tier: gold\nservice: payments\nservice_status: outage\nrecurring_issue_same_service: true\nissue_summary: paiement refusé à plusieurs reprises pendant la panne"}]}}}'
```

Expected response in `artifacts`: a JSON object with a justification in French, `"voucher_eur": 30`, extras `free_shipping` and `priority_callback`, and `"requires_human_approval": false` (example 2 from the charter).

In case of a 424 error on invocation, check the agent's CloudWatch logs: they are far more informative than the error code.
