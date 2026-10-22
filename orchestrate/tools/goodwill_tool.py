"""Orchestrate tool that calls the AWS "Goodwill" agent via A2A.

Why a tool rather than a collaborator: declared as a collaborator, the
external AWS agent "takes over" (Transferring to…) and its raw response
terminates the turn; the escalation agent can never write its synthesis
(tests from September 28, ReAct and Plan-Act styles). Called as a tool,
the same AWS agent returns its JSON to the escalation agent, which keeps
control.

Authentication: OAuth2 token (client credentials, Cognito pool wxo-a2a)
obtained and renewed by the Orchestrate bedrock_cognito_a2a connection,
associated with the tool at import (--app-id bedrock_cognito_a2a).
"""

import json
import uuid

import requests
from ibm_watsonx_orchestrate.agent_builder.connections import ConnectionType, ExpectedCredentials
from ibm_watsonx_orchestrate.agent_builder.tools import ToolPermission, tool
from ibm_watsonx_orchestrate.run import connections

APP_ID = "bedrock_cognito_a2a"
# AWS agent invocation URL (encoded ARN). rebuild_wxo.sh rewrites this
# line from AGENTCORE_ARN when deploying to a different AWS account.
AGENTCORE_URL = "https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/<ENCODED_ARN>/invocations?qualifier=DEFAULT"


def _raw_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start : end + 1])


@tool(
    permission=ToolPermission.READ_ONLY,
    expected_credentials=[ExpectedCredentials(app_id=APP_ID, type=ConnectionType.OAUTH2_CLIENT_CREDS)],
)
def ask_goodwill_agent(
    tier: str,
    service: str,
    service_status: str,
    recurring_issue_same_service: bool,
    issue_summary: str,
) -> dict:
    """Asks the AWS Customer Relations agent for the commercial gesture for an escalated ticket.

    Never transmit personal data: no name, email, phone, address, order
    number, or card number.

    Args:
        tier (str): Customer tier: bronze, silver, gold, or unknown.
        service (str): Affected service: login, checkout, payments, search, notifications, order-tracking.
        service_status (str): Service status: operational, degraded, outage, or unknown.
        recurring_issue_same_service (bool): True if the customer recently reported an issue on the same service.
        issue_summary (str): One or two sentences describing the problem, without any personal data.

    Returns:
        dict: gesture (none or voucher), voucher_eur, extras, requires_human_approval and justification in English.
    """
    creds = connections.oauth2_client_creds(APP_ID)
    text = (
        f"tier: {tier}\nservice: {service}\nservice_status: {service_status}\n"
        f"recurring_issue_same_service: {str(recurring_issue_same_service).lower()}\n"
        f"issue_summary: {issue_summary}"
    )
    body = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "message/send",
        "params": {
            "message": {
                "kind": "message",
                "role": "user",
                "messageId": str(uuid.uuid4()),
                "parts": [{"kind": "text", "text": text}],
            }
        },
    }
    try:
        resp = requests.post(
            AGENTCORE_URL,
            json=body,
            headers={"Authorization": f"Bearer {creds.access_token}"},
            timeout=60,
        )
        resp.raise_for_status()
        result = resp.json().get("result", {})
        parts = [
            p.get("text", "")
            for artifact in result.get("artifacts") or []
            for p in artifact.get("parts", [])
            if p.get("kind") == "text"
        ]
        return _raw_json("".join(parts))
    except Exception as exc:  # the agent must still draft a reply without a gesture
        return {
            "gesture": "none",
            "voucher_eur": 0,
            "extras": [],
            "requires_human_approval": True,
            "justification": f"AWS agent unavailable ({type(exc).__name__}): gesture must be decided manually by the support agent.",
        }
