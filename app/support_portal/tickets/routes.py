"""Ticket lifecycle HTTP + WebSocket surface (spec: docs/specs/ticket-lifecycle/spec.md).
Ticket creation carries service/subject/details instead of a single
free-text field; this module owns creation, listing, detail, replies,
close, and the per-ticket WebSocket. Business logic (the shared store,
Kafka agent-action dispatch) lives in tickets/service.py.
"""

from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

from support_portal.incidents.known_issues import SERVICES
from support_portal.messaging.schemas import TicketRaw
from support_portal.tickets import service
from support_portal.tickets.store import TicketRecord

router = APIRouter()

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
TOPIC = "tickets.raw"
COOKIE_NAME = "user_id"


class TicketCreate(BaseModel):
    service: Literal[tuple(SERVICES)]  # type: ignore[valid-type]
    subject: str = Field(min_length=1, max_length=100)
    details: Optional[str] = Field(default=None, max_length=500)
    urgency: Literal["low", "medium", "high"] = "medium"


class ReplyCreate(BaseModel):
    message: str = Field(min_length=1, max_length=500)


def _require_user_id(request: Request) -> int:
    raw = request.cookies.get(COOKIE_NAME)
    if raw is None:
        raise HTTPException(status_code=400, detail="Missing check-in cookie; reload the page.")
    return int(raw)


def _require_owned_ticket(request: Request, ticket_id: str) -> TicketRecord:
    user_id = _require_user_id(request)
    record = service.store.get(ticket_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    if record.user_id != user_id:
        raise HTTPException(status_code=403, detail="This ticket does not belong to you.")
    return record


# --- REST endpoints ---


@router.post("/api/tickets")
async def create_ticket(request: Request, submission: TicketCreate):
    user_id = _require_user_id(request)
    record = service.store.create(
        user_id=user_id,
        service=submission.service,
        subject=submission.subject,
        description=submission.details,
        urgency=submission.urgency,
    )

    text = submission.subject if not submission.details else f"{submission.subject}. {submission.details}"
    raw = TicketRaw(
        ticket_id=record.ticket_id,
        user_id=user_id,
        text=text,
        urgency_self_rated=submission.urgency,
        source="live",
        service=submission.service,
        subject=submission.subject,
    )
    request.app.state.producer.produce_model(TOPIC, key=record.ticket_id, model_instance=raw)
    request.app.state.account_pool.record_ticket(user_id, submission.service)

    return record.to_detail()


@router.get("/api/tickets")
async def list_tickets(request: Request):
    user_id = _require_user_id(request)
    return [r.to_summary() for r in service.store.list_for_user(user_id)]


@router.get("/api/tickets/{ticket_id}")
async def get_ticket(request: Request, ticket_id: str):
    record = _require_owned_ticket(request, ticket_id)
    return record.to_detail()


@router.post("/api/tickets/{ticket_id}/replies")
async def reply_to_ticket(request: Request, ticket_id: str, reply: ReplyCreate):
    record = _require_owned_ticket(request, ticket_id)
    if record.status == "closed":
        raise HTTPException(status_code=400, detail="This ticket is closed.")

    event, context = service.store.add_reply(ticket_id, reply.message)

    raw = TicketRaw(
        ticket_id=ticket_id,
        user_id=record.user_id,
        text=context,
        urgency_self_rated=record.urgency,
        source="live",
        service=record.service,
        subject=record.subject,
    )
    request.app.state.producer.produce_model(TOPIC, key=ticket_id, model_instance=raw)

    return event


@router.post("/api/tickets/{ticket_id}/close")
async def close_ticket(request: Request, ticket_id: str):
    record = _require_owned_ticket(request, ticket_id)
    if record.status == "closed":
        raise HTTPException(status_code=400, detail="This ticket is already closed.")

    event = service.store.close(ticket_id)
    return {"ticket_id": ticket_id, "status": "closed", "closed_at": event.created_at}


# --- Pages ---


@router.get("/tickets")
async def tickets_page(request: Request):
    # Check-in only happens at "/" (see pages.py); landing here directly
    # (bookmark, shared link, lost cookie) with no user_id cookie would
    # otherwise 400 on every /api/tickets call with no way to recover.
    if request.cookies.get(COOKIE_NAME) is None:
        return RedirectResponse("/")
    return FileResponse(STATIC_DIR / "tickets.html")


@router.get("/tickets/{ticket_id}")
async def ticket_detail_page(request: Request, ticket_id: str):
    if request.cookies.get(COOKIE_NAME) is None:
        return RedirectResponse("/")
    return FileResponse(STATIC_DIR / "ticket-detail.html")


# --- WebSocket ---


@router.websocket("/ws/tickets/{ticket_id}")
async def ticket_ws(websocket: WebSocket, ticket_id: str):
    record = service.store.get(ticket_id)
    if record is None:
        await websocket.close(code=4404)
        return
    cookie_user = websocket.cookies.get(COOKIE_NAME)
    if cookie_user is not None and int(cookie_user) != record.user_id:
        await websocket.close(code=4403)
        return

    await websocket.accept()
    service.register_connection(ticket_id, websocket)
    await websocket.send_json({"type": "snapshot", "data": record.to_detail().model_dump(mode="json")})
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        service.unregister_connection(ticket_id, websocket)
