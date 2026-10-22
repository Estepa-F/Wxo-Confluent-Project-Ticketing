# E-Shop Support Portal — Ticket Lifecycle UI & Backend Spec

## 1. Goal

Extend the existing mobile-first E-Shop support portal so attendees can:

* create support tickets
* review their own tickets
* open a ticket detail page
* receive an automatic response or escalation
* reply to a ticket
* re-enter the triage flow after each reply
* close a ticket

The UI should remain consistent with the existing Support Operations Dashboard:

* dark navy / charcoal theme
* Confluent-inspired visual language
* bright blue primary actions
* green / amber / red status accents
* simple and business-oriented
* mobile-first

The attendee experience must remain very simple.

---

# 2. Ticket lifecycle

Use this lifecycle:

```text
Ticket created
      ↓
Triage
   ├── Automatic reply
   └── Escalated
          ↓
      User reply
          ↓
        Triage
       ├── Automatic reply
       └── Escalated
              ↓
          User reply
              ↓
             ...
              ↓
           Closed
```

Important rule:

Every new user reply re-enters the same triage process.

Do not model a user reply as a simple comment only.

A user reply must be an event that can trigger another automatic response or escalation decision.

---

# 3. User-visible lifecycle events

The user-facing timeline should only expose meaningful events.

Supported display types:

```text
Ticket created
Automatic reply
Escalated to support
Your reply
Support reply
Closed
```

Do not expose internal implementation details such as:

* Kafka topic
* partition
* offset
* Flink job
* agent name
* MCP tool call
* knowledge-base lookup
* model name
* confidence score

These may exist in backend events but should not appear in the attendee UI.

---

# 4. Ticket states

Use a small number of states.

Recommended:

```text
open
in_progress
resolved
closed
```

Suggested semantics:

### open

Ticket has been created and is waiting for processing.

### in_progress

Ticket has been escalated or is awaiting further resolution.

### resolved

An automatic or support response has provided a resolution.

The user may still reply if the issue is not actually solved.

### closed

Conversation is finished.

No additional replies are allowed.

---

# 5. Status behavior

Suggested transitions:

```text
ticket_created
→ open

automatic_reply
→ resolved

escalated
→ in_progress

support_reply
→ resolved

user_reply
→ open

ticket_closed
→ closed
```

A ticket marked `resolved` is not necessarily final.

If the attendee replies:

```text
resolved
→ user_reply
→ open
→ triage again
```

Only `closed` is terminal.

---

# 6. Mobile navigation

Use only two main attendee pages:

```text
New Ticket
My Tickets
```

Ticket Details is a drill-down from `My Tickets`.

Bottom navigation:

```text
New Ticket
My Tickets
```

An Account tab is optional and should be omitted unless needed.

---

# 7. New Ticket screen

Keep the ticket creation screen deliberately simple.

Fields:

## Service

Dropdown containing exactly:

```text
login
checkout
payments
search
notifications
order-tracking
```

Do not show both service tiles and a dropdown.

Use dropdown only.

## Subject

Single-line text input.

Example:

```text
Payment declined but charged
```

Recommended max length:

```text
100 characters
```

## Details

Multiline text field.

Optional.

Example:

```text
I was charged but the checkout page showed the payment as declined.
```

Recommended max length:

```text
500 characters
```

## Urgency

Use either a segmented control or dropdown:

```text
Low
Medium
High
```

For mobile, preferred UI:

```text
○ Low    ● Medium    ○ High
```

Default:

```text
Medium
```

## Submit

Primary full-width button:

```text
Submit Ticket
```

After successful submission:

* show success state
* navigate to the Ticket Details screen

Do not navigate back to an empty form.

---

# 8. My Tickets screen

Do not include search.

The audience is expected to have only a small number of tickets.

Header:

```text
My Support Tickets
Track the status of your requests.
```

Optional filters:

```text
All
Open
In progress
Resolved
Closed
```

Filters should be horizontal pills.

Show ticket cards rather than a desktop-style table.

Example:

```text
#45812                         Open

Payment declined but charged

Payments

Updated 2 min ago                 >
```

Each card should show:

* ticket number
* subject
* service
* current status
* last updated time
* chevron

Do not show the full ticket description in the list.

Maximum useful content per card:

2–3 compact rows.

---

# 9. Ticket Details screen

Use the previously selected mobile design.

Top navigation:

```text
< My Tickets

Ticket Details
```

Main ticket card:

```text
Open                        #45812

Payment declined but charged

Payments • Medium priority

Created Nov 9, 2024 at 10:17 AM
```

Then show the original request text.

Example:

```text
I was charged $49.99 for order #12345 but the payment shows as declined.
```

---

# 10. Ticket information section

Compact card:

```text
Ticket Information

Service        Payments
Status         Open
Priority       Medium
Created        10:17 AM
Last updated   10:24 AM
```

Avoid duplicating too much information already visible in the header card.

If space is limited on mobile, keep only:

```text
Service
Priority
Created
Last updated
```

Status is already clearly visible at the top.

---

# 11. Conversation / Activity timeline

The activity section is the core of the Ticket Details page.

Title:

```text
Activity
```

Render events chronologically.

Oldest first is recommended because this behaves like a conversation.

Example:

```text
● Ticket created
  10:17 AM

  Your request has been submitted.


● Automatic reply
  10:17 AM

  We found a known payment issue affecting some transactions.
  Your payment may appear temporarily charged even if checkout failed.


● Your reply
  10:21 AM

  I still see the charge in my bank account.


● Escalated to support
  10:21 AM

  Your ticket has been escalated for further review.
```

Use different icons/colors:

```text
Ticket created       blue
Automatic reply      green
Escalated            amber / red
Your reply           blue
Support reply        green / neutral
Closed               gray / green
```

---

# 12. Automatic reply event

An automatic reply should contain user-readable content.

Example event:

```json
{
  "type": "automatic_reply",
  "message": "We found a known issue affecting payment authorization. Please wait a few minutes before retrying.",
  "created_at": "2026-09-21T10:17:12Z"
}
```

UI:

```text
Automatic reply

We found a known issue affecting payment authorization.
Please wait a few minutes before retrying.
```

Do not label it:

```text
AI reply
LLM response
Agent response
```

Keep it user-friendly.

---

# 13. Escalation event

Example:

```json
{
  "type": "escalated",
  "message": "Your request needs additional review and has been escalated to support.",
  "created_at": "2026-09-21T10:18:02Z"
}
```

UI:

```text
Escalated to support

Your request needs additional review.
```

No internal queue or agent identifier is required.

---

# 14. User reply

At the bottom of every non-closed ticket show:

```text
Add a reply
```

Use a full-width primary button.

When tapped, either:

### Preferred mobile approach

Expand an inline composer above the button.

```text
Your reply

[ multiline input ]

Cancel                Send reply
```

or use a bottom sheet.

Prefer inline expansion for implementation simplicity.

Recommended max length:

```text
500 characters
```

Do not allow empty replies.

---

# 15. Send reply behavior

When the user submits a reply:

1. disable the send button
2. POST the reply to the backend
3. append `Your reply` to the local timeline
4. show a subtle processing state
5. backend emits a new reply event
6. triage is triggered again
7. the next `automatic_reply` or `escalated` event appears in real time

Suggested transient state:

```text
Processing your reply…
```

Do not block the whole screen.

---

# 16. Close ticket action

Below `Add a reply`, show a secondary action:

```text
Close ticket
```

Do not style it as the primary action.

On tap:

show a lightweight confirmation:

```text
Close this ticket?

You won't be able to add more replies after closing it.

Cancel      Close ticket
```

After confirmation:

* backend receives the close action
* ticket state becomes `closed`
* timeline receives a `Closed` event
* reply composer disappears
* close action disappears

---

# 17. Closed ticket UI

At the top:

```text
Closed
```

Timeline contains:

```text
✓ Ticket closed
  Sep 21 at 10:38 AM
```

At the bottom:

```text
This ticket is closed.
```

Do not show:

```text
Add a reply
Close ticket
```

Closed tickets are read-only.

---

# 18. Backend API

Recommended REST API additions.

## Get current user's tickets

```http
GET /api/tickets
```

Response:

```json
[
  {
    "ticket_id": "45812",
    "service": "payments",
    "subject": "Payment declined but charged",
    "status": "in_progress",
    "urgency": "medium",
    "created_at": "2026-09-21T10:17:00Z",
    "updated_at": "2026-09-21T10:21:00Z"
  }
]
```

Only return tickets belonging to the current synthetic user.

---

# 19. Get ticket details

```http
GET /api/tickets/{ticket_id}
```

Response:

```json
{
  "ticket_id": "45812",
  "service": "payments",
  "subject": "Payment declined but charged",
  "description": "I was charged but checkout reported that payment failed.",
  "status": "in_progress",
  "urgency": "medium",
  "created_at": "2026-09-21T10:17:00Z",
  "updated_at": "2026-09-21T10:21:00Z",
  "events": [
    {
      "event_id": "evt-1",
      "type": "ticket_created",
      "created_at": "2026-09-21T10:17:00Z"
    },
    {
      "event_id": "evt-2",
      "type": "automatic_reply",
      "message": "We found a known payment issue.",
      "created_at": "2026-09-21T10:17:08Z"
    },
    {
      "event_id": "evt-3",
      "type": "user_reply",
      "message": "I still see the charge.",
      "created_at": "2026-09-21T10:20:54Z"
    },
    {
      "event_id": "evt-4",
      "type": "escalated",
      "message": "Your ticket has been escalated to support.",
      "created_at": "2026-09-21T10:21:01Z"
    }
  ]
}
```

---

# 20. Add reply endpoint

```http
POST /api/tickets/{ticket_id}/replies
```

Request:

```json
{
  "message": "I still see the charge on my bank account."
}
```

Response:

```json
{
  "event_id": "evt-123",
  "ticket_id": "45812",
  "type": "user_reply",
  "message": "I still see the charge on my bank account.",
  "created_at": "2026-09-21T10:32:00Z"
}
```

Validation:

* ticket must belong to current user
* ticket must not be closed
* message must not be empty
* enforce max length

---

# 21. Close endpoint

```http
POST /api/tickets/{ticket_id}/close
```

Response:

```json
{
  "ticket_id": "45812",
  "status": "closed",
  "closed_at": "2026-09-21T10:35:00Z"
}
```

Backend should also emit a lifecycle event.

---

# 22. Event architecture

Prefer event-driven state changes.

Each relevant user/support operation creates an event.

Suggested event types:

```text
ticket_created
automatic_reply
escalated
user_reply
support_reply
ticket_closed
```

Optional internal event types may exist, but attendee UI does not need to expose them.

---

# 23. Kafka event model

Recommended normalized event structure:

```json
{
  "event_id": "evt-12345",
  "ticket_id": "45812",
  "user_id": 123,
  "event_type": "user_reply",
  "service": "payments",
  "message": "I still see the charge.",
  "created_at": "2026-09-21T10:32:00Z"
}
```

For ticket creation:

```json
{
  "event_id": "evt-12340",
  "ticket_id": "45812",
  "user_id": 123,
  "event_type": "ticket_created",
  "service": "payments",
  "subject": "Payment declined but charged",
  "message": "I was charged but checkout failed.",
  "urgency": "medium",
  "created_at": "2026-09-21T10:17:00Z"
}
```

---

# 24. Re-triage behavior

The backend must treat both of these as triage inputs:

```text
ticket_created
user_reply
```

Pseudo-flow:

```text
on ticket_created:
    run triage(ticket)

on user_reply:
    append reply
    mark ticket open
    run triage(ticket + conversation context)
```

Triage outputs:

```text
automatic_reply
OR
escalated
```

The conversation history should be passed as context when re-triaging.

The agent should not treat every reply as a brand-new unrelated support request.

---

# 25. Automatic resolution

If triage can answer the issue automatically:

create:

```text
automatic_reply
```

and set:

```text
status = resolved
```

The attendee can still reply.

Example:

```text
Automatic reply

This is a known checkout issue.
Please refresh the page and try again in two minutes.
```

---

# 26. Escalation

If triage cannot confidently handle the issue:

create:

```text
escalated
```

and set:

```text
status = in_progress
```

Example:

```text
Escalated to support

Your request requires additional review.
```

---

# 27. Support reply

If the backend later simulates or implements a human response:

event:

```text
support_reply
```

Example:

```json
{
  "event_type": "support_reply",
  "ticket_id": "45812",
  "message": "We've confirmed that the authorization was reversed.",
  "created_at": "..."
}
```

Set ticket status:

```text
resolved
```

---

# 28. Closing semantics

Support two internal close sources:

```text
user
support
```

Example event:

```json
{
  "event_type": "ticket_closed",
  "ticket_id": "45812",
  "closed_by": "user",
  "created_at": "..."
}
```

UI does not need to emphasize the difference.

Render:

```text
Ticket closed
```

---

# 29. Real-time updates

Ticket Details should update without page refresh.

Preferred options:

1. reuse the existing WebSocket infrastructure
2. add ticket/user-scoped WebSocket events

For example:

```text
/ws/tickets
```

or:

```text
/ws/tickets/{ticket_id}
```

When a new backend event arrives:

* append it to the timeline
* update ticket status
* update `updated_at`
* enable/disable actions as needed

---

# 30. WebSocket event example

```json
{
  "type": "ticket_event",
  "ticket_id": "45812",
  "event": {
    "event_id": "evt-124",
    "type": "automatic_reply",
    "message": "We found a known issue with payment authorization.",
    "created_at": "2026-09-21T10:32:04Z"
  },
  "status": "resolved"
}
```

---

# 31. Loading states

After creating a ticket:

```text
Submitting…
```

After sending a reply:

```text
Sending…
```

After triage starts:

```text
Processing your request…
```

Avoid spinners covering the whole screen.

Use subtle inline feedback.

---

# 32. Empty ticket list

If the attendee has no tickets:

```text
No support tickets yet

Need help with something?
Create your first support request.

[ New Ticket ]
```

---

# 33. Error handling

For demo reliability, errors must be user-friendly.

Examples:

```text
We couldn't submit your ticket.
Please try again.
```

```text
We couldn't send your reply.
Your message has not been lost.
```

```text
Connection interrupted.
Reconnecting…
```

Do not display raw backend exceptions.

---

# 34. Mobile visual design

Primary target:

```text
390–430 px width
```

Design for one-handed phone usage.

Rules:

* minimum 44 px touch targets
* full-width primary buttons
* 16 px minimum body text
* no horizontal scrolling
* avoid dense tables
* use cards for tickets
* use one column
* keep important actions near the bottom

---

# 35. Ticket Details recommended layout

```text
┌──────────────────────────────┐
│ < My Tickets   Ticket Details│
├──────────────────────────────┤
│ OPEN                  #45812 │
│                              │
│ Payment declined but charged│
│ Payments • Medium            │
│ Created 10:17 AM             │
│                              │
│ I was charged but...         │
├──────────────────────────────┤
│ Ticket Information           │
│ Service          Payments    │
│ Priority         Medium      │
│ Created          10:17 AM    │
│ Updated          10:21 AM    │
├──────────────────────────────┤
│ Activity                     │
│                              │
│ ● Ticket created             │
│ │ 10:17 AM                   │
│ │                            │
│ ● Automatic reply            │
│ │ Known payment issue...     │
│ │                            │
│ ● Your reply                 │
│ │ I still see the charge...  │
│ │                            │
│ ● Escalated to support       │
│                              │
├──────────────────────────────┤
│       Add a reply            │
│                              │
│       Close ticket           │
└──────────────────────────────┘
```

---

# 36. Demo scenario example

A complete demo loop should be possible:

```text
1. User creates:
   "Checkout page freezes when I pay"

2. ticket_created event

3. Agent matches known issue

4. automatic_reply:
   "This appears to be a known checkout issue..."

5. Ticket becomes Resolved

6. User replies:
   "That didn't fix it."

7. user_reply event

8. Agent re-runs triage

9. escalated:
   "We've escalated this for further review."

10. Ticket becomes In Progress

11. Support response or simulated resolution

12. User closes ticket

13. ticket_closed event
```

This flow should also be visible in the presenter dashboard through the aggregated Auto-resolved / Escalated metrics.

---

# 37. Implementation priorities

Prioritize in this order:

1. ticket creation
2. ticket list
3. ticket details
4. timeline
5. user reply
6. re-triage
7. close ticket
8. real-time updates
9. polish and animations

Keep all frontend code simple.

Do not introduce a frontend framework unless the existing application architecture changes.

The demo should favor reliability and clarity over elaborate interaction patterns.
