"""Test for the Commercial Policy Advisor deployed on AgentCore, via A2A,
with a real Cognito token (as Orchestrate uses).

Usage: python3 test.py <ARN> ["question"]
The Cognito client secret is read via the AWS CLI (AWS_PROFILE).
About 1 cent of Bedrock per question.
"""

import base64
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid

def _require(name: str) -> str:
    v = os.environ.get(name, "")
    if not v:
        raise SystemExit(f"{name} not set. Export it or set it in your wxo.env file.")
    return v

POOL_ID = _require("COGNITO_POOL_ID")
CLIENT_ID = _require("COGNITO_CLIENT_ID")
TOKEN_URL = _require("COGNITO_TOKEN_URL")
QUESTION = "What gesture for a gold customer whose payment was refused multiple times during a payments outage?"


def token():
    out = subprocess.run(
        ["aws", "cognito-idp", "describe-user-pool-client", "--user-pool-id", POOL_ID,
         "--client-id", CLIENT_ID, "--region", "us-east-1", "--output", "json"],
        capture_output=True, text=True, check=True).stdout
    client = json.loads(out)["UserPoolClient"]
    basic = base64.b64encode(f"{CLIENT_ID}:{client['ClientSecret']}".encode()).decode()
    data = urllib.parse.urlencode({"grant_type": "client_credentials",
                                   "scope": " ".join(client.get("AllowedOAuthScopes", []))}).encode()
    req = urllib.request.Request(TOKEN_URL, data=data, headers={
        "Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"})
    return json.load(urllib.request.urlopen(req, timeout=30))["access_token"]


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    arn, question = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else QUESTION)
    url = ("https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/"
           + urllib.parse.quote(arn, safe="") + "/invocations?qualifier=DEFAULT")
    body = {"jsonrpc": "2.0", "id": "1", "method": "message/send", "params": {"message": {
        "kind": "message", "role": "user", "messageId": str(uuid.uuid4()),
        "parts": [{"kind": "text", "text": question}]}}}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
        "Authorization": f"Bearer {token()}", "Content-Type": "application/json",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": str(uuid.uuid4()) + "-dswt2026-test"})
    t0 = time.time()
    res = json.load(urllib.request.urlopen(req, timeout=120))
    print(f"Question: {question}\nDuration: {time.time() - t0:.1f} s\n")
    result = res.get("result", res)
    texts = [p.get("text", "") for a in result.get("artifacts", []) for p in a.get("parts", [])]
    print("\n".join(texts) if texts else json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
