"""Ticket lifecycle business logic: the shared ticket store, the per-ticket
WebSocket broadcast, and the Kafka agent-action dispatch.

Module-level state (`store`, `_connections`) mirrors dashboard/service.py's
style: process-global, not persisted, not stashed on app.state, since
nothing outside this module needs it directly.
"""

import asyncio

from fastapi import WebSocket

from support_portal.tickets.models import TicketEvent
from support_portal.tickets.store import TicketStore

store = TicketStore()
_connections: dict[str, set[WebSocket]] = {}


def extract_sentiment(value: dict) -> str | None:
    """Same normalization dashboard/service.py's handle_message already
    applies: AI_SENTIMENT's real label is capitalized ('Negative'/...)
    and returns 'UNKNOWN' when it can't find the aspect discussed in the
    text -- lowercase and drop 'unknown' (treated as no signal, not a
    real reading)."""
    aspects = (value.get("sentiment_analysis") or {}).get("sentiment") or []
    label = aspects[0].get("label") if aspects else None
    label = label.lower() if label else None
    return label if label and label != "unknown" else None


def register_connection(ticket_id: str, ws: WebSocket) -> None:
    _connections.setdefault(ticket_id, set()).add(ws)


def unregister_connection(ticket_id: str, ws: WebSocket) -> None:
    conns = _connections.get(ticket_id)
    if conns is not None:
        conns.discard(ws)


# --- Kafka dispatch (registered with the shared DashboardConsumer) ---


def handle_agent_action(topic: str, value: dict) -> None:
    """Correlates a real tickets.agent-actions message back to a ticket.
    decision/message now arrive pre-computed from Flink (03_statements_
    triage_agent.tf's run_triage_agent extracts them from AI_RUN_AGENT's
    raw response via REGEXP_EXTRACT), so no parsing happens here -- just a
    defensive fallback since Kafka messages are external input this code
    doesn't control end-to-end."""
    ticket_id = value.get("ticket_id")
    if not ticket_id:
        return
    action = value.get("decision", "escalate")
    message = value.get("message") or value.get("response")
    store.set_sentiment(ticket_id, extract_sentiment(value))
    event = store.apply_agent_action(ticket_id, action, message)
    if event is None:
        return
    record = store.get(ticket_id)
    if record is not None:
        asyncio.create_task(_broadcast(ticket_id, event, record.status))
        if event.type == "escalated":
            from support_portal.orchestrate import drafts  # late import: avoids a cycle

            if drafts.should_auto_draft(record):
                drafts.schedule_draft(ticket_id)


# --- Human support reply (called from the /admin/tickets/{id}/support-reply route) ---


def apply_support_reply(ticket_id: str, message: str) -> TicketEvent | None:
    """A human's answer to an escalated ticket -- doesn't republish to
    tickets.raw (a support reply is a terminal answer, not something that
    should re-trigger AI triage), just updates the store and broadcasts
    over the ticket's own WS like any other event."""
    event = store.apply_support_reply(ticket_id, message)
    if event is None:
        return None
    record = store.get(ticket_id)
    if record is not None:
        asyncio.create_task(_broadcast(ticket_id, event, record.status))
    return event


# --- WebSocket broadcast ---


async def _broadcast(ticket_id: str, event: TicketEvent, status: str) -> None:
    conns = _connections.get(ticket_id)
    if not conns:
        return
    payload = {
        "type": "ticket_event",
        "ticket_id": ticket_id,
        "event": event.model_dump(mode="json"),
        "status": status,
    }
    dead = []
    for ws in list(conns):
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        conns.discard(ws)
