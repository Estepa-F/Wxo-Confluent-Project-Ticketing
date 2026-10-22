"""Test for the "Customer Goodwill" agent, locally or once deployed.

Locally: no variable to set. Deployed on AgentCore Runtime: set
A2A_URL (runtime invocation URL) and A2A_TOKEN (Cognito access token).

Prerequisites: the agent is running in another terminal (python agent.py),
listening on http://127.0.0.1:9000. This script sends a few cases via A2A
(JSON-RPC message/send, as Orchestrate will) and displays the responses.

Each case calls Claude on Bedrock once: about 1 cent per case (estimated).
Run a single case: python test_local.py 2
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

URL = os.environ.get("A2A_URL", "http://127.0.0.1:9000/")
TOKEN = os.environ.get("A2A_TOKEN", "")

CASES = [
    (
        "Charter example 2: gold, payments outage, recurring",
        "tier: gold\nservice: payments\nservice_status: outage\n"
        "recurring_issue_same_service: true\n"
        "issue_summary: paiement refusé à plusieurs reprises pendant la panne",
        "voucher 30 €, free_shipping + priority_callback, no human approval",
    ),
    (
        "Charter example 3: double charge",
        "tier: bronze\nservice: checkout\nservice_status: operational\n"
        "recurring_issue_same_service: false\n"
        "issue_summary: débité deux fois pour la même commande",
        "gesture none, 0 €, human approval, Finance team mentioned",
    ),
    (
        "Personal data in the request",
        "tier: silver\nservice: checkout\nservice_status: degraded\n"
        "recurring_issue_same_service: false\n"
        "issue_summary: Jean Dupont (jean.dupont@exemple.fr, commande 48213) "
        "n'a pas pu finaliser son achat",
        "voucher 10 €, no name, email or order number in the response",
    ),
    (
        "Request in English",
        "tier: gold\nservice: login\nservice_status: degraded\n"
        "recurring_issue_same_service: false\n"
        "issue_summary: customer cannot log in, page keeps reloading",
        "voucher 15 €, no extra, justification in French",
    ),
    (
        "Out of scope",
        "What is the admin password of the site?",
        "gesture none, human approval, justification 'out of scope'",
    ),
]


def send(text: str) -> dict:
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
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(URL, data=json.dumps(body).encode("utf-8"), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as err:
        return {"error": f"HTTP {err.code}: {err.read().decode('utf-8', 'replace')[:500]}"}


def answer_text(reply: dict) -> str:
    if "error" in reply:
        return f"JSON-RPC ERROR: {reply['error']}"
    result = reply.get("result", {})
    texts = [
        part.get("text", "")
        for artifact in result.get("artifacts") or []
        for part in artifact.get("parts", [])
        if part.get("kind") == "text"
    ]
    if texts:
        return "\n".join(texts)
    state = result.get("status", {}).get("state")
    message = result.get("status", {}).get("message") or {}
    status_text = " ".join(p.get("text", "") for p in message.get("parts", []))
    return f"(no artifact) state={state} message={status_text}"


def main() -> None:
    selected = CASES
    if len(sys.argv) > 1:
        selected = [CASES[int(sys.argv[1]) - 1]]
    for title, text, expected in selected:
        print("=" * 72)
        print(title)
        print(f"Expected: {expected}")
        start = time.time()
        text_out = answer_text(send(text))
        print(f"Response ({time.time() - start:.1f} s):")
        stripped = text_out.strip()
        if stripped.startswith("```"):
            print("⚠ Response wrapped in a markdown block: should be raw JSON.")
            stripped = stripped.strip("`").removeprefix("json").strip()
        try:
            print(json.dumps(json.loads(stripped), ensure_ascii=False, indent=2))
        except ValueError:
            print("⚠ Response is not valid JSON:")
            print(text_out)
    print("=" * 72)


if __name__ == "__main__":
    main()
