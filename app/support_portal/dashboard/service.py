"""Live dashboard pub/sub + metrics aggregation. handle_message is invoked
from the Kafka consumer's background thread via loop.call_soon_threadsafe,
so it always runs on the event loop and can safely schedule the async
broadcast."""

import asyncio
import time
from collections import defaultdict, deque

from fastapi import WebSocket

_connections: set[WebSocket] = set()
_recent_actions: list[dict] = []
# service -> window_end -> row. tickets.metrics is now partitioned per
# service (01_statements_ticket_metrics.tf's PARTITION BY service, added
# to fix MISSING_PARTITION_BY_FOR_OVER_WINDOW/UPSERT_AND_PRIMARY_KEYS_
# DIFFERENT), so each service gets its own line on the dashboard instead
# of one global rollup. Keyed by window_end within each service (not a
# plain list) for the same reason as before: tickets.raw has multiple
# partitions, so Flink emits windows out of order, and a revision for a
# window already seen should overwrite rather than duplicate.
_recent_metrics: dict[str, dict[str, dict]] = {}
_urgency_counts: dict[str, int] = {"low": 0, "medium": 0, "high": 0}
_last_status: dict | None = None
# Running totals for the dashboard KPI cards -- the Kafka topics themselves
# carry no cumulative counts, so this is the only place that survives a
# dashboard page reload without replaying the full topic history.
_counters: dict[str, int] = {"total_tickets": 0, "auto_resolved": 0, "escalated": 0}

# Per-service state that used to live only in dashboard.html's JS (and so
# reset to empty on every page reload/new tab) -- tracked here instead so
# it's included in snapshot() like the counters above.
SENTIMENT_WINDOW = 50  # matches dashboard.html's SENTIMENT_WINDOW
RATE_HISTORY_SECONDS = 90  # a bit more than dashboard.html's ~80s sparkline window
TICKET_SERVICE_MAP_SIZE = 500  # matches dashboard.html's ticketServiceMap cap
VOLUME_WINDOW_POINTS = 100  # 100 x Flink's 15-minute tumbling window covers 24h+ (24*60/15=96) for the "1d" zoom preset; matches dashboard.html's VOLUME_MAX_POINTS
_service_totals: dict[str, int] = defaultdict(int)
_service_sentiment: dict[str, deque] = defaultdict(lambda: deque(maxlen=SENTIMENT_WINDOW))
_service_recent_timestamps: dict[str, list[float]] = defaultdict(list)
_incidents: list[dict] = []
_ticket_service_map: dict[str, str] = {}


def snapshot() -> dict:
    return {
        "urgency_counts": dict(_urgency_counts),
        "recent_metrics": {
            service: sorted(rows.values(), key=lambda m: m["window_end"])[-VOLUME_WINDOW_POINTS:]
            for service, rows in _recent_metrics.items()
        },
        "recent_actions": _recent_actions[-20:],
        "status": _last_status,
        "counters": dict(_counters),
        "service_totals": dict(_service_totals),
        "service_sentiment": {svc: list(buf) for svc, buf in _service_sentiment.items()},
        "service_recent_timestamps": dict(_service_recent_timestamps),
        "incidents": list(_incidents),
    }


def register_connection(ws: WebSocket) -> None:
    _connections.add(ws)


def unregister_connection(ws: WebSocket) -> None:
    _connections.discard(ws)


async def _broadcast(event: dict) -> None:
    dead = []
    for ws in list(_connections):
        try:
            await ws.send_json(event)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _connections.discard(ws)


def _remember_ticket_service(ticket_id: str, service: str) -> None:
    if not ticket_id:
        return
    if len(_ticket_service_map) >= TICKET_SERVICE_MAP_SIZE and ticket_id not in _ticket_service_map:
        _ticket_service_map.pop(next(iter(_ticket_service_map)))
    _ticket_service_map[ticket_id] = service


def handle_message(topic: str, value: dict) -> None:
    if topic == "tickets.enriched":
        # AI_SENTIMENT returns ROW<sentiment ARRAY<ROW<aspect, label,
        # score>>, metadata> (kept as one whole column, sentiment_analysis,
        # by 02_statements_ticket_enrichment.tf -- see its comment for why
        # it isn't decomposed in SQL). With a single aspect (ARRAY[service]),
        # that array has exactly one entry. Flatten it back to the plain
        # 'positive'/'negative'/'neutral' string the rest of the dashboard
        # (the deque below, dashboard.html's bar chart, schemas.py) expects.
        #
        # Confirmed live: AI_SENTIMENT's real label is capitalized
        # ('Negative'/'Positive'/'Neutral'), not lowercase, and it also
        # returns 'UNKNOWN' whenever the model can't find the aspect
        # actually discussed in the text (common here, since customers
        # don't always name their own service). dashboard.html's bucket
        # counting checks exact lowercase 'positive'/'neutral'/'negative'
        # keys and treats its "negative" percentage as a *remainder*
        # (100 - pos - neu), so an unrecognized label like 'UNKNOWN'
        # silently gets counted as negative instead of excluded --
        # lowercase the real label and drop 'unknown' entirely (treated
        # as no sentiment signal, same as a missing/null label already
        # was) rather than let it skew the negative bucket.
        aspects = (value.get("sentiment_analysis") or {}).get("sentiment") or []
        label = aspects[0].get("label") if aspects else None
        label = label.lower() if label else None
        value = {**value, "sentiment": label if label and label != "unknown" else None}

        urgency = value.get("urgency_self_rated", "low")
        _urgency_counts[urgency] = _urgency_counts.get(urgency, 0) + 1
        _counters["total_tickets"] += 1
        service = value.get("service")
        if service:
            _service_totals[service] += 1
            _remember_ticket_service(value.get("ticket_id"), service)
            if value.get("sentiment"):
                _service_sentiment[service].append(value["sentiment"])
            timestamps = _service_recent_timestamps[service]
            timestamps.append(time.time() * 1000)
            cutoff = time.time() * 1000 - RATE_HISTORY_SECONDS * 1000
            while timestamps and timestamps[0] < cutoff:
                timestamps.pop(0)
        event = {"type": "enriched", "data": value}
    elif topic == "tickets.metrics":
        # Flink's real column/field names (ticket_count, forecast: [...])
        # don't match what the dashboard chart expects (count,
        # forecast_next as a single near-term scalar) -- add the expected
        # aliases without dropping the original fields, in case a richer
        # UI wants the full forecast array later.
        forecast = value.get("forecast") or []
        value = {
            **value,
            "count": value.get("ticket_count"),
            "forecast_next": forecast[0].get("forecast_value") if forecast else None,
        }
        service = value.get("service")
        window_end = value.get("window_end")
        if service and window_end:
            _recent_metrics.setdefault(service, {})[window_end] = value
        event = {"type": "metrics", "data": value}
    elif topic == "tickets.agent-actions":
        # decision/message now arrive pre-computed from Flink
        # (03_statements_triage_agent.tf's run_triage_agent extracts them
        # from AI_RUN_AGENT's raw response via REGEXP_EXTRACT), so these
        # KPI counters and the activity feed read the same fields
        # tickets/service.py's handle_agent_action does, rather than each
        # re-parsing the raw response text independently.
        if not value.get("service"):
            remembered = _ticket_service_map.get(value.get("ticket_id"))
            if remembered:
                value = {**value, "service": remembered}
        action = value.get("decision", "escalate")
        message = value.get("message") or value.get("response")
        value = {**value, "action": action, "message": message}
        _recent_actions.append(value)
        if action == "auto_resolve":
            _counters["auto_resolved"] += 1
        elif action == "escalate":
            _counters["escalated"] += 1
        event = {"type": "agent_action", "data": value}
    else:
        return
    asyncio.create_task(_broadcast(event))


def push_status(status: dict) -> None:
    global _last_status
    previous_services = (_last_status or {}).get("services") or {}
    for service, value in (status.get("services") or {}).items():
        if value != previous_services.get(service) and value != "operational":
            _incidents.append({"ts": time.time() * 1000, "service": service, "status": value})
    del _incidents[:-20]
    _last_status = status
    asyncio.create_task(_broadcast({"type": "status", "data": status}))
