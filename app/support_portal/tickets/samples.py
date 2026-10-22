"""Canned per-service ticket content for the "Generate for me" option on
new-ticket.html. tickets.csv is a checked-in asset that's always present,
so this loads eagerly at import time with no missing-file handling."""

import csv
from dataclasses import dataclass
from pathlib import Path

from support_portal.incidents.known_issues import SERVICES

CSV_PATH = Path(__file__).resolve().parent / "tickets.csv"
_VALID_URGENCIES = {"low", "medium", "high"}
_URGENCY_ALIASES = {"critical": "high"}
# tickets.csv's bulk-generated rows spell services with spaces/singulars
# rather than the app's canonical slugs (known_issues.SERVICES) -- without
# this, ~30% of rows (order tracking, notification) are silently dropped.
_SERVICE_ALIASES = {"order tracking": "order-tracking", "notification": "notifications"}


@dataclass(frozen=True)
class TicketSample:
    subject: str
    details: str | None
    urgency: str


def _load() -> dict[str, list[TicketSample]]:
    samples: dict[str, list[TicketSample]] = {service: [] for service in SERVICES}
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            service = row["service"].strip()
            service = _SERVICE_ALIASES.get(service, service)
            if service not in samples:
                continue
            urgency = row.get("urgency", "").strip().lower()
            urgency = _URGENCY_ALIASES.get(urgency, urgency)
            if urgency not in _VALID_URGENCIES:
                urgency = "medium"
            samples[service].append(TicketSample(
                subject=row["subject"].strip(),
                details=row.get("description", "").strip() or None,
                urgency=urgency,
            ))
    return samples


TICKET_SAMPLES_BY_SERVICE: dict[str, list[TicketSample]] = _load()
