# AWS Agent "Goodwill Policy Advisor" (AgentCore Runtime, A2A)

Second agent of the Customer Relations team, hosted on AWS. It answers **in prose, in English** questions about the goodwill policy (`charter.md`, the same one as the "Customer Goodwill" agent).

It is declared as a **collaborator of the Support Ops Copilot**: Orchestrate hands the turn over to this agent, whose answer is shown directly to the user. This is the opposite of `customer_goodwill_agent`, called as a tool because the escalation agent needs to post-process its JSON.

| File | Role |
|---|---|
| `agent.py` | Strands agent exposed via A2A, text response |
| `charter.md` | Copy of the policy (the AgentCore build packages only this folder) |
| `goodwill_policy_advisor.yaml` | External agent definition for Orchestrate |
| `deploy.sh` | `agentcore configure` + `deploy`, then test with a real Cognito token |
| `test.py` | A2A test of the deployed agent: `python3 test.py <ARN> "question"` |

Same Cognito pool, same client and same Orchestrate connection as `customer_goodwill_agent`: nothing to create on the OAuth side.

## Deployment

```bash
cd orchestrate/external-agents/aws-policy-advisor
bash deploy.sh
```

Then add the `POLICY_ADVISOR_ARN=…` line printed at the end to `orchestrate/wxo.env`, and:

```bash
cd ../..
bash add_policy_advisor.sh wxo.env
```

Rollback (copilot without collaborator): `bash add_policy_advisor.sh wxo.env --rollback`.
