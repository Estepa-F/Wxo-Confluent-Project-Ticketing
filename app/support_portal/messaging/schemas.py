"""Kafka wire-format models — source of truth for the JSON Schemas registered
in Confluent Cloud Schema Registry for tickets.raw / tickets.enriched /
tickets.metrics / tickets.agent-actions. TicketRaw is produced by this app
(tickets/, generator/) via messaging/producer.py; the other three are
produced by the external Flink pipeline and consumed back here only as
raw dicts (messaging/consumer.py), so they're never instantiated in-app --
they exist purely to document that pipeline's wire contract."""

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TicketRaw(BaseModel):
    ticket_id: str
    user_id: int
    text: str
    urgency_self_rated: Literal["low", "medium", "high"]
    submitted_at: datetime = Field(default_factory=_utcnow)
    source: Literal["live", "synthetic"] = "live"
    # Self-declared, same as urgency_self_rated -- the enrichment pipeline
    # doesn't classify service from ticket text (see 02_statements_ticket_enrichment.tf),
    # so synthetic producers stamp the service they already know here.
    service: Optional[str] = None
    # Subject line for the ticket-lifecycle UI, also passed through
    # tickets.enriched into the triage agent's prompt and on to
    # search_known_issues (03_statements_triage_agent.tf) -- subject text
    # tends to echo a known issue's own topic more directly than the
    # verbose ticket body alone, which meaningfully improves match rate.
    # Optional so this stayed a backward-compatible addition to the
    # registered JSON Schema when first introduced.
    subject: Optional[str] = None


class ServiceStatusEvent(BaseModel):
    """Produced by this app (like TicketRaw) to the compacted
    services.status topic, keyed by `service` -- published at startup,
    on every admin-triggered change, and on a 1-minute heartbeat. Flink
    infers changelog.mode='upsert' with `service` as primary key from
    the topic's cleanup.policy=compact plus its keyed records, so this
    is joined directly into tickets.enriched (no intermediate table)."""

    service: str
    status: str  # "operational" | "degraded" | "outage"
    description: str = ""
    updated_at: datetime = Field(default_factory=_utcnow)


class EnrichedTicket(BaseModel):
    ticket_id: str
    user_id: int
    service: Optional[str] = None
    text: str
    urgency_self_rated: str
    sentiment: Optional[str] = None
    urgency_score: Optional[float] = None
    enriched_at: datetime = Field(default_factory=_utcnow)


class MetricsPoint(BaseModel):
    window_start: datetime
    window_end: datetime
    count: int
    forecast_next: Optional[float] = None


class AgentAction(BaseModel):
    ticket_id: str
    action: Literal["auto_resolve", "escalate"]
    issue_id: Optional[str] = None
    confidence: Optional[float] = None
    message: str
    created_at: datetime = Field(default_factory=_utcnow)


class EscalationDraft(BaseModel):
    """Produced by this app to tickets.escalation-drafts, keyed by
    ticket_id: the watsonx Orchestrate escalation agent's proposal for an
    escalated ticket (orchestrate/drafts.py), consumed back by support-admin
    and indexable by the Real-Time Context Engine. No personal data: the
    agent's input is masked by the Orchestrate PII control, and the draft
    only restates the problem."""

    ticket_id: str
    ticket_number: str
    service: str
    tier: str
    service_status: str
    recurring_issue_same_service: bool
    reponse_suggeree: str
    geste_commercial: str
    note_conseiller: str
    voucher_eur: Optional[float] = None
    requires_human_approval: Optional[bool] = None
    duration_seconds: float
    agent: str = "watsonx Orchestrate escalation_agent"
    drafted_at: datetime = Field(default_factory=_utcnow)
