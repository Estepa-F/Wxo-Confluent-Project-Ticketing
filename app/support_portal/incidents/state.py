"""In-memory, thread-safe per-service status + open incidents. Mutated
live via POST /admin/status — not automated, so the presenter controls
timing precisely (spec section 2.3 / 5)."""

import threading

from support_portal.incidents.known_issues import SERVICES
from support_portal.messaging.producer import TicketProducer
from support_portal.messaging.schemas import ServiceStatusEvent

SERVICE_STATUS_TOPIC = "services.status"


class PortalState:
    def __init__(self):
        self._lock = threading.Lock()
        self.service_status: dict[str, str] = {s: "operational" for s in SERVICES}
        self.incidents: list[dict] = []

    def get_status(self) -> dict:
        with self._lock:
            return {"services": dict(self.service_status), "incidents": list(self.incidents)}

    def get_service_status(self) -> dict[str, str]:
        with self._lock:
            return dict(self.service_status)

    def set_incident(self, service: str, status: str, description: str = "") -> dict:
        with self._lock:
            self.service_status[service] = status
            self.incidents = [i for i in self.incidents if i["service"] != service]
            if status != "operational":
                self.incidents.append({"service": service, "status": status, "description": description})
            return {"services": dict(self.service_status), "incidents": list(self.incidents)}

    def _incident_description(self, service: str) -> str:
        return next((i["description"] for i in self.incidents if i["service"] == service), "")


def publish_status_snapshot(producer: TicketProducer, state: PortalState) -> None:
    """Publishes one ServiceStatusEvent per known service to the compacted
    services.status topic, keyed by service -- used both for the one-time
    startup snapshot and the recurring heartbeat (main.py's lifespan).
    Kept separate from the immediate publish-on-change in admin/routes.py's
    update_status, which fires right away instead of waiting for the next
    snapshot."""
    status = state.get_service_status()
    for service in SERVICES:
        producer.produce_model(
            SERVICE_STATUS_TOPIC,
            key=service,
            model_instance=ServiceStatusEvent(
                service=service,
                status=status.get(service, "operational"),
                description=state._incident_description(service),
            ),
        )
