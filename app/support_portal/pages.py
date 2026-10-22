"""Check-in is folded into the ticket page itself: GET / assigns a
user_id cookie inline (if the visitor doesn't have one this session) and
serves the ticket form directly -- no separate visible check-in step."""

import json
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse

from support_portal.tickets.samples import TICKET_SAMPLES_BY_SERVICE

router = APIRouter()

STATIC_DIR = Path(__file__).resolve().parent / "static"
COOKIE_NAME = "user_id"


def _render_new_ticket_html() -> str:
    """Injects the per-service ticket samples as inline JSON so
    new-ticket.html's "Generate for me" button can pick one client-side
    with no extra request -- computed once, not per-request."""
    html = (STATIC_DIR / "new-ticket.html").read_text()
    samples_json = json.dumps({
        service: [{"subject": s.subject, "details": s.details, "urgency": s.urgency} for s in samples]
        for service, samples in TICKET_SAMPLES_BY_SERVICE.items()
    })
    injected = f"<script>window.TICKET_SAMPLES = {samples_json};</script>\n"
    return html.replace("<script>", injected + "<script>", 1)


_NEW_TICKET_HTML = _render_new_ticket_html()


@router.get("/")
async def ticket_page(request: Request):
    account_pool = request.app.state.account_pool
    existing = request.cookies.get(COOKIE_NAME)
    if existing is not None:
        resp = HTMLResponse(_NEW_TICKET_HTML)
        if request.cookies.get("tier") is None:
            # Backfills the tier cookie for sessions that checked in before
            # it existed -- without this, anyone with an older user_id
            # cookie would never get a tier cookie set for the rest of
            # their 6-hour session.
            account = account_pool.get(int(existing))
            if account is not None:
                resp.set_cookie("tier", account.tier, max_age=60 * 60 * 6, httponly=False, samesite="lax")
        return resp

    user_id = account_pool.check_in()
    if user_id is None:
        return FileResponse(STATIC_DIR / "full.html", status_code=503)

    account = account_pool.get(user_id)
    resp = HTMLResponse(_NEW_TICKET_HTML)
    resp.set_cookie(COOKIE_NAME, str(user_id), max_age=60 * 60 * 6, httponly=False, samesite="lax")
    resp.set_cookie("tier", account.tier, max_age=60 * 60 * 6, httponly=False, samesite="lax")
    return resp


@router.get("/dashboard")
async def dashboard_page():
    return FileResponse(STATIC_DIR / "dashboard.html")


@router.get("/support-admin")
async def support_admin_page():
    return FileResponse(STATIC_DIR / "support-admin.html")


@router.get("/status")
async def get_status(request: Request):
    return request.app.state.portal_state.get_status()
