# Governance

The demo shows agents that act, so it also shows how they are kept under control. Governance sits at five levels, from the data to the agents running on other platforms.

## 1. Governed data (Confluent)

- **Schema Registry.** Every message on `tickets.raw`, `tickets.enriched`, `tickets.agent-actions` and `tickets.escalation-drafts` follows a registered schema (JSON Schema; Avro for `tickets.metrics`). A producer that sends a malformed ticket is rejected, so consumers and agents can rely on the shape of the data.
- **Stream Lineage.** The whole pipeline is visible as it runs: producer, Flink statements, topics.
- **Agent behaviour is data.** The triage agent's messages, model responses and tool calls (with their latency) are written to a queryable log, like any other stream.

## 2. Controls before the model (Orchestrate)

Both controls are attached to `escalation_agent` and run on `agent_pre_invoke`: they act on the ticket before the model sees it.

| Control | File | What it does |
|---|---|---|
| `pii_escalation_input` (PII filter) | [`orchestrate/controls/pii_control.yaml`](../orchestrate/controls/pii_control.yaml) | Masks emails, phone numbers, card and bank account numbers, IP addresses and dates of birth, plus three custom patterns: announced names ("my name is…", "je suis…"), order numbers (5+ digits) and French phone numbers. Replaced with `[REDACTED]`; detections are logged |
| `escalation_guardrails` (content guardrails) | [`orchestrate/controls/escalation_guardrails.yaml`](../orchestrate/controls/escalation_guardrails.yaml) | Blocks jailbreak and prompt-injection attempts, harmful, violent, biased or sexual content, on input and output (`agent_post_invoke` too). A blocked ticket gets a fixed message and no draft |

The agent's own instructions are the second line of defence: the ticket text is declared **untrusted content**, the goodwill amount always comes from the AWS agent and the policy (never from the customer), and a ticket that is not a genuine support request gets no customer reply.

The copilot has no control: only the support manager (admin) can reach it.

## 3. Human in the loop

No agent answers the customer. The escalation agent produces a draft (suggested reply, goodwill gesture, note for the advisor) that the advisor reviews, edits and sends from `/support-admin`. The AWS agent flags `requires_human_approval` when the policy demands it: a total over the €30 cap, a billing correction, or an out-of-scope request.

## 4. Traces (Orchestrate Observability)

- Each run of the escalation agent shows the control, the model call, the `ask_goodwill_agent` tool call to AWS and the answer.
- The Goodwill Policy Advisor runs on AWS but sends its own OpenTelemetry traces to Orchestrate ([`wxo_tracing.py`](../orchestrate/external-agents/aws-policy-advisor/wxo_tracing.py), enabled by [`enable_tracing.sh`](../orchestrate/external-agents/aws-policy-advisor/enable_tracing.sh)), so it has its own conversations in Observability like a native agent.

## 5. Agents on other platforms

- The two AWS agents are registered in the Orchestrate **agent directory** as external A2A agents, authenticated with OAuth client credentials (Cognito) through an Orchestrate connection: no secret in the agent definitions.
- On a larger instance, the **AI Gateway** discovers agents running on Amazon Bedrock, Gemini Enterprise or Microsoft Foundry, so they can be registered and governed instead of staying in the shadow, and the same controls apply to agents, tools and models.

## Showing it in the demo

See [scenario-demo.md](scenario-demo.md), act 3: masked data in the conversation, a blocked fake ticket, the trace of one run, then the control plane.
