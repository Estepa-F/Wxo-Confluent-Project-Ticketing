"""AI reply drafts for escalated tickets, prepared by the Orchestrate
escalation agent (orchestrate/agents/escalation_agent.yaml).

When the Flink triage agent escalates a ticket, the app sends the ticket
context to the escalation agent in one headless call. The agent strips
personal data (Orchestrate PII control + its own instructions), asks the
AWS goodwill agent for the commercial gesture, and answers with three
sections that support-admin shows next to the reply composer. A human
always reviews and sends: the app never posts the draft on its own.
"""

import asyncio
import logging
import re
from datetime import datetime, timezone

from support_portal.accounts.pool import AccountPool, is_synthetic_user_id
from support_portal.config import settings
from support_portal.incidents.state import PortalState
from support_portal.orchestrate import client

logger = logging.getLogger(__name__)

_account_pool: AccountPool | None = None
_portal_state: PortalState | None = None
_in_flight: set[str] = set()

SECTION_KEYS = {
    # French or English headings (the escalation agent may answer in either).
    "reponse_suggeree": r"R[ÉE]PONSE\s+SUGG[ÉE]R[ÉE]E|SUGGESTED\s+(?:REPLY|RESPONSE)",
    "geste_commercial": r"GESTE\s+COMMERCIAL\s+PROPOS[ÉE]|PROPOSED\s+(?:GOODWILL\s+GESTURE|GESTURE|COMPENSATION)",
    "note_conseiller": r"NOTE\s+POUR\s+LE\s+CONSEILLER|NOTE\s+(?:FOR|TO)\s+THE\s+(?:ADVISOR|AGENT)",
}
_HEADER = re.compile(
    r"^[#>*\s]*(" + "|".join(f"(?P<{k}>{p})" for k, p in SECTION_KEYS.items()) + r")[ \t*]*:?[ \t*]*",
    re.IGNORECASE | re.MULTILINE,
)


def configure(account_pool: AccountPool, portal_state: PortalState) -> None:
    global _account_pool, _portal_state
    _account_pool, _portal_state = account_pool, portal_state


def parse_sections(text: str) -> dict[str, str]:
    """Splits the agent answer on its three headings. Missing headings are
    tolerated: whatever precedes the first heading (or the whole text when
    none is found) becomes the suggested reply."""
    matches = list(_HEADER.finditer(text))
    sections = {k: "" for k in SECTION_KEYS}
    if not matches:
        sections["reponse_suggeree"] = text.strip()
        return sections
    for i, m in enumerate(matches):
        key = next(k for k in SECTION_KEYS if m.group(k))
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[key] = text[m.end():end].strip()
    if not sections["reponse_suggeree"] and matches[0].start() > 0:
        sections["reponse_suggeree"] = text[: matches[0].start()].strip()
    return sections


def ticket_facts(record) -> dict:
    """Tier and recurrence use the same account data as the MCP tool
    get_account_context, so the triage and escalation agents see the same
    facts; service status comes from the portal state."""
    account = _account_pool.get(record.user_id) if _account_pool else None
    return {
        "ticket_number": "#" + record.ticket_id.replace("-", "")[:5].upper(),
        "tier": account.tier if account else "unknown",
        "recurring": bool(account) and any(t.get("service") == record.service for t in account.ticket_history),
        "service_status": (_portal_state.get_service_status().get(record.service) if _portal_state else None) or "unknown",
    }


def build_message(record, triage_message: str | None, facts: dict | None = None) -> str:
    """Same shape as the manual chat test: one "label: value" line per fact."""
    f = facts or ticket_facts(record)
    lines = [
        f"Escalated ticket {f['ticket_number']}",
        f"Tier: {f['tier']}",
        f"Service: {record.service}",
        f"Service status: {f['service_status']}",
        f"Recurring issue on this service: {'true' if f['recurring'] else 'false'}",
        f"Subject: {record.subject}",
        f"Text: {record.description or '(no details)'}",
    ]
    if triage_message:
        lines.append(f"Triage agent message: {triage_message}")
    return "\n".join(lines)


def should_auto_draft(record) -> bool:
    if not (settings.wxo_auto_draft and client.is_configured()):
        return False
    return settings.wxo_include_synthetic or not is_synthetic_user_id(record.user_id)


async def request_draft(ticket_id: str, on_update=None) -> None:
    """Runs one draft request for a ticket; never raises. on_update(ticket_id)
    is called after each state change so the caller can notify the UI."""
    from support_portal.tickets.service import store  # late import: avoids a cycle

    if ticket_id in _in_flight:
        return
    record = store.get(ticket_id)
    if record is None:
        return
    _in_flight.add(ticket_id)
    started = datetime.now(timezone.utc)
    triage = next((e.message for e in reversed(record.events) if e.type == "escalated"), None)
    store.set_ai_draft(ticket_id, {"status": "pending", "requested_at": started.isoformat()})
    if on_update:
        on_update(ticket_id)
    facts = ticket_facts(record)
    try:
        text = await client.ask_agent(build_message(record, triage, facts))
        draft = {
            "status": "ready",
            "requested_at": started.isoformat(),
            "seconds": round((datetime.now(timezone.utc) - started).total_seconds(), 1),
            "text": text,
            **parse_sections(text),
        }
    except Exception as exc:
        logger.exception("Orchestrate draft failed for ticket %s", ticket_id)
        draft = {"status": "error", "requested_at": started.isoformat(), "error": f"{type(exc).__name__}: {exc}"[:300]}
    finally:
        _in_flight.discard(ticket_id)
    # Stored right away (support-admin never waits on Kafka), and ready
    # drafts are also published to Confluent (tickets.escalation-drafts) for
    # other consumers: Real-Time Context Engine, Support Ops Copilot. The
    # app's own consumer re-applies the same draft and tags it via_topic.
    store.set_ai_draft(ticket_id, draft)
    if draft["status"] == "ready":
        publish_draft(record, facts, draft)
    if on_update:
        on_update(ticket_id)


DRAFTS_TOPIC = "tickets.escalation-drafts"
_VOUCHER = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:€|EUR\b|euros?\b)|(?:€|EUR)\s*(\d+(?:[.,]\d+)?)", re.IGNORECASE)


def _voucher_eur(geste: str) -> float | None:
    if re.search(r"\bnone\b|\bno\s+(?:voucher|gesture)\b|aucun", geste, re.IGNORECASE) and not _VOUCHER.search(geste):
        return 0.0
    m = _VOUCHER.search(geste)
    return float((m.group(1) or m.group(2)).replace(",", ".")) if m else None


def _approval(text: str) -> bool | None:
    m = re.search(r"requires_human_approval\W*(true|false)", text, re.IGNORECASE)
    return (m.group(1).lower() == "true") if m else None


def publish_draft(record, facts: dict, draft: dict) -> bool:
    """Publishes a ready draft to Kafka; False if Kafka is off or fails."""
    from support_portal.messaging.producer import producer
    from support_portal.messaging.schemas import EscalationDraft

    if not getattr(producer, "_enabled", True):
        return False
    try:
        producer.produce_model(
            DRAFTS_TOPIC,
            key=record.ticket_id,
            model_instance=EscalationDraft(
                ticket_id=record.ticket_id,
                ticket_number=facts["ticket_number"],
                service=record.service,
                tier=facts["tier"],
                service_status=facts["service_status"],
                recurring_issue_same_service=facts["recurring"],
                reponse_suggeree=draft.get("reponse_suggeree", ""),
                geste_commercial=draft.get("geste_commercial", ""),
                note_conseiller=draft.get("note_conseiller", ""),
                voucher_eur=_voucher_eur(draft.get("geste_commercial", "")),
                requires_human_approval=_approval(draft.get("text", "")),
                duration_seconds=draft.get("seconds", 0.0),
            ),
        )
        return True
    except Exception:
        logger.warning("Could not publish draft for %s to %s; storing locally", record.ticket_id, DRAFTS_TOPIC, exc_info=True)
        return False


def handle_draft_message(topic: str, value: dict) -> None:
    """Consumer side of tickets.escalation-drafts: puts the draft back on
    the ticket for support-admin. Unknown ticket_ids (another instance's
    tickets, or history replayed at startup) are ignored by the store."""
    from support_portal.tickets.service import store

    ticket_id = value.get("ticket_id")
    if not ticket_id or store.get(ticket_id) is None:
        return
    current = (store.get(ticket_id).ai_draft or {})
    store.set_ai_draft(ticket_id, {
        **current,
        "status": "ready",
        "seconds": value.get("duration_seconds", current.get("seconds")),
        "reponse_suggeree": value.get("reponse_suggeree", ""),
        "geste_commercial": value.get("geste_commercial", ""),
        "note_conseiller": value.get("note_conseiller", ""),
        "voucher_eur": value.get("voucher_eur"),
        "via_topic": DRAFTS_TOPIC,
    })


def schedule_draft(ticket_id: str, on_update=None) -> None:
    asyncio.create_task(request_draft(ticket_id, on_update))
