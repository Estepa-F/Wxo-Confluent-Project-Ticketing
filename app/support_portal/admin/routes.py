"""Admin backend: incident/burst/generator presenter controls (now driven
from dashboard.html directly) plus the support-admin ticket routes
(escalated queue + support replies, driven from support-admin.html)."""

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from support_portal.accounts.pool import is_synthetic_user_id
from support_portal.config import settings
from support_portal.incidents.known_issues import SERVICES
from support_portal.incidents.state import SERVICE_STATUS_TOPIC
from support_portal.generator.synthetic import fire_burst
from support_portal.dashboard.service import push_status
from support_portal.messaging.schemas import ServiceStatusEvent
from support_portal.tickets import service as tickets_service

logger = logging.getLogger(__name__)
router = APIRouter()

_burst_in_progress = False
_last_burst_error: str | None = None


def _check_token(x_admin_token: str | None) -> None:
    if x_admin_token != settings.admin_token:
        raise HTTPException(status_code=401, detail="Invalid admin token")


class IncidentUpdate(BaseModel):
    service: str
    status: str  # "operational" | "degraded" | "outage"
    description: str = ""


@router.post("/admin/status")
async def update_status(
    update: IncidentUpdate,
    request: Request,
    x_admin_token: str | None = Header(default=None),
):
    _check_token(x_admin_token)
    new_status = request.app.state.portal_state.set_incident(
        update.service, update.status, update.description
    )
    push_status(new_status)
    try:
        request.app.state.producer.produce_model(
            SERVICE_STATUS_TOPIC,
            key=update.service,
            model_instance=ServiceStatusEvent(
                service=update.service, status=update.status, description=update.description
            ),
        )
    except Exception:
        # In-memory state + dashboard push above already succeeded --
        # don't 500 the presenter's admin action just because the
        # producer is disabled (e.g. local smoke-testing without
        # CC_BOOTSTRAP_SERVERS, per messaging/producer.py's docstring).
        logger.exception("Failed to publish services.status event for %s", update.service)
    return new_status


class BurstRequest(BaseModel):
    service: str  # one of SERVICES, or "all"
    count: int = 15
    interval_ms: int = 400


@router.post("/admin/burst")
async def trigger_burst(
    burst: BurstRequest,
    request: Request,
    x_admin_token: str | None = Header(default=None),
):
    _check_token(x_admin_token)
    if _burst_in_progress:
        raise HTTPException(status_code=409, detail="A burst is already in progress")

    producer = request.app.state.producer

    async def _run() -> None:
        global _burst_in_progress, _last_burst_error
        _burst_in_progress = True
        _last_burst_error = None
        try:
            if burst.service == "all":
                # Split the requested count across every service instead of
                # firing `count` tickets per service -- keeps total volume
                # proportional to the requested duration regardless of scope.
                per_service = max(burst.count // len(SERVICES), 1)
                await asyncio.gather(*(
                    fire_burst(producer, service, per_service, burst.interval_ms)
                    for service in SERVICES
                ))
            else:
                await fire_burst(producer, burst.service, burst.count, burst.interval_ms)
        except Exception as exc:
            logger.exception("Burst failed")
            _last_burst_error = str(exc)
        finally:
            _burst_in_progress = False

    asyncio.create_task(_run())
    return {"started": True, "service": burst.service, "count": burst.count}


@router.get("/admin/burst-status")
async def burst_status(x_admin_token: str | None = Header(default=None)):
    _check_token(x_admin_token)
    return {"in_progress": _burst_in_progress, "last_error": _last_burst_error}


class GeneratorUpdate(BaseModel):
    action: Literal["pause", "resume", "rate"]
    rate: float | None = None  # tickets/second, required when action == "rate"


def _generator_state(generator) -> dict:
    if generator is None:
        return {"enabled": False, "running": False, "rate": 0.0}
    return {"enabled": True, "running": generator.running, "rate": generator.rate}


@router.get("/admin/generator")
async def get_generator(request: Request, x_admin_token: str | None = Header(default=None)):
    _check_token(x_admin_token)
    return _generator_state(request.app.state.generator)


@router.post("/admin/generator")
async def update_generator(
    update: GeneratorUpdate,
    request: Request,
    x_admin_token: str | None = Header(default=None),
):
    _check_token(x_admin_token)
    generator = request.app.state.generator
    if generator is None:
        raise HTTPException(status_code=409, detail="Baseline generator is disabled")

    if update.action == "pause":
        generator.pause()
    elif update.action == "resume":
        generator.resume()
    elif update.action == "rate":
        if update.rate is None:
            raise HTTPException(status_code=422, detail="rate is required for action=rate")
        generator.set_rate(update.rate)

    return _generator_state(generator)


class SupportReply(BaseModel):
    # 1500, not 500: Orchestrate drafts (orchestrate/drafts.py) run 3-5 sentences.
    message: str = Field(min_length=1, max_length=1500)


@router.get("/admin/tickets/escalated")
async def list_escalated_tickets(include_synthetic: bool = False, x_admin_token: str | None = Header(default=None)):
    _check_token(x_admin_token)
    records = tickets_service.store.list_escalated(include_synthetic=include_synthetic)
    return [
        {
            "ticket_id": r.ticket_id,
            "service": r.service,
            "subject": r.subject,
            "urgency": r.urgency,
            "sentiment": r.sentiment,
            "escalation_message": r.events[-1].message,
            "escalated_at": r.events[-1].created_at,
            "synthetic": is_synthetic_user_id(r.user_id),
            "ai_draft_status": (r.ai_draft or {}).get("status"),
        }
        for r in records
    ]


@router.get("/admin/tickets/{ticket_id}")
async def get_ticket_admin(ticket_id: str, x_admin_token: str | None = Header(default=None)):
    _check_token(x_admin_token)
    record = tickets_service.store.get(ticket_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    return record.to_detail(include_ai_draft=True)


@router.post("/admin/tickets/{ticket_id}/ai-draft")
async def request_ai_draft(ticket_id: str, x_admin_token: str | None = Header(default=None)):
    """Asks the Orchestrate escalation agent for a (new) reply draft --
    same call as the automatic one on escalation, for retries or for
    tickets escalated before the feature was configured."""
    _check_token(x_admin_token)
    from support_portal.orchestrate import client as wxo_client
    from support_portal.orchestrate import drafts

    if not wxo_client.is_configured():
        raise HTTPException(status_code=409, detail="watsonx Orchestrate is not configured (WXO_* settings).")
    if tickets_service.store.get(ticket_id) is None:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    drafts.schedule_draft(ticket_id)
    return {"started": True}


@router.post("/admin/tickets/{ticket_id}/support-reply")
async def support_reply(
    ticket_id: str,
    reply: SupportReply,
    x_admin_token: str | None = Header(default=None),
):
    _check_token(x_admin_token)
    event = tickets_service.apply_support_reply(ticket_id, reply.message)
    if event is None:
        raise HTTPException(status_code=404, detail="Ticket not found, or already closed.")
    return event
