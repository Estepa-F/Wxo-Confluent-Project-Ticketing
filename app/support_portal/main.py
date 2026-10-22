import asyncio
import base64
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from mcp.server.transport_security import TransportSecuritySettings

from support_portal import pages
from support_portal.accounts.pool import AccountPool
from support_portal.admin import routes as admin
from support_portal.config import settings
from support_portal.dashboard import routes as dashboard
from support_portal.dashboard import service as dashboard_service
from support_portal.generator.synthetic import BaselineGenerator
from support_portal.incidents.state import PortalState, publish_status_snapshot
from support_portal.mcp.server import build_mcp_server
from support_portal.orchestrate import drafts as wxo_drafts
from support_portal.messaging.consumer import DashboardConsumer
from support_portal.messaging.producer import producer
from support_portal.tickets import routes as tickets
from support_portal.tickets import service as tickets_service

account_pool = AccountPool(settings.account_pool_size)
portal_state = PortalState()

# Keep the SDK's default internal route ("/mcp") and mount the sub-app at
# "/" (below, registered last) rather than mounting at "/mcp" with an
# internal "/" route -- the latter makes Starlette 307-redirect bare
# "/mcp" requests to "/mcp/", which not every MCP HTTP client follows on
# POST. mcp 2.x also rejects any request whose Host header isn't
# allowlisted (DNS-rebinding protection, on by default) -- add the
# public deployment hostname to MCP_ALLOWED_HOSTS before going live.
mcp_server = build_mcp_server(account_pool, portal_state)
wxo_drafts.configure(account_pool, portal_state)
mcp_asgi_app = mcp_server.streamable_http_app(
    transport_security=TransportSecuritySettings(
        allowed_hosts=[h.strip() for h in settings.mcp_allowed_hosts.split(",") if h.strip()],
        allowed_origins=[h.strip() for h in settings.mcp_allowed_hosts.split(",") if h.strip()],
    ),
)


class MCPBasicAuthMiddleware:
    """Requires HTTP Basic auth on the MCP mount. Per PROJECT_SPEC.md the
    only intended caller is Confluent's Flink AI_RUN_AGENT/mcp_server
    connection -- without this, the mount is a fully open,
    unauthenticated data-lookup surface reachable by anyone (confirmed
    live: unrelated bot/scanner traffic already probes it)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or self._is_authorized(scope):
            await self.app(scope, receive, send)
            return

        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [(b"www-authenticate", b'Basic realm="mcp"')],
            }
        )
        await send({"type": "http.response.body", "body": b"Unauthorized"})

    def _is_authorized(self, scope) -> bool:
        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode("latin-1")
        if not auth_header.startswith("Basic "):
            return False
        try:
            username, _, password = base64.b64decode(auth_header[6:]).decode("utf-8").partition(":")
        except Exception:
            return False
        return secrets.compare_digest(username, settings.mcp_username) and secrets.compare_digest(
            password, settings.mcp_password
        )


mcp_asgi_app = MCPBasicAuthMiddleware(mcp_asgi_app)


KAFKA_HANDLERS = {
    "tickets.enriched": [dashboard_service.handle_message],
    "tickets.metrics": [dashboard_service.handle_message],
    "tickets.agent-actions": [dashboard_service.handle_message, tickets_service.handle_agent_action],
    # Orchestrate escalation-agent proposals, published by orchestrate/drafts.py.
    "tickets.escalation-drafts": [wxo_drafts.handle_draft_message],
}

SERVICE_STATUS_HEARTBEAT_SECONDS = 60


async def _service_status_heartbeat() -> None:
    # Keeps services.status fresh even with no admin action -- a single
    # failed produce call must not kill the heartbeat for good, same
    # reasoning as BaselineGenerator._run's own try/except.
    while True:
        await asyncio.sleep(SERVICE_STATUS_HEARTBEAT_SECONDS)
        try:
            publish_status_snapshot(producer, portal_state)
        except Exception:
            logging.getLogger(__name__).exception("Service-status heartbeat failed to publish")


@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_event_loop()
    consumer = DashboardConsumer(loop, handlers=KAFKA_HANDLERS)
    consumer.start(list(KAFKA_HANDLERS))

    generator = None
    if settings.enable_generator:
        generator = BaselineGenerator(producer, rate=settings.generator_rate, portal_state=portal_state)
        generator.start()

    # Must not raise (producer is a no-op without CC_BOOTSTRAP_SERVERS,
    # e.g. local smoke-testing per messaging/producer.py's own docstring)
    # -- an unhandled exception here would crash app startup entirely.
    try:
        publish_status_snapshot(producer, portal_state)
    except Exception:
        logging.getLogger(__name__).exception("Startup service-status snapshot failed to publish")
    status_heartbeat_task = asyncio.create_task(_service_status_heartbeat())

    app.state.consumer = consumer
    app.state.generator = generator

    # The mounted MCP sub-app's streamable-HTTP session manager needs its
    # own async context manager entered for the mount to actually work --
    # Starlette does not propagate a sub-app's lifespan automatically.
    async with mcp_server.session_manager.run():
        yield

    status_heartbeat_task.cancel()
    if generator:
        generator.stop()
    consumer.stop()
    producer.flush()


app = FastAPI(title="Fake Shop Support Portal", lifespan=lifespan)
app.state.account_pool = account_pool
app.state.portal_state = portal_state
app.state.producer = producer

app.include_router(pages.router)
app.include_router(tickets.router)
app.include_router(dashboard.router)
app.include_router(admin.router)
app.mount("/static", StaticFiles(directory=Path(__file__).resolve().parent / "static"), name="static")

# Registered last: Starlette matches routes in registration order, so the
# explicit routes/mounts above always win and only unmatched paths (i.e.
# "/mcp") fall through to this catch-all mount.
app.mount("/", mcp_asgi_app)
