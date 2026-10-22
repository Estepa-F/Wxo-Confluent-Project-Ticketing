# Tools

## [`goodwill_tool.py`](goodwill_tool.py) — `ask_goodwill_agent`

Python tool used by `escalation_agent` to ask the AWS Goodwill Gesture agent (Bedrock AgentCore, A2A 0.3.0) for the gesture on one ticket. It returns the agent's JSON (voucher amount, extras, `requires_human_approval`, justification) to the escalation agent, which keeps the turn and writes its draft.

**Why a tool and not a collaborator:** declared as a collaborator, the external agent takes over the turn and its raw answer ends it; the escalation agent can never write its synthesis.

**Authentication:** OAuth2 client credentials from the Cognito pool, obtained and renewed by the Orchestrate connection `bedrock_cognito_a2a`, bound at import (`--app-id`).

`AGENTCORE_URL` in the file is a placeholder: [`../rebuild_wxo.sh`](../rebuild_wxo.sh) rewrites it from `AGENTCORE_ARN` (in `wxo.env`) in a temporary copy before importing.

[`requirements.txt`](requirements.txt): the tool's runtime dependencies.
