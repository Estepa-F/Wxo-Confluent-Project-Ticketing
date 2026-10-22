"""Send this agent's own traces to watsonx Orchestrate (Analyze / Observability).

Follows the ADK page "Exporting observability traces with OpenTelemetry":
OTLP/HTTP to {instance}/v1/orchestrate/inject/traces, bearer token from IBM
Cloud IAM, resource attributes tenant.id + deployment.environment, and
agent.id / langfuse.session.id / langfuse.user.id on the root span.

Design choices for a live demo:
- Off unless WXO_OTEL_EXPORT_URL, WXO_API_KEY, WXO_TENANT_ID and WXO_AGENT_ID
  are all set: removing the variables disables it.
- A private TracerProvider, never the global one: AgentCore already runs its
  own OpenTelemetry instrumentation (CloudWatch / X-Ray) and must not be
  touched, nor send its spans to Orchestrate.
- Fail-safe: any tracing error is logged and swallowed, the answer is never
  blocked. The IAM token is refreshed before it expires (1 h).
"""

import json
import logging
import os
import time
import urllib.parse
import urllib.request
import uuid
from contextlib import contextmanager

log = logging.getLogger("wxo_tracing")

_tracer = None
_provider = None
_exporter = None
_token_exp = 0.0


def _env(name):
    return os.environ.get(name, "").strip()


def enabled():
    return all(_env(n) for n in ("WXO_OTEL_EXPORT_URL", "WXO_API_KEY", "WXO_TENANT_ID", "WXO_AGENT_ID"))


def _iam_token():
    data = urllib.parse.urlencode({
        "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
        "apikey": _env("WXO_API_KEY"),
    }).encode()
    req = urllib.request.Request(
        _env("WXO_TOKEN_URL") or "https://iam.cloud.ibm.com/identity/token", data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        body = json.loads(r.read().decode())
    return body["access_token"], time.time() + int(body.get("expires_in", 3600))


def _setup():
    global _tracer, _provider, _exporter, _token_exp
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    token, _token_exp = _iam_token()
    _exporter = OTLPSpanExporter(endpoint=_env("WXO_OTEL_EXPORT_URL"),
                                 headers={"Authorization": f"Bearer {token}"}, timeout=5)
    resource = Resource.create({
        "service.name": "goodwill-policy-advisor",
        "service.version": "1.0.0",
        "application": "aws-agentcore",
        "tenant.id": _env("WXO_TENANT_ID"),
        "deployment.environment": _env("WXO_ENVIRONMENT") or "live",
    })
    _provider = TracerProvider(resource=resource)
    # Export in a background thread (a slow or unreachable endpoint never
    # delays the answer), then a short bounded flush at the end of each run so
    # the span leaves before the AgentCore session can be frozen.
    _provider.add_span_processor(BatchSpanProcessor(_exporter, schedule_delay_millis=500))
    _tracer = _provider.get_tracer("goodwill-policy-advisor")


def _refresh_token_if_needed():
    """IAM tokens last 1 h. Rebuild the exporter with a fresh token instead
    of touching exporter internals (they changed across OTel versions)."""
    global _tracer, _provider
    if time.time() > _token_exp - 300:
        old = _provider
        _tracer = _provider = None
        _setup()
        try:
            old.shutdown()
        except Exception:
            pass


class _Run:
    output = ""


@contextmanager
def agent_run(user_input: str):
    """Wrap one agent run for Orchestrate. Yields an object whose .output the
    caller sets to the final answer. Never raises because of tracing.

    Two spans per run:
    - a ROOT span in a brand-new trace, carrying agent.id and the langfuse
      ids: this is what Analytics counts as a conversation of this agent.
      When Orchestrate calls us as a collaborator, the incoming request
      carries Orchestrate's own trace context; a span created in that
      context joins the copilot's trace and is NOT counted for this agent.
    - a CHILD span in the incoming context (when there is one), so the
      copilot's trace also shows the time spent inside the AWS agent.
    """
    run = _Run()
    if not enabled():
        yield run
        return
    root = child = None
    try:
        from opentelemetry import context as otel_context, trace as otel_trace
        from opentelemetry.trace import Link

        if _tracer is None:
            _setup()
        else:
            _refresh_token_if_needed()
        incoming = otel_trace.get_current_span().get_span_context()
        links = [Link(incoming)] if incoming and incoming.is_valid else None
        root = _tracer.start_span("goodwill_policy_advisor.run",
                                  context=otel_context.Context(), links=links)
        root.set_attribute("agent.id", _env("WXO_AGENT_ID"))
        root.set_attribute("langfuse.session.id", str(uuid.uuid4()))
        root.set_attribute("langfuse.user.id", "usr_orchestrate_a2a")
        root.set_attribute("input", user_input[:4000])
        if incoming and incoming.is_valid:
            child = _tracer.start_span("goodwill_policy_advisor (AWS AgentCore)")
            child.set_attribute("input", user_input[:4000])
    except Exception as exc:  # tracing must never break the agent
        log.warning("Orchestrate tracing disabled for this run: %s", exc)
        root = child = None
    start = time.time()
    try:
        yield run
    finally:
        for span in (child, root):
            if span is None:
                continue
            try:
                span.set_attribute("output", (run.output or "")[:4000])
                span.set_attribute("duration_seconds", round(time.time() - start, 2))
                span.end()
            except Exception as exc:
                log.warning("tracing end: %s", exc)
        if root is not None:
            try:
                _provider.force_flush(timeout_millis=1500)
            except Exception as exc:
                log.warning("tracing flush: %s", exc)
