# Agents

## [`escalation_agent.yaml`](escalation_agent.yaml)

Native watsonx Orchestrate agent (`react_intrinsic` style) that handles **one** ticket escalated by the Confluent triage agent. It never answers the customer: it prepares a draft that the advisor reviews in `/support-admin`.

1. Receives the ticket context from the app: tier, service, service status, recurrence, subject, text, triage agent message.
2. Summarises the problem without personal data.
3. Calls the AWS Goodwill Gesture agent through the `ask_goodwill_agent` tool.
4. Returns three sections parsed by the app: `SUGGESTED REPLY`, `PROPOSED GOODWILL GESTURE`, `NOTE FOR THE ADVISOR`.

The ticket text is treated as **untrusted content**: the agent ignores instructions written in it, never takes an amount from the customer, and drafts no reply for a ticket that is not a genuine support request. The controls in [`../controls`](../controls) run before it.

Imported and deployed by [`../rebuild_wxo.sh`](../rebuild_wxo.sh). The copilot lives in [`../copilot`](../copilot).
