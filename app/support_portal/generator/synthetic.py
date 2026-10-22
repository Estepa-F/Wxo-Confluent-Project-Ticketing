"""Synthetic ticket generation: continuous baseline traffic so Flink's
matching has realistic variety even with zero live submissions (spec
section 2.2), plus on-cue burst mode, triggered from the presenter
console, guaranteed to fuzzy-match a seeded known issue (spec sections
2.2 / 5 -- presenter controls timing precisely)."""

import asyncio
import logging
import random

from support_portal.config import settings
from support_portal.accounts.pool import SYNTHETIC_ID_START, SYNTHETIC_POOL_SIZE
from support_portal.incidents.known_issues import search_known_issues
from support_portal.incidents.state import PortalState
from support_portal.messaging.producer import TicketProducer
from support_portal.messaging.schemas import TicketRaw
from support_portal.tickets import service as tickets_service
from support_portal.tickets.samples import TICKET_SAMPLES_BY_SERVICE, TicketSample

logger = logging.getLogger(__name__)

TOPIC = "tickets.raw"

# A service's health biases both how often it's picked and how urgent the
# generated ticket looks, so the demo's "degraded/down services drive more
# and worse tickets" story (spec section 12) holds without any explicit
# scripting by the presenter.
HEALTH_WEIGHTS: dict[str, float] = {"operational": 1.0, "degraded": 2.0, "outage": 4.0}
URGENCY_WEIGHTS_BY_HEALTH: dict[str, dict[str, float]] = {
    "operational": {"low": 0.6, "medium": 0.3, "high": 0.1},
    "degraded": {"low": 0.3, "medium": 0.4, "high": 0.3},
    "outage": {"low": 0.1, "medium": 0.3, "high": 0.6},
}


def _weighted_service(services: list[str], status: dict[str, str]) -> str:
    weights = [HEALTH_WEIGHTS.get(status.get(s, "operational"), 1.0) for s in services]
    return random.choices(services, weights=weights, k=1)[0]


def _weighted_urgency(service: str, status: dict[str, str]) -> str:
    dist = URGENCY_WEIGHTS_BY_HEALTH.get(status.get(service, "operational"), URGENCY_WEIGHTS_BY_HEALTH["operational"])
    return random.choices(list(dist), weights=list(dist.values()), k=1)[0]


def emit_ticket(producer: TicketProducer, service: str | None = None, status: dict[str, str] | None = None) -> TicketRaw:
    status = status or {}
    service = service or _weighted_service(list(TICKET_SAMPLES_BY_SERVICE), status)
    sample = random.choice(TICKET_SAMPLES_BY_SERVICE[service])
    user_id = random.randint(SYNTHETIC_ID_START, SYNTHETIC_ID_START + SYNTHETIC_POOL_SIZE - 1)
    urgency = _weighted_urgency(service, status)
    # Registers a real TicketRecord (not just a Kafka message) so this
    # ticket can be looked up by ticket_id later -- e.g. tickets/service.py's
    # handle_agent_action, which otherwise silently no-ops for unknown ids.
    record = tickets_service.store.create(
        user_id=user_id, service=service, subject=sample.subject, description=sample.details, urgency=urgency
    )
    ticket = TicketRaw(
        ticket_id=record.ticket_id,
        user_id=user_id,
        text=sample.details or sample.subject,
        urgency_self_rated=urgency,
        source="synthetic",
        service=service,
        subject=sample.subject,
    )
    producer.produce_model(TOPIC, key=ticket.ticket_id, model_instance=ticket)
    return ticket


class BaselineGenerator:
    def __init__(self, producer: TicketProducer, rate: float, portal_state: PortalState):
        self._producer = producer
        self._rate = max(rate, 0.01)
        self._portal_state = portal_state
        self._paused = False
        self._task: asyncio.Task | None = None

    @property
    def rate(self) -> float:
        return self._rate

    @property
    def running(self) -> bool:
        return not self._paused

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def set_rate(self, rate: float) -> None:
        self._rate = max(rate, 0.01)

    async def _run(self) -> None:
        # A single failed produce call must not kill baseline traffic for
        # the rest of the event -- log and keep going.
        while True:
            await asyncio.sleep(1.0 / self._rate)
            if self._paused:
                continue
            try:
                emit_ticket(self._producer, status=self._portal_state.get_service_status())
            except Exception:
                logger.exception("Baseline generator failed to emit a ticket")


def _burst_candidates(service: str) -> list[TicketSample]:
    """tickets.csv rows that actually fuzzy-match a known issue for this
    service, verified live against search_known_issues() rather than
    trusted from a comment -- guarantees burst tickets can auto-resolve.
    Query text mirrors what the live agent sends (subject + description,
    see 03_statements_triage_agent.tf), so this stays accurate to runtime
    behavior rather than a narrower, stale definition of "matches"."""
    candidates = []
    for sample in TICKET_SAMPLES_BY_SERVICE.get(service, []):
        details = sample.details or ""
        text = f"{sample.subject}. {details}" if details else sample.subject
        result = search_known_issues(text, settings.match_threshold)
        if result["matched"] and result["service"] == service:
            candidates.append(sample)
    return candidates


# Computed once at import, like TICKET_SAMPLES_BY_SERVICE itself.
BURST_CANDIDATES_BY_SERVICE: dict[str, list[TicketSample]] = {
    service: _burst_candidates(service) for service in TICKET_SAMPLES_BY_SERVICE
}


async def fire_burst(producer: TicketProducer, service: str, count: int, interval_ms: int) -> int:
    candidates = BURST_CANDIDATES_BY_SERVICE.get(service)
    if not candidates:
        raise ValueError(f"No tickets.csv rows fuzzy-match a known issue for service '{service}'")

    sent = 0
    for _ in range(count):
        sample = random.choice(candidates)
        user_id = random.randint(SYNTHETIC_ID_START, SYNTHETIC_ID_START + SYNTHETIC_POOL_SIZE - 1)
        record = tickets_service.store.create(
            user_id=user_id, service=service, subject=sample.subject, description=sample.details, urgency=sample.urgency
        )
        ticket = TicketRaw(
            ticket_id=record.ticket_id,
            user_id=user_id,
            text=sample.details or sample.subject,
            urgency_self_rated=sample.urgency,
            source="synthetic",
            service=service,
            subject=sample.subject,
        )
        producer.produce_model(TOPIC, key=ticket.ticket_id, model_instance=ticket)
        sent += 1
        await asyncio.sleep(interval_ms / 1000)
    return sent
