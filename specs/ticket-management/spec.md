# E-Shop Support Portal — Support Admin (Ticket Management) Spec

## 1. Goal

Add a "Support Admin" surface so a human can close the loop the AI triage agent starts. Today, per `specs/ticket-lifecycle/spec.md`, a ticket can reach `escalated`, but nothing lets a person see the queue of escalated tickets or answer one — `support_reply` exists as an event type with no way to produce it before this spec (see `app/support_portal/tickets/service.py`'s `apply_support_reply`, added but with no admin-facing queue view yet).

This replaces the old "Presenter Console" (`static/console.html`), whose other two features (flip a service's incident status, fire a synthetic ticket burst) are already duplicated inline in the dashboard (`static/dashboard.html`) and add nothing on their own.

Two screens, mobile-first like the rest of the portal (see the mockup this spec is based on):

```text
Escalated Queue  →  Ticket Response
```

Visual language: same dark-navy/charcoal theme, Confluent-inspired palette, bright-blue primary actions, green/amber/red status accents as the rest of the portal (`theme.css`/`theme.js`). Reuse existing component patterns (status pills, timeline items, reply composer) rather than inventing new ones — this should look like a natural extension of `ticket-detail.html`, not a separate tool.

---

## 2. Screen 1 — Escalated Queue

```text
┌──────────────────────────────┐
│ Support Admin                │
│ Manage escalated tickets and │
│ support customers.           │
├──────────────────────────────┤
│ ↑ Escalated queue         (4)│
│   Tickets requiring human    │
│   support                    │
├──────────────────────────────┤
│ payments            #SP-1042 │
│ Payment declined but charged │
│ Medium  12m waiting  Negative│
│ Customer was charged but...  │
│                            > │
├──────────────────────────────┤
│ checkout            #SP-1041 │
│ Unable to complete order     │
│ High  28m waiting  Neutral   │
│ Customer cannot complete...  │
│                            > │
├──────────────────────────────┤
│           ⋮ (more rows)      │
└──────────────────────────────┘
```

Each row:
* service icon + service name (small, muted)
* ticket number, right-aligned (see §6 for where this comes from)
* subject, bold
* three inline badges: urgency (color-coded: low=gray, medium=amber, high=red), waiting time (`Xm waiting` / `1h Xm waiting`, computed client-side from the escalation event's `created_at` to now — do not have the backend compute a live-relative string), sentiment (see §6)
* one-line preview of the escalation message, truncated
* chevron

The queue count badge and row count must always match — this is a live, derived view, not a separately-maintained counter.

### Empty state

Show **instead of** the row list, not appended below it:

```text
📥 Nothing escalated right now
All caught up! We'll notify you when new tickets are escalated.
```

### Sorting

Oldest-waiting first (the ticket that's been escalated longest is the one most likely to need attention).

---

## 3. Screen 2 — Ticket Response (drill-down from a queue row)

```text
┌──────────────────────────────┐
│ < Back to queue               │
├──────────────────────────────┤
│ Payment declined but charged │
│                    ↑ Escalated│
│ Customer was charged but     │
│ checkout showed the payment  │
│ as declined.                 │
│                               │
│ payments  Medium  12m waiting│
│ #SP-1042                     │
├──────────────────────────────┤
│ 🙁 Customer sentiment: Negative│
├──────────────────────────────┤
│ ⚠ Escalation reason           │
│ Customer reports being        │
│ charged but seeing a declined │
│ payment message. Needs manual │
│ review and refund verification│
├──────────────────────────────┤
│ ⏱ Activity timeline           │
│ ● Ticket created              │
│ │ Customer submitted a        │
│ │ support request             │
│ │ 11:12:15                    │
│ │                             │
│ ● Your reply                  │
│ │ Added additional details    │
│ │ about the charge            │
│ │ 11:15:03                    │
│ │                             │
│ ● Escalated to support        │
│   Automated rules escalated   │
│   this ticket                 │
│   11:23:32                    │
├──────────────────────────────┤
│ 💬 Reply to customer          │
│ [ multiline input ]           │
│                        0/500  │
│ ⓘ Response will be sent as    │
│   Support Admin.              │
│                                │
│   Clear          Send reply   │
└──────────────────────────────┘
```

Corrections vs. the mockup this is based on, to keep it consistent with the real event model in `tickets/models.py`:
* **Timeline order is chronological, oldest first** — same rule as `ticket-lifecycle/spec.md` §11. (The mockup showed `escalated` above `ticket_created`; that was a mockup artifact, not intended behavior.)
* There is no `"Customer updated ticket"` event type. A customer adding detail after creation is a `user_reply` event, already defined — label it "Your reply" like `ticket-detail.html` does, not new copy.
* **"Escalation reason" is the escalated event's own `message`** — the same customer-facing text the triage agent already produces (`DECISION: ESCALATE` / `MESSAGE: ...`, see `03_statements_triage_agent.tf`). There is no separate internal-only reason today. If a genuinely different internal-facing explanation is wanted later, that requires a prompt change to have the agent emit a second field — out of scope for this pass; ship with the same message shown to the customer.

### Send reply behavior

Mirrors `ticket-lifecycle/spec.md` §15's reply flow, support-side:
1. disable "Send reply" while in flight
2. `POST /admin/tickets/{ticket_id}/support-reply` (already implemented, see §7)
3. on success: append the `support_reply` event to the local timeline, show confirmation, and remove the ticket from the queue view (it's no longer escalated once answered)
4. on failure: keep the composer's contents, show an inline error (`We couldn't send your reply. Your message has not been lost.`), don't clear the field

"Clear" empties the composer without sending; it does not navigate back.

---

## 4. Ticket states shown here

Only tickets whose **current** state is escalated belong in the queue — derived from live state, not a standing flag:

```text
in queue  ⟺  latest event type == "escalated"
              AND no support_reply, user_reply, or ticket_closed has happened since
```

The moment a `support_reply` (this feature), a `user_reply` (customer replies again before support gets to it — re-enters triage per the existing lifecycle spec), or a `ticket_closed` lands, that ticket drops out of the queue automatically. Do not add a separate "resolved by support" boolean; the event timeline is the single source of truth, same principle `ticket-lifecycle/spec.md` already establishes for customer-facing state.

---

## 5. Sentiment (new field, not in the current data model)

`tickets.enriched`'s `AI_SENTIMENT` output already computes this per ticket (`sentiment_analysis.sentiment[0].label`), and it already flows into `tickets.agent-actions` as a passthrough column (confirmed live: real `tickets.agent-actions` messages carry the full `sentiment_analysis` object). It just isn't stored on the ticket record today.

Add:
* `TicketRecord`/`TicketSummary` gain an optional `sentiment: Optional[str]` field (`"positive"` / `"neutral"` / `"negative"`, lowercased — same normalization `dashboard/service.py`'s `handle_message` already applies for its own sentiment handling, including treating `"unknown"` as absent).
* `tickets/service.py`'s `handle_agent_action` sets it on the record from `value.get("sentiment_analysis")` the first time a message for that ticket arrives with one (enriched data arrives on the same `tickets.agent-actions` message the decision does — no new topic subscription needed).

If no sentiment is available yet, omit the sentiment badge/callout rather than showing a placeholder.

---

## 6. Ticket numbers (`#SP-1042` in the mockup)

The rest of the app has no short numeric ticket ID — `ticket_id` is a UUID (see `store.create()`). Two options, pick one when implementing:
* Derive a display-only short form from the existing UUID (e.g. `#` + first 5 hex chars uppercased — `ticket-detail.html`'s `shortId()` already does exactly this for its own ticket-number display; reuse that function/format here for consistency rather than inventing a new `SP-####` numbering scheme).
* Do not introduce a real sequential ticket-number field just for this view.

---

## 7. Backend API

### 7.1 List escalated tickets (new)

```http
GET /admin/tickets/escalated
X-Admin-Token: <token>
```

Same auth as every other `/admin/*` route (`_check_token` in `admin/routes.py`).

Response — array of ticket summaries plus the escalation context the queue row needs:

```json
[
  {
    "ticket_id": "5e0b185c-5e22-406b-b480-3cdcb0f4fc69",
    "service": "payments",
    "subject": "Payment declined but charged",
    "urgency": "medium",
    "sentiment": "negative",
    "escalation_message": "Customer was charged but checkout showed the payment as declined.",
    "escalated_at": "2026-09-23T11:23:32Z"
  }
]
```

Sorted oldest-`escalated_at`-first (§2). Backed by a new `TicketStore.list_escalated()` (per §4's definition), not a Kafka topic replay — `tickets.escalations` is for external consumers, this app's own queue view reads its own live state.

### 7.2 Get ticket detail

Reuse the existing `GET /api/tickets/{ticket_id}` — it already returns the full event timeline this screen needs. Add the new `sentiment` field from §5 to its response too. (This endpoint currently checks the *customer's* cookie ownership; the admin view needs a token-gated equivalent, e.g. reuse the same handler under `/admin/tickets/{ticket_id}` with `_check_token` instead of `_require_owned_ticket` — do not require an admin to have the customer's session cookie.)

### 7.3 Send a support reply

Already implemented — no changes needed:

```http
POST /admin/tickets/{ticket_id}/support-reply
X-Admin-Token: <token>

{"message": "We've confirmed the charge was reversed and your order is confirmed."}
```

---

## 8. Real-time updates

The queue should feel live without a full-page reload, but a new escalation can come from *any* ticket, unlike the existing per-ticket `/ws/tickets/{ticket_id}` WebSocket which is scoped to one ticket.

For this iteration: **poll `GET /admin/tickets/escalated` every few seconds** while the queue screen is open. This is an explicit, acceptable tradeoff, not an oversight — do not build a new all-tickets WebSocket channel for this unless a later iteration decides the polling latency is actually a problem on stage.

The detail/reply screen, once opened for a specific ticket, may reuse the existing `/ws/tickets/{ticket_id}` WebSocket the customer-facing page already uses, to see a customer's reply arrive live while composing a response.

---

## 9. Console retirement

Once this view covers the support-reply case:
* remove `static/console.html` and wherever it's linked/served (check `pages.py`/`main.py`'s static routes)
* leave the `/admin/status` and `/admin/burst` **routes** in `admin/routes.py` untouched — `dashboard.html` calls them directly and must keep working standalone

---

## 10. Error handling

Same philosophy as `ticket-lifecycle/spec.md` §33 — user-friendly, never a raw exception:

```text
We couldn't load the escalated queue. Retrying…
We couldn't send your reply. Your message has not been lost.
```

---

## 11. Implementation priorities

1. `TicketStore.list_escalated()` + `GET /admin/tickets/escalated`
2. Queue screen (list, badges, empty state, polling)
3. Admin-token-gated ticket detail fetch
4. Detail/reply screen (timeline, composer, send)
5. Sentiment threading (§5) — nice-to-have badge, not blocking the core loop
6. Console retirement (§9)
7. Polish: waiting-time formatting, transitions between queue and detail
