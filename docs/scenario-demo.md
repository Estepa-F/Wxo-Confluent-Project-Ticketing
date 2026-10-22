# Demo scenario

The story of one customer ticket, in four acts, about 20 minutes. For each step: what to show, what to say, and where the "wow" moment is. The same flow is in the slide deck ([DSWT2026-demo-walkthrough.pptx](DSWT2026-demo-walkthrough.pptx)), one slide per step with the script in the speaker notes.

## Before the demo

- Generator running at a low rate (`{"action": "rate", "rate": 0.1}`), so topics move without burning Bedrock quota.
- Tabs open: the portal (`/`), `/dashboard`, `/support-admin`, Confluent Cloud (Stream Lineage, topics, Flink statements), watsonx Orchestrate (escalation agent chat, Observability, agent directory).
- A **Gold** test account ready in the portal.
- ADK token fresh if you plan to touch the CLI (it expires after about two hours).

## Opening

> "An AI is only useful in a company if it works on fresh data and if what it does is under control. Confluent takes care of the first half, watsonx Orchestrate of the second. We'll follow one customer ticket from the click to the advisor's reply."

## Act 1 — Triage in the stream (Confluent)

| # | Show | Say |
|---|---|---|
| 1 | Portal: the Gold customer opens a High-urgency ticket about a tracking status that differs between the site and the carrier, "and it's not the first time" | "From this click, the ticket is no longer a row waiting in a database. It's an event, published to Kafka, and every system that needs it gets it at the same time." |
| 2 | Stream Lineage, then the topic list | "No nightly batch: every arrow is data moving now. Each stage writes a topic another team or agent can reuse. Produce once, consume many." |
| 3 | `tickets.raw`: the customer's message and its schema | "The message follows a schema registered in Schema Registry. It's a contract: a malformed ticket is rejected, so others can reuse the stream with confidence." |
| 4 | Flink metrics statement, then `tickets.metrics` | "Flink counts tickets per service and window and calls `ML_FORECAST`. The support manager sees the spike coming before the queue explodes." |
| 5 | Enrichment statement, then `tickets.enriched` | "Each ticket is joined with the live status of its service and scored with `AI_SENTIMENT`. That's the context an agent needs to decide well." |
| 6 | `triage_agent` definition and its two MCP tools | "A Streaming Agent runs next to the data. It checks the customer's history and the known incidents through two MCP tools exposed by our portal." |
| 7 | `AI_RUN_AGENT` statement, then `tickets.agent-actions` | "For each ticket, the agent resolves or escalates. Most tickets never need a human; the ones that do arrive already qualified." |
| 8 | Portal: the ticket timeline shows *Escalated to support* | "The customer knows where they stand in seconds, not the next morning." |
| 9 | One SQL query tracing the ticket through every topic, then `triage_agent_logs` | "Everything is a stream, including the agent's behaviour: every model call and tool call is a row you can query, audit and alert on." |

## Act 2 — Escalation, human in the loop (Orchestrate + AWS)

| # | Show | Say |
|---|---|---|
| 10 | `/support-admin`: the escalation agent's proposal (suggested reply, goodwill gesture, note for the advisor) | "watsonx Orchestrate takes over. Its escalation agent drafted a reply, and asked the Customer Relations team's agent, which runs on AWS, for the goodwill gesture." |
| 11 | *Use this reply*, edit one sentence, send | "The agent prepares, the human decides. No agent answers the customer on its own." |

## Act 3 — Governance (Orchestrate)

| # | Show | Say |
|---|---|---|
| 12 | Escalation agent conversation: email, phone and name replaced by `[REDACTED]` | "Personal data is masked by a control before the model even sees it." |
| 13 | Same chat: a ticket asking the agent to ignore its instructions is blocked | "Fake tickets trying to hijack the agent are stopped by content guardrails." |
| 14 | Trace of the run: control, model call, AWS tool call, answer | "We know exactly what the agent did, and why." |
| 15 | Control plane on a larger instance: agents, usage, quality, risk; AI Gateway discovering agents on Bedrock, Gemini Enterprise, Microsoft Foundry; agent directory and controls | "In a large company there are hundreds of agents. One place to discover them, register them and apply the same rules: no shadow agents." |

## Act 4 — Ops copilot on live context (Confluent RTCE + Orchestrate)

Open the copilot bubble on `/dashboard` and ask, in this order:

1. "Which topics can you read?" — proof that the context comes from Confluent.
2. Tile **Live escalations** — the ten latest escalations and the service that concentrates them.
3. Tile **Goodwill proposals** — the drafts prepared in act 2, with their amount and whether human approval is required.
4. Tile **Goodwill policy** — "What is our goodwill rule for a gold customer hit by a recurring payments outage?", handed to the AWS Goodwill Policy Advisor (A2A collaborator).

**Wow moment:** create a ticket live (or let someone in the audience do it from the portal URL), wait for the escalation, then ask "What happened with the last escalated ticket?" The copilot describes a ticket created two minutes earlier, with the escalation agent's proposal.

> "Fresh context, not yesterday's export."

## Closing

> "Confluent turns events into decisions. watsonx Orchestrate turns decisions into controlled actions. Next step: a workshop of less than a day to find, in your company, the business event that is worth the most if you know it in under a minute."

## If something goes wrong

| Symptom on stage | Fallback |
|---|---|
| The live ticket is not escalated after two minutes | Use a ticket escalated during rehearsal; the trace query (step 9) still tells the story |
| The copilot says the live data is unavailable | Show the topics in the Confluent console instead, then the copilot's answer from rehearsal |
| An AWS agent times out | Show the proposal already in `/support-admin` and the trace in Observability |

See [troubleshooting.md](troubleshooting.md) for the fixes.
