"""In-app ticket lifecycle models (not Kafka/Schema-Registry-backed)."""

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


TicketStatus = Literal["open", "closed"]

TicketEventType = Literal[
    "ticket_created",
    "automatic_reply",
    "escalated",
    "user_reply",
    "support_reply",
    "ticket_closed",
]


class TicketEvent(BaseModel):
    event_id: str
    ticket_id: str
    type: TicketEventType
    message: Optional[str] = None
    created_at: datetime = Field(default_factory=_utcnow)


class TicketSummary(BaseModel):
    ticket_id: str
    service: str
    subject: str
    status: TicketStatus
    urgency: Literal["low", "medium", "high"]
    created_at: datetime
    updated_at: datetime
    # Set from tickets.agent-actions' passthrough sentiment_analysis column
    # (see tickets/service.py's handle_agent_action) the first time an
    # agent-actions message for this ticket carries one -- absent until
    # then, never a placeholder.
    sentiment: Optional[Literal["positive", "neutral", "negative"]] = None


class TicketDetail(TicketSummary):
    description: Optional[str] = None
    events: list[TicketEvent] = Field(default_factory=list)
    # Orchestrate escalation-agent draft (orchestrate/drafts.py): status is
    # pending | ready | error; ready drafts carry reponse_suggeree,
    # geste_commercial, note_conseiller and the raw text.
    ai_draft: Optional[dict] = None
