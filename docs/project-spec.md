# Live Support Triage Copilot — Project Spec

**Context:** 45-minute technical demo for Data Streaming World Tour Paris,
mixed tech/architect audience. Live, audience-participation demo showcasing
Confluent's Flink + AI/ML functions + Streaming Agents (tool calling) +
Real-Time Context Engine, closing with a watsonx Orchestrate "Support Ops
Copilot" agent answering live questions on stage.

**Status as of this update:** the system described below is built and
deployed end-to-end (Confluent Cloud platform, the support_portal app on
AWS ECS, the Flink enrichment/metrics/agent pipeline, RTCE, and the
watsonx Orchestrate agent) — including a full ticket-lifecycle subsystem
(section 2.2) and a human-facing Support Admin queue (section 2.8) added
since earlier versions of this document. Several pipeline assumptions
from the initial build also turned out to be wrong once things ran
against real Confluent Cloud/Bedrock services and were corrected live —
see 2.5/2.6 in particular. The main remaining work is rehearsal and
tuning — see section 6.

Companion files:
- `docs/architecture.md` — current architecture diagram
  (kept in sync with this spec)
- `app/support_portal/` — the actual deployed app (see section 2.4; this
  superseded the originally-planned standalone `support_portal_mock.py`)
- `docs/specs/ticket-lifecycle/spec.md` — detailed spec for the ticket
  lifecycle subsystem (section 2.2): states, UI, demo walkthrough
- `docs/specs/dashboard/spec.md` — detailed spec for the presenter dashboard's
  Live Triage Stream table (section 2.8)
- `docs/specs/ticket-management/spec.md` — detailed spec for the Support
  Admin surface (section 2.8): escalated queue, human reply, retiring
  the old presenter console

This document describes what was built, the data contracts between
pieces, what's explicitly out of scope, and what's still genuinely open
pending rehearsal. It stays at the project-overview level; the three
`specs/` files above are the canonical, detailed specs for their areas
and should be updated there first if those areas change again.

---

## 1. Narrative (for context, not implementation)

Attendees scan a QR code, land on a simple phone web form, and submit a
mock e-commerce support ticket (free text + self-rated urgency) at one or
more points during the talk. Each submitted ticket is now a followable
thing, not fire-and-forget: attendees can revisit their ticket list,
see the triage decision as it lands, reply if it didn't help (which
re-triggers triage), and close it out (section 2.2). A synthetic ticket
generator runs continuously alongside real submissions so the demo never
depends on live attendance volume. At a cued moment, the presenter
triggers a spike (asks the room to submit tickets about a specific
topic) which correlates with a status-page incident flipped live, and
the pipeline visibly detects, matches, and routes it. Tickets the agent
escalates instead of auto-resolving land in a Support Admin queue
(section 2.8) that a human (presenter or plant) can work live on stage —
closing the loop between the AI triage step and a person actually
answering — before the talk ends with a live Q&A against a watsonx
Orchestrate agent that answers questions about the room's ticket
activity in real time.

---

## 2. Components built

### 2.1 Ticket submission front end — RESOLVED
- Minimal phone web page (`app/support_portal/static/new-ticket.html`),
  QR-code accessible, no login, plain vanilla JS.
- Check-in and the ticket form are now the **same page/route**: on
  `GET /` (`pages.ticket_page` in `app/support_portal/pages.py`),
  first-visit attendees are checked in against the pre-seeded account
  pool (assigning `user_id`/`tier` cookies) and served `new-ticket.html`
  directly — there's no separate `/register` call or `intake.html`
  anymore. If the account pool is exhausted, the same route serves
  `full.html` (503) instead (see 2.8's site map for its repurposed
  role).
- `new-ticket.html` is pre-rendered once at import time
  (`pages.py`'s `_render_new_ticket_html()`) with
  `window.TICKET_SAMPLES` inlined from `tickets/samples.py`, powering a
  "✨ Generate a random ticket" button.
- Form fields: free-text ticket description, self-rated urgency
  (low/medium/high).
- On submit: `POST /api/tickets` (`app/support_portal/tickets/routes.py`
  — see 2.2), which reads the `user_id` cookie, builds a `TicketRaw`
  model, and calls `TicketProducer.produce_model("tickets.raw", ...)`
  (`app/support_portal/messaging/producer.py`) to produce **directly**
  to Confluent Cloud via `confluent-kafka`, JSON-Schema-serialized
  against Schema Registry. This mechanism itself is unchanged from the
  original design — no REST Proxy or serverless function, the backend
  app itself is the producer.
- The MCP sub-app is mounted at `/` (catch-all, registered last in
  `app/support_portal/main.py`), with all FastAPI routers registered
  first so they take priority; `mcp_server.session_manager.run()` is
  entered explicitly inside the app's `lifespan`, since Starlette
  doesn't propagate a mounted sub-app's lifespan automatically.

### 2.2 Ticket lifecycle — RESOLVED (new subsystem, not in the previous spec)
Tickets are no longer fire-and-forget. `app/support_portal/tickets/`
gives every submitted ticket a followable lifecycle, matching
`docs/specs/ticket-lifecycle/spec.md` (the canonical detailed spec for this
area — states, UI layout, full demo walkthrough):

- **Model** (`tickets/models.py`): `TicketStatus` is just `open`/`closed`
  (`closed` is the only terminal state). The richer axis is
  `TicketEventType` — `ticket_created`, `automatic_reply`, `escalated`,
  `user_reply`, `support_reply`, `ticket_closed` — forming a timeline
  per ticket. Status is derived from the latest event: anything flips
  it to `open` except `ticket_closed`.
- **Lifecycle loop**: `Ticket created → Triage → {Automatic reply |
  Escalated} → User reply → Triage → ... → Closed`. Critically, a
  **user reply re-enters triage** — it's republished to `tickets.raw`
  with the full conversation-so-far as `text` (`store.py`'s
  `conversation_context()`), not treated as a passive comment.
- **Store** (`tickets/store.py`): `TicketStore`, an in-memory,
  thread-locked dict keyed by `ticket_id` — not Kafka-backed, not
  persisted, same "lives only for process lifetime" trade-off as
  `AccountPool`/`PortalState`. `apply_agent_action()` maps a parsed
  triage decision (see 2.6 — `AI_RUN_AGENT`'s real output has no
  structured `action` field, so `tickets/service.py`'s
  `parse_agent_response()` extracts `auto_resolve`/`escalate` from the
  agent's free-text response first) onto `automatic_reply`/`escalated`
  events. `set_sentiment()`/`list_escalated()` back the two features
  below.
- **No fallback escalation anymore.** An earlier revision started a
  30-second timer on every ticket creation/reply and synthesized its own
  escalation if the real Flink pipeline hadn't responded in time. That
  timer (`FALLBACK_TIMEOUT_SECONDS`/`schedule_fallback`/
  `cancel_fallback`) has since been removed from `tickets/service.py`
  entirely — every ticket now waits on a real `tickets.agent-actions`
  message with nothing standing in for the pipeline if it stalls. **Not
  yet reconfirmed against section 5's "reliability over completeness"
  principle** — flagged in section 4 as something to revisit before the
  live session, not silently re-added here.
- **Sentiment threading**: `TicketSummary`/`TicketDetail` carry an
  optional `sentiment` (`positive`/`neutral`/`negative`), set once from
  `tickets.agent-actions`' passthrough `sentiment_analysis` column the
  first time a message for that ticket carries one (never overwritten
  back to absent by a later message without it) — the same value
  `AI_SENTIMENT` computes in 2.5, now visible on the ticket itself and
  surfaced in the Support Admin queue (2.8).
- **REST/WS surface** (`tickets/routes.py`), all cookie-gated by
  `user_id`: `POST /api/tickets` (create), `GET /api/tickets` (list
  own), `GET /api/tickets/{id}` (detail, 403/404 enforced),
  `POST /api/tickets/{id}/replies` (reply — rejected 400 if closed),
  `POST /api/tickets/{id}/close`, and `WS /ws/tickets/{id}` (initial
  snapshot + live `ticket_event` pushes as agent actions/replies land).
  Pages: `GET /tickets` (list) and `GET /tickets/{id}` (detail) — see
  2.8's site map.
- **Sample content**: `tickets/samples.py` loads `tickets/tickets.csv`
  (1019 rows across the six services) into
  `TICKET_SAMPLES_BY_SERVICE`, powering both the "generate a random
  ticket" UI button (2.1) and the synthetic generator (2.3).
- Internal pipeline details (Kafka topic/offset, Flink job/agent name,
  MCP tool calls, model name, confidence score) never surface in the
  attendee-facing UI — only the resulting message/decision does.

### 2.3 Synthetic ticket generator — RESOLVED
- Consolidated into a single module,
  `app/support_portal/generator/synthetic.py` (the earlier
  `baseline.py`/`burst.py`/`phrasing_bank.py` split no longer exists).
  It still has both modes:
  - `BaselineGenerator` — same asyncio-loop shape as before
    (`start/stop/pause/resume/set_rate`), driven by
    `settings.enable_generator`/`settings.generator_rate` from
    `main.py`'s lifespan.
  - `fire_burst()` — still async, still `(producer, service, count,
    interval_ms)`, still invoked from `admin/routes.py`'s
    `POST /admin/burst` (including the "all services" fan-out case).
- **Content source changed**: both modes now draw from
  `tickets/samples.py`'s `TICKET_SAMPLES_BY_SERVICE` (section 2.2's
  1019-row `tickets.csv`) instead of hand-written phrasing banks —
  unifying what used to be three separate content sources (baseline
  phrasings, burst phrasings, and nothing for the UI) into one.
- **New: health-weighted selection.** `HEALTH_WEIGHTS`
  (`operational=1.0, degraded=2.0, outage=4.0`) and
  `URGENCY_WEIGHTS_BY_HEALTH` bias which service and urgency get
  picked, read live from `PortalState.get_service_status()` — so a
  degraded/outage service automatically generates more and worse
  tickets, with no manual scripting needed.
- **Burst candidates are computed, not hand-tagged**:
  `BURST_CANDIDATES_BY_SERVICE` is built once at import time by
  actually running `search_known_issues()` against every `tickets.csv`
  row per service and keeping only genuine fuzzy-matches — see the
  updated note in section 4 (this used to be a hand-tagged mapping).
- **Synthetic tickets are now real ticket records.** Both `emit_ticket`
  and `fire_burst` call `tickets_service.store.create(...)` before
  producing to Kafka, so a synthetic ticket gets a real `TicketRecord`
  (keyed by the same `ticket_id` that goes on the wire) instead of just
  a bare UUID string — needed so `handle_agent_action` (2.2) can find it
  when the real decision comes back, instead of silently no-op'ing on
  an unknown id. Synthetic accounts are excluded by default from the
  Support Admin queue (2.8) via `accounts/pool.py`'s
  `is_synthetic_user_id()` — there's no real person behind one to reply
  to.
- **`generator_rate` default dropped from 0.5 to 0.1 tickets/sec**
  (`config.py`) — with all six services weighted equally when healthy,
  that averages to ~1 ticket/min/service, sized so the synthetic
  baseline doesn't compete with real attendee tickets for the shared
  Flink compute pool's `AI_RUN_AGENT` capacity (see 2.5's CFU note).

### 2.4 support_portal app — RESOLVED (consolidated, package layout updated)
Originally planned as a separate mock-server file
(`support_portal_mock.py`); in the actual build the front end (2.1),
ticket lifecycle (2.2), and dashboard (2.8) are all **one deployed
FastAPI app** (`app/support_portal/`, one Docker image — see 2.9)
rather than separate services. The package layout has moved from a flat
`routes/` module to per-domain packages: `pages.py` (top-level page
routes) plus `tickets/`, `dashboard/`, `admin/`, `incidents/`,
`mcp/server.py` (was a top-level `mcp_server.py`), `messaging/` (was
`kafka/`).

**MCP tools** (called by the Flink `triage_agent` via MCP tool
invocation, `app/support_portal/mcp/server.py`) — signatures and return
shapes are **unchanged**:
- `search_known_issues(ticket_text: str) -> dict` — fuzzy-matches
  (`rapidfuzz`) against a known-issues dataset. Returns `matched`,
  `issue_id`, `service`, `suggested_fix`, `confidence`.
- `get_account_context(user_id: int, service_hint: str = "") -> dict` —
  looks up a pre-seeded fake account (tier, recent ticket history capped
  at 5, `recurring_issue_same_service` flag). The agent's prompt calls
  `search_known_issues` first and threads its `service` result into
  this call as `service_hint`.

**What changed underneath `search_known_issues`**: the static Python
list the original design used has been replaced by
`incidents/knowledge_base.csv` — 76 KB articles (`KB-0001`...`KB-0076`)
with `article_id, title, description, symptoms, apply_to, resolution,
steps_to_fix` columns, covering all six services with real
troubleshooting detail. `incidents/known_issues.py` now loads this CSV
at import (`_load()`) instead of defining issues inline; the
`search_known_issues()` function signature callers depend on is
unchanged.

**MCP mount now requires HTTP Basic auth** (`main.py`'s
`MCPBasicAuthMiddleware`, credentials in `config.py`'s
`mcp_username`/`mcp_password`). It used to have no auth of its own
(only the Host-header allowlist below) — confirmed live that
unrelated bot/scanner traffic was already probing the open `/mcp`
endpoint on the public URL, so it's no longer left as a fully open
data-lookup surface. Confluent's `portal_mcp_connection` (2.6) supplies
the matching credential, generated by Terraform
(`terraform/app-hosting`'s `random_password.mcp_password`) and read
into the `confluent-intelligence` stage via `terraform_remote_state`.

**Plain REST endpoints** (no MCP involved):
- `GET /status` / `POST /admin/status` — current per-service status
  (six mock e-commerce services: `login`, `checkout`, `payments`,
  `search`, `notifications`, `order-tracking`) plus open mock incidents,
  tracked by `incidents/state.py`'s `PortalState`. Mutated live
  (manually, via the presenter dashboard — see 2.8's "Presenter console
  retired") right before the on-cue incident trigger, and also read
  live by the generator's health-weighting (2.3).

**Descoped**: the original design called for the Flink agent to call
`GET /status` as a function/UDF-style tool. This was **not built** — no
UDF JAR exists in the repo, and the corresponding Terraform resources
in `terraform/confluent-intelligence/03_statements_triage_agent.tf` are
commented out, unused. `/status`/`/admin/status` still exist and drive
the dashboard and the live incident flip — they're just not consumed by
the Flink agent's triage decision. The `triage_agent` relies only on the
two MCP tools above.

### 2.5 Confluent Cloud — Flink SQL jobs — RESOLVED (with caveats)

**Ticket enrichment** (`terraform/confluent-intelligence/02_statements_ticket_enrichment.tf`):
```sql
CREATE TABLE `tickets.enriched`
DISTRIBUTED BY (ticket_id) INTO 2 BUCKETS
WITH (
  'value.format' = 'json-registry'
) AS
SELECT
  ticket_id,
  user_id,
  service,
  text,
  urgency_self_rated,
  AI_SENTIMENT(text, ARRAY[service]) AS sentiment_analysis,
  CURRENT_TIMESTAMP AS enriched_at
FROM `tickets.raw`;
```
**Real `AI_SENTIMENT` call, not a placeholder**: `AI_SENTIMENT` is now
enabled for this environment, replacing the earlier random-pick
placeholder used during the initial build (kept only so the rest of the
pipeline — `triage_agent`, dashboard — could be built/tested before
`AI_SENTIMENT`'s syntax and per-aspect return shape were confirmed).
`sentiment_analysis` is kept as a whole
`ROW<sentiment ARRAY<ROW<aspect, label, score>>, metadata>` rather than
decomposed in SQL, same reasoning as `forecast` below — the app derives
a flat `sentiment` string from `sentiment_analysis.sentiment[0].label`
(`dashboard/service.py`'s `handle_message`, `tickets/service.py`'s
`extract_sentiment`) for the dashboard and the ticket record, which
expect an exact `positive`/`negative`/`neutral` match (`AI_SENTIMENT`'s
real label is capitalized and can come back `UNKNOWN` when it can't
find the aspect discussed in the text — both handlers lowercase and
drop `unknown` as "no signal" rather than let it skew a bucket).

- **Aspect argument corrected from `ARRAY['urgency']` to
  `ARRAY[service]`.** `AI_SENTIMENT` is *aspect-based* sentiment
  analysis — the aspect must be a concrete topic actually discussed in
  the text (Confluent's own docs examples: `'battery'`, `'shipping'`),
  not an abstract property of the message like "urgency", which
  customers never write about. `service` (the ticket's own column) is
  the real topic, and is accepted as a per-row dynamic expression rather
  than a literal.
- **`AI_SENTIMENT` is only available in `us-east-1` at the time of
  building this** — the `eu-west-1` attempt returned phase `DEGRADED`
  with a generic internal error, no explicit access-denied message. The
  Confluent Cloud environment for this demo is deployed in `us-east-1`
  as a result (see 2.6's Bedrock note for the matching AWS-side
  adjustment); `terraform/base/variables.tf`'s `region` variable still
  *defaults* to `eu-west-1` for portability, so this is set via
  `TF_VAR_region`/`credentials.env`, not a code default. **Recheck this
  region restriction before relying on it** — first-party regional GA
  availability for AI functions changes over time.
- **`DISTRIBUTED BY (ticket_id) INTO 2 BUCKETS`** — without it, this
  plain append-only CTAS (no `PRIMARY KEY`) ships with a null Kafka key,
  so `tickets.raw`'s own per-`ticket_id` partition affinity (2
  partitions, `terraform/base/main.tf`) is lost and `tickets.enriched`
  messages land round-robin instead. Confirmed live against a disposable
  test table that this syntax is accepted without a `PRIMARY KEY` (the
  documented examples only pair it with one).
- Resulting schema: `ticket_id, user_id, service, text, urgency_self_rated,
  sentiment_analysis (ROW), enriched_at`.

**Ticket metrics** (`terraform/confluent-intelligence/01_statements_ticket_metrics.tf`):
```sql
CREATE TABLE `tickets.metrics` (
  PRIMARY KEY (window_end, window_start, service) NOT ENFORCED
) WITH (
  'changelog.mode' = 'upsert'
) AS
SELECT
  window_end,
  window_start,
  COALESCE(service, 'unknown') AS service,
  COUNT(*) AS ticket_count,
  ML_FORECAST(
    CAST(COUNT(*) AS DOUBLE),
    window_end,
    CAST(JSON_OBJECT('minTrainingSize' VALUE 3, 'enableStl' VALUE false, 'horizon' VALUE 2) AS STRING)
  ) OVER (
    PARTITION BY COALESCE(service, 'unknown')
    ORDER BY window_end
    RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
  ) AS forecast
FROM TABLE(
  TUMBLE(TABLE `tickets.raw`, DESCRIPTOR($rowtime), INTERVAL '15' MINUTE)
)
GROUP BY window_start, window_end, COALESCE(service, 'unknown');
```
Window/horizon/`minTrainingSize` are sized for a live demo, not
statistical rigor: a 15-minute tumble (widened from 1 minute, which was
too fine-grained to read as a trend), `horizon=2` (forecast is 2 x
15min = 30 minutes ahead), `minTrainingSize=3` (dropped from 10, which
needed 2.5h of history before forecasting anything — too long for most
demo sessions).
- Uses `ML_FORECAST` (GA, ARIMA-based), **not** `AI_FORECAST` (EA) —
  `AI_FORECAST` consistently failed with "does not exist"; its EA access
  is gated by a sign-up program this org isn't enrolled in, with no
  GRANT/RBAC path. `ML_FORECAST` was the anticipated GA fallback.
- **Now partitioned per service, not one global forecast** — fixes
  three Confluent Cloud query-health warnings confirmed live against the
  earlier version: `UPSERT_AND_PRIMARY_KEYS_DIFFERENT` (the declared
  `PRIMARY KEY` must match the `GROUP BY` key exactly, or Flink inserts
  an extra state-heavy `UpsertMaterialize` operator), and
  `MISSING_PARTITION_BY_FOR_OVER_WINDOW` (the `OVER(...)` had no
  `PARTITION BY`, so it ran as one non-parallel task computing a single
  global forecast — `PARTITION BY COALESCE(service, 'unknown')` gives
  `ML_FORECAST` a real key and genuine parallelism, one running forecast
  per service). `service` must be wrapped in `COALESCE(..., 'unknown')`
  everywhere it's grouped/partitioned/selected — a bare nullable
  `service` column fails `PRIMARY KEY` validation ("Column 'service' is
  nullable"). The app (`dashboard/service.py`) keeps metrics keyed by
  service — the dashboard shows one actual + one forecast line per
  service instead of a single global rollup.
- Also fixes `HIGH_STATE_OPERATOR_WITHOUT_TTL`: the
  `OVER(...UNBOUNDED PRECEDING)` operator's state would otherwise grow
  forever. Set via `'sql.state-ttl' = '1 DAY'` in this statement's own
  `properties` (Confluent Cloud Flink's per-statement equivalent of
  `SET 'sql.state-ttl'`), not the shared `flink_statement_context`, so
  it doesn't affect the other statements in this phase.
- `tickets.metrics` is an **upsert**-mode table, converted from the
  planner's default retract classification — combining the
  tumbling-window `GROUP BY` with `OVER(...UNBOUNDED PRECEDING)` around
  `ML_FORECAST` means a forecast for an already-emitted
  `(window_end, service)` can legitimately be revised, so the planner
  marks the output as retract by default, and RTCE's query tool only
  supports append or upsert. Upsert is the semantically correct target,
  not forcing append.
- Resulting schema: `window_end, window_start, service, ticket_count,
  forecast` (key columns first, in the same order as the `PRIMARY KEY`
  — Confluent Cloud Flink requires both), where `forecast` is a single
  `ROW(actual_value, aic, forecast_value, lower_bound, rmse, timestamp,
  upper_bound)` kept as-is rather than decomposed in SQL.
- `tickets.raw`'s own `submitted_at` came in as VARCHAR and can't be used
  for `TUMBLE` directly; the statement uses Confluent Cloud Flink's
  system-provided `$rowtime` metadata column (Kafka record timestamp)
  instead of touching the table's watermark.
- **Stays on Flink's default `avro-registry` value format** (no
  `value.format` override), unlike `tickets.enriched`/
  `tickets.agent-actions` above/below — confirmed live that
  `ML_FORECAST`'s `ROW` result carries a `TIMESTAMP(6)` field, and
  Confluent Cloud's `json-registry` format only supports `TIMESTAMP`
  precision ≤ 3 (`CREATE TABLE ... WITH ('value.format' =
  'json-registry')` fails outright on this statement). The app's
  `DashboardConsumer` (`messaging/consumer.py`) therefore uses a
  dedicated `AvroDeserializer` for this one topic instead of the shared
  `JSONDeserializer` used everywhere else, and merges the Avro message
  key (which is where `window_end` actually lives for this table) back
  into the value before dispatch.
- **`intelligence_flink_max_cfu` bumped from 5 to 10** — the
  provider's small default wasn't enough to keep the `triage_agent`'s
  per-ticket `AI_RUN_AGENT` call (a real LLM round-trip) responsive
  under demo traffic.
- **Re-applying a changed statement isn't a plain Terraform update**:
  neither this table nor `tickets.enriched` above use `IF NOT EXISTS`,
  so changing the statement text (e.g. the window size or the
  `PARTITION BY` addition) fails with "table already exists" until the
  table is manually dropped first (`DROP TABLE ...;` in the Flink SQL
  workspace) — Terraform can't safely automate dropping a live table as
  a side effect of a statement-text change.

### 2.6 Streaming Agent (on Flink) — RESOLVED (simplified design)
Originally planned as four chained agents (`LOOKUPAGENT` → `TRIAGEAGENT`
→ `AUTOAGENT`/`ESCALATEAGENT`). Built instead as a **single** agent,
because Confluent Streaming Agents has no native agent-to-agent
handoff/branching primitive. From
`terraform/confluent-intelligence/03_statements_triage_agent.tf`:

```sql
CREATE AGENT triage_agent
  USING MODEL `triage_agent_model`
  USING PROMPT 'You are a support triage agent for an e-commerce
    platform. The input contains "User ID: <id>" followed by the
    ticket text. For each ticket: first call search_known_issues
    with the ticket text; then call get_account_context passing the
    User ID from the input as user_id and the service from step 1
    as service_hint; then decide whether to auto-resolve (known
    issue matched above threshold) or escalate. Respond with
    EXACTLY two lines and nothing else -- no other commentary,
    markdown, or headings:
    DECISION: AUTO_RESOLVE
    MESSAGE: <one-paragraph customer-facing message>
    (or DECISION: ESCALATE with its own MESSAGE line).'
  USING TOOLS search_known_issues_tool, get_account_context_tool
  WITH ('max_iterations' = '10', 'max_consecutive_failures' = '3');
```

**Prompt rewritten twice from the original**, based on live evidence
once the agent actually ran end-to-end (everything before that had
always died earlier in the connection/auth/deserialization chain, so
this was the first real feedback on the agent's own behavior):
- The input now carries `"User ID: <id>"` ahead of the ticket text (see
  `run_triage_agent` below) — real responses showed the agent asking the
  human "please provide your user ID" instead of calling
  `get_account_context`, since it was never actually given one before.
- The old free-form "produce that decision with a short message"
  instruction let the model answer however it liked, and some real
  responses never stated a decision at all. The app needs a
  deterministic decision to drive the ticket UI/escalation topic, so the
  prompt now demands an exact, parseable two-line `DECISION:`/`MESSAGE:`
  output instead (see below).

**`AI_RUN_AGENT`'s actual output has no structured decision field** —
confirmed live it's just `{status, response}`, `response` being
whatever free text the model produced. `tickets/service.py`'s
`parse_agent_response()` (shared with `dashboard/service.py` so both the
customer-facing ticket UI and the presenter dashboard agree on the same
decision for the same message) regex-parses the `DECISION:`/`MESSAGE:`
lines the prompt above demands, falling back to `escalate` — never a
silent auto-resolve — if the model doesn't follow that contract.

Both tools are MCP-backed, over the same connection to the deployed
app's `/mcp` endpoint (see 2.9), now with real HTTP Basic auth (2.4):
```sql
CREATE CONNECTION portal_mcp_connection
WITH (
  'type' = 'mcp_server',
  'endpoint' = '<app_public_url>/mcp',
  'transport-type' = 'STREAMABLE_HTTP',
  'username' = 'flink-agent',
  'password' = '<terraform-generated>'
);

CREATE TOOL search_known_issues_tool USING CONNECTION portal_mcp_connection
WITH ('type' = 'mcp', 'allowed_tools' = 'search_known_issues');

CREATE TOOL get_account_context_tool USING CONNECTION portal_mcp_connection
WITH ('type' = 'mcp', 'allowed_tools' = 'get_account_context');
```
Confirmed live: two of Confluent's four supported `mcp_server` auth
methods (`api-key`, `token`) were rejected identically and client-side
(never even reaching the app) when tried with a placeholder credential
— Basic auth with a real, checkable credential (2.4) was the
combination that actually worked.

Output is wired via `run_triage_agent`, unaliased per Confluent's
documented `LATERAL TABLE` pattern (an aliased `AS result` +
`SELECT result.*` fails to parse):
```sql
CREATE TABLE `tickets.agent-actions` WITH (
  'value.format' = 'json-registry'
) AS
SELECT *
FROM `tickets.enriched` /*+ OPTIONS('scan.startup.mode' = 'latest-offset') */,
LATERAL TABLE(AI_RUN_AGENT(
  'triage_agent',
  CONCAT('User ID: ', CAST(`tickets.enriched`.user_id AS STRING), CHR(10), 'Ticket: ', `tickets.enriched`.text),
  `tickets.enriched`.ticket_id
));
```
`user_id` is baked directly into the single free-text input column
rather than passed alongside it — `AI_RUN_AGENT`'s second argument is
one plain string, with no separate structured-input parameter.
`scan.startup.mode = 'latest-offset'` is required because this job has
no checkpoint to carry over each time it's recreated, and Confluent
Cloud Flink's table default (`earliest-offset`) would otherwise replay
`tickets.enriched` from offset 0 on every restart — including old
records from before `ticket_id` was added to that table's `SELECT`,
which the current schema can't deserialize and which would kill the job
before it processes anything current. This is also just correct
behavior for a live triage agent regardless: it should react to new
tickets going forward, not replay history.

`triage_agent_model` is backed by Bedrock Claude Sonnet 4.5 via a
cross-region inference profile whose prefix depends on region
(`local.bedrock_inference_profile_prefix`, currently mapping
`eu-west-1 → eu`, `us-east-1 → us`; re-confirm live before adding a new
region — AWS's own geography-prefix convention isn't a reliable guess,
e.g. APAC profiles use `apac.`, not `ap.`). The Bedrock connection
authenticates with a dedicated, narrowly-scoped IAM user
(`terraform/confluent-intelligence/bedrock_iam.tf`, `bedrock:InvokeModel`
only, Anthropic models only, resource wildcarded across regions since a
geographic inference profile can transparently route to any of several
destination regions and IAM checks against whichever one it actually
lands on), created independently of `app-hosting`'s own AWS footprint
so the common case (`intelligence_enable_bedrock_model = false`) never
touches AWS at all.
No `check_status` tool (see 2.4) — the `triage_agent` relies only on
the two MCP tools above, and the `agent-actions` output feeds both the
dashboard (2.8) and the ticket lifecycle (2.2) via
`tickets.agent-actions`.

### 2.7 Real-Time Context Engine (RTCE) + watsonx Orchestrate — RESOLVED
- RTCE indexes `tickets.enriched`, `tickets.metrics`, and
  `tickets.agent-actions`. Confirmed AWS-only, and this Confluent Cloud
  environment is provisioned on AWS throughout — currently `us-east-1`
  (see 2.5's `AI_SENTIMENT` region note).
- RTCE has no Terraform resource type — enabling it per topic is a
  **manual Console step** (Topics → Context engine column). Terraform
  (`terraform/confluent-intelligence/rtce.tf`) only provisions the
  querying credential: a Global `confluent_api_key`, exposed via
  outputs `rtce_api_key`/`rtce_api_secret`, plus a composed
  `rtce_mcp_endpoint` (`https://mcp.<region>.aws.confluent.cloud/mcp/v1/context-engine/organizations/<org_id>/environments/<env_id>/kafka-clusters/<lkc_id>`)
  and a precomputed `rtce_basic_auth_token` (`base64(api_key:api_secret)`
  for the `Authorization: Basic` header).
- **Operational gotcha**: the RTCE toggle must be redone in the Console
  any time the underlying topic is dropped and recreated — this
  happened once already for `tickets.metrics` during the retract→upsert
  conversion above.
- A watsonx Orchestrate agent ("Support Ops Copilot") queries RTCE via
  MCP (either IBM's catalog-managed Confluent MCP connector, or a custom
  MCP toolkit pointed at `rtce_mcp_endpoint` with the Basic auth token),
  answering live on-stage questions about ticket volume/trend/forecast,
  sentiment/urgency, and auto-resolve/escalate activity. Its system
  prompt is authored and iterated in Orchestrate itself (not
  version-controlled in this repo); it explicitly derives "now" from
  `MAX(window_end)` in `tickets_metrics` since RTCE/Orchestrate has no
  built-in current-time awareness.

### 2.8 Live dashboard + Support Admin — RESOLVED
- Plain HTML/CSS/vanilla JS (`app/support_portal/static/dashboard.html`),
  no frontend framework; charting via Chart.js loaded from CDN. Detailed
  layout/data-model spec for its Live Triage Stream table:
  `docs/specs/dashboard/spec.md`.
- The module split into `dashboard/service.py` (aggregation/state) and
  `dashboard/routes.py` (transport only — `GET /ws/dashboard`), instead
  of one flat `routes/dashboard.py`. `service.py`'s `snapshot()` now
  covers considerably more server-side state than the original
  `_urgency_counts`/`_recent_metrics`/`_recent_actions`/`_last_status`/
  `_counters` shape — per-service ticket totals, a rolling
  sentiment window, per-service recent-timestamp lists (for a
  tickets/sec sparkline), and a capped incident-change log. This state
  used to live only in `dashboard.html`'s own JS (reset to empty on
  every reload or new tab); moving it server-side means a reloaded
  dashboard rebuilds its view from `snapshot()` instead of starting
  blank. `_recent_metrics` is also now keyed per-service (`service ->
  window_end -> row`), matching 2.5's partitioned `tickets.metrics`.
- **New integration point**: `tickets.agent-actions` now fans out to
  *two* handlers — `dashboard_service.handle_message` (as before) and
  `tickets_service.handle_agent_action` (section 2.2) — so a single
  agent decision updates both the presenter dashboard and the
  attendee's own ticket timeline, using the same
  `parse_agent_response()` (2.6) in both places so they never disagree
  on what a given message means.
- Shows: urgency distribution, per-service ticket-volume trend +
  forecast, live status-page state, and a full-width **Live Triage
  Stream** table (Time/Ticket ID/Service/Sentiment/Action/Ticket, with
  Service/Sentiment/Action filters) replacing the earlier
  batched-counts activity feed — see `docs/specs/dashboard/spec.md` for the
  detailed layout.
- **Presenter console retired.** The old `static/console.html`
  (incident flip + burst trigger, driven from its own separate browser
  tab) is gone — those two controls are now driven directly from
  `dashboard.html` itself, so the presenter only ever needs the one tab
  on stage. The underlying `/admin/status` and `/admin/burst` **routes**
  in `admin/routes.py` are unchanged; only the front end that calls them
  moved.
- **New: Support Admin surface** (`static/support-admin.html`,
  `docs/specs/ticket-management/spec.md` is the canonical detailed spec) —
  a human-facing screen for the escalated-ticket queue this system
  otherwise has no way to act on: an escalated queue list (oldest-
  waiting-first, synthetic tickets excluded by default) and a per-ticket
  reply screen. Backed by three new `admin/routes.py` endpoints:
  `GET /admin/tickets/escalated` (`TicketStore.list_escalated()` — a
  ticket is "in queue" purely from its latest event being `escalated`,
  no separate flag), `GET /admin/tickets/{id}` (admin-token-gated
  ticket detail, no customer cookie required), and
  `POST /admin/tickets/{id}/support-reply` (`tickets_service
  .apply_support_reply()` — appends a `support_reply` event and
  broadcasts over the ticket's own WebSocket; does **not** republish to
  `tickets.raw`, since a human's answer is terminal, not something that
  should re-trigger AI triage). The queue view polls rather than adding
  a new all-tickets WebSocket channel — an explicit, accepted trade-off
  for now, not an oversight.
- Site map (`app/support_portal/pages.py`, `tickets/routes.py`,
  `admin/routes.py`):

  | Path | Serves | Notes |
  |---|---|---|
  | `GET /` | `new-ticket.html` | Check-in + ticket form (2.1) |
  | `GET /tickets` | `tickets.html` | Attendee's own ticket list (2.2) |
  | `GET /tickets/{id}` | `ticket-detail.html` | Single ticket, live via WS (2.2) |
  | `GET /dashboard` | `dashboard.html` | Presenter-facing live ops dashboard, now also hosting incident/burst/generator controls |
  | `GET /support-admin` | `support-admin.html` | Human agent queue for escalated tickets + replies (new) |
  | `GET /status` | JSON | Current per-service status |
  | (fallback) | `full.html` | Capacity-exhausted (503) page — repurposed; no longer a combined embed view |

  `theme.css`/`theme.js` are shared across every page (dark/light theme
  toggle). `intake.html` no longer exists — functionally replaced by
  `new-ticket.html` served at `/`. `console.html` no longer exists —
  see "Presenter console retired" above.

### 2.9 App hosting/deployment — RESOLVED
The whole app (2.1, 2.2, 2.4, 2.8) is one Docker image deployed to AWS
ECS via ECS Express Gateway — a single Terraform resource
(`aws_ecs_express_gateway_service`, `terraform/app-hosting/`) providing
Fargate + ALB + TLS together, giving a public HTTPS ingress URL required
for the Flink Streaming Agent to reach the app's `/mcp` endpoint and for
the dashboard's WebSocket.

**CloudFront now sits in front of the Express service**
(`terraform/app-hosting/cloudfront.tf`), purely to get a public hostname
that stays fixed even when the Express service itself is torn down and
recreated (which changes its auto-generated `*.ecs.<region>.on.aws`
hostname). CloudFront allocates its `*.cloudfront.net` domain once, at
creation; updating a distribution's origin afterwards is an in-place
update, not a replacement. `outputs.tf`'s `app_public_url` (the stable
CloudFront URL) is now what `MCP_ALLOWED_HOSTS` and
`confluent-intelligence`'s `app_public_url` should reference —
`ingress_url` (the raw Express endpoint) is kept only for debugging.
Confirmed live: Express Mode's ALB routes purely on the `Host` header,
matching only the exact `*.ecs.<region>.on.aws` hostname it was created
with, so CloudFront's origin request policy
(`Managed-AllViewerExceptHostHeader`) deliberately leaves `Host` alone
rather than forwarding the viewer's own CloudFront domain — otherwise
the ALB's default action returns a bare "Not Found".

Bootstrapped in three passes (see `deploy.py`'s `deploy_app_hosting`):
1. Create just the ECR repo and the CloudFront distribution (targeted
   apply, pointed at a placeholder origin) — `aws_ecs_express_gateway_
   service.app` has `count = var.app_image_uri != "" ? 1 : 0`, so it
   doesn't exist yet and isn't dragged into existence by this pass.
   This is what makes `app_public_url` knowable before the image is
   even built.
2. Build/push the image, then deploy the full service for the first
   time with `MCP_ALLOWED_HOSTS` set to the now-known CloudFront
   hostname — and, in the same apply, flip the CloudFront origin from
   its placeholder to the real Express ingress endpoint. This doesn't
   fully allowlist the app yet: CloudFront always rewrites the `Host`
   header it sends to the origin to the origin's own domain name (the
   raw ingress hostname), which isn't known until this apply returns.
3. Re-apply with the raw ingress hostname *also* appended to
   `MCP_ALLOWED_HOSTS` — required because the `mcp` SDK's DNS-rebinding
   protection rejects any request whose `Host` header isn't allowlisted
   (confirmed live: Confluent's Flink MCP client got HTTP 421 until this
   pass ran); only restarts the one task, no rebuild, doesn't touch the
   CloudFront distribution.

**Operational gotcha, confirmed live during redeploy**: because the
service runs a single task (no rolling replacement), pass 3's restart
briefly leaves zero healthy targets behind the ALB. With the synthetic
generator running, that window is enough real 4xx/5xx traffic to trip
AWS's automatic deployment circuit-breaker alarm ("Rate of 4XX and 5XX
errors" > 1%) and roll the deployment back to the previous task
revision — the app stays up throughout (old revision), but
`MCP_ALLOWED_HOSTS` doesn't get the real hostname until a retry
succeeds. Simply re-running the same apply is enough; it's a timing
race, not a config error. Also confirmed live: the whole
`base → app → intelligence` sequence is otherwise reliable, including
a from-scratch redeploy of the `intelligence` stage end-to-end (Flink
compute pool, enrichment/metrics/tool statements, the Bedrock IAM user,
and `triage_agent` all created successfully in one pass once AWS SSO
credentials were fresh).

---

## 3. Explicitly out of scope / decided against

Still holds, re-verified against the current build:

- **No AWS Bedrock Knowledge Base, OpenSearch Serverless, or AgentCore
  Gateway** for the known-issues search — local fuzzy matching
  (`rapidfuzz`) inside the app, no external cloud dependency for this
  component.
- **No watsonx Orchestrate agent acting as the mock portal backend** —
  the app is a plain Python service; watsonx Orchestrate's only role is
  the final "Support Ops Copilot" via RTCE.
- **No semantic embedding search live in Flink** (`AI_EMBEDDING` +
  `VECTOR_SEARCH_AGG`) — not built.
- **No real customer data, no login, no PII** — all accounts and
  tickets are synthetic; `user_id` is an anonymous pool-assigned integer.

---

## 4. Open decisions

- **Fallback escalation timer was removed — needs a deliberate
  decision, not a silent gap.** An earlier revision synthesized its own
  escalation if the real Flink pipeline hadn't responded within 30
  seconds (section 2.2); that code is gone. Before the live session,
  decide whether this was an intentional simplification (e.g. because
  the agent-response contract in 2.6 made the pipeline reliable enough
  in practice) or whether it needs to come back in some form — an
  attendee's ticket that never gets a response with no pipeline
  problem visible on stage is exactly the failure mode section 5's
  "reliability over completeness" principle exists to prevent.
- **`MATCH_THRESHOLD`** in the app (currently `65` — `config.py`,
  `.env.example`, and the deployed `terraform/app-hosting` default all
  agree) — still needs tuning against real planned ticket phrasings
  during rehearsal.
- **Region: confirm `us-east-1` before the live session.** The
  Confluent Cloud environment is currently deployed in `us-east-1`
  because `AI_SENTIMENT` wasn't available in `eu-west-1` at build time
  (section 2.5) — re-verify this is still the case (or still the
  deployed region) rather than assuming it from this document.
- **Not pursued**: the "streaming agent calls an external agent
  platform" stretch goal (e.g. AWS Bedrock AgentCore/Strands) as a
  dedicated demonstration of that capability pillar. Scope went instead
  to the single simpler `triage_agent` design (section 2.6); revisit
  only if there's build/rehearsal time left over.

**Resolved** (kept here for history, no longer open): front-end-to-Kafka
ingestion mechanism (2.1); dashboard tech stack (2.8); exact ticket
phrasings for the on-cue incident spike — the old `phrasing_bank.py`
hand-tagging is gone (2.3), but its intent survives structurally:
`BURST_CANDIDATES_BY_SERVICE` in `generator/synthetic.py` is computed at
import time by running `search_known_issues()` against every
`tickets.csv` row, so burst tickets for a service still reliably
fuzzy-match that service's known issues (e.g. checkout bursts still
match `KI-1002`/checkout freeze) — just derived from real matching
instead of a manual mapping; `AI_SENTIMENT` placeholder vs. real call
(now real, and correctly aspected on `service` rather than `urgency` —
section 2.5); `AI_RUN_AGENT`'s actual output shape and the
`DECISION:`/`MESSAGE:` prompt contract built around it (section 2.6);
MCP mount auth (now real Basic auth, not a placeholder credential —
sections 2.4/2.6); a stable public hostname across app redeploys (now
CloudFront — section 2.9).

---

## 5. Non-functional requirements

- **Reliability over completeness**: every live-dependent component
  should degrade gracefully (empty dashboard states, fallback matching,
  never a raw exception surfaced to an attendee) rather than error
  visibly on stage. **Currently under-served**: the ticket lifecycle's
  30-second fallback-escalation timer, which used to synthesize an
  escalation itself if the real Flink pipeline hadn't responded in
  time, has been removed (section 2.2) — see section 4 for the decision
  this leaves open.
- **No live dependency the presenter doesn't control the timing of**:
  the incident status and known-issue matching are manually triggered
  (via the presenter dashboard, 2.8), not automatically correlated.
- **Privacy**: no real names, emails, or identifying information
  collected from attendees at any point.
- **Scale**: designed for up to ~200 concurrent attendees; the account
  pool (250) and Kafka/Flink throughput should comfortably exceed this
  with margin.

---

## 6. Build status

1. ✅ support_portal app (front end, MCP tools, REST endpoints,
   Basic-auth-gated MCP mount) — built, consolidated into one app
   (2.1, 2.4).
2. ✅ Ticket submission front end + check-in flow — built (2.1).
3. ✅ Ticket lifecycle (create/list/detail/reply/close, sentiment
   threading) — built (2.2). The fallback-escalation timer this item
   originally included has since been removed — see section 4's open
   decision on that.
4. ✅ Flink SQL jobs (ticket enrichment, per-service ticket metrics)
   against real Confluent Cloud — built. `AI_SENTIMENT` is a real call
   (aspected on `service`, `us-east-1`-only — 2.5/4), `ML_FORECAST` is
   used instead of `AI_FORECAST`, and metrics are now partitioned per
   service.
5. ✅ Streaming Agent (`triage_agent`, MCP tools only) — built, simplified
   from the original four-agent design, with a prompt rewritten against
   real agent output and a regex parser (`parse_agent_response`) for its
   `DECISION:`/`MESSAGE:` contract (2.6).
6. ✅ RTCE — provisioned and topic-enabled (2.7). watsonx Orchestrate
   agent wired and configured; its prompt is authored/iterated in
   Orchestrate itself, not in this repo.
7. ✅ Dashboard — built, including the Live Triage Stream table and
   the retired presenter console's controls moved in (2.8).
8. ✅ Synthetic ticket generator, including health-weighted selection,
   the on-cue spike mode, and registering synthetic tickets as real
   `TicketRecord`s — built (2.3).
9. ✅ Support Admin (escalated queue, human reply) — built (2.8),
   per `docs/specs/ticket-management/spec.md`.
10. ⬜ **End-to-end rehearsal, threshold tuning** — the main remaining
    work: tuning `MATCH_THRESHOLD`, confirming the `us-east-1` region
    decision still holds, and deciding whether the fallback-escalation
    timer needs to come back in some form (section 4).

---

## 7. Reference: current app structure

See `app/support_portal/` for the full current implementation:
- `pages.py` — top-level page routes (`/`, `/dashboard`,
  `/support-admin`, `/status`)
- `tickets/` — ticket lifecycle: `models.py`, `store.py`, `service.py`,
  `routes.py`, `samples.py`, `tickets.csv` (section 2.2)
- `dashboard/` — `service.py` (aggregation/state), `routes.py`
  (WebSocket transport) (section 2.8)
- `admin/` — dashboard-driven incident/burst/generator controls, plus
  the Support Admin routes (escalated queue, ticket detail, support
  reply) (section 2.8)
- `accounts/` — `pool.py` (`AccountPool`, check-in, `is_synthetic_user_id`)
- `incidents/` — `known_issues.py` (fuzzy matcher),
  `knowledge_base.csv` (76 KB-article dataset), `state.py`
  (`PortalState`)
- `generator/` — `synthetic.py` (baseline + burst, section 2.3)
- `mcp/server.py` — the two MCP tools (section 2.4)
- `messaging/` — Kafka producer/consumer/client/schemas
- `static/` — front-end pages: `new-ticket.html`, `tickets.html`,
  `ticket-detail.html`, `dashboard.html`, `support-admin.html`,
  `full.html`, plus shared `theme.css`/`theme.js`

This superseded the originally-planned standalone
`support_portal_mock.py` single-file design.
