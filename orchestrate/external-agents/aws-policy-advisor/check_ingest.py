"""Sends ONE test trace to Orchestrate from the Mac, using the same code as
the agent (wxo_tracing.py), and prints the exact response from the ingestion
endpoint. Used to verify that Orchestrate accepts our traces.

Usage: python3 check_ingest.py ../../wxo.env <AGENT_ID>
Prerequisites: pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-http
"""

import json
import os
import sys
from pathlib import Path

cfg = {}
for line in Path(sys.argv[1]).read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        cfg[k.strip()] = v.strip().strip('"').strip("'")
agent_id = sys.argv[2]
tenant = json.load(open(Path(__file__).parent / "../../../app/support_portal/static/copilot-config.json"))["orchestrationID"]

os.environ.update(
    WXO_OTEL_EXPORT_URL=cfg["WXO_URL"].rstrip("/") + "/v1/orchestrate/inject/traces",
    WXO_API_KEY=cfg["WXO_API_KEY"], WXO_TENANT_ID=tenant, WXO_AGENT_ID=agent_id,
    WXO_ENVIRONMENT="live")

import logging  # noqa: E402
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter  # noqa: E402

_orig_export = OTLPSpanExporter.export


def _spy(self, spans, *a, **kw):
    result = _orig_export(self, spans, *a, **kw)
    print(f"\nExported {len(spans)} span(s) to Orchestrate -> {result}")
    return result


OTLPSpanExporter.export = _spy

import wxo_tracing  # noqa: E402

print("Endpoint:", os.environ["WXO_OTEL_EXPORT_URL"])
print("Tenant  :", tenant)
print("Agent   :", agent_id)
with wxo_tracing.agent_run("Ingestion test from Mac") as run:
    run.output = "Test response"
if wxo_tracing._provider is None:
    print("Tracing not initialised: see message above (IAM token?)")
else:
    wxo_tracing._provider.force_flush(10000)
