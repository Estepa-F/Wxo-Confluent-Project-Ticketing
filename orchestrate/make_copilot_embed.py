#!/usr/bin/env python3
"""Prepare the embedded Support Ops Copilot for the app.

1. Runs `orchestrate channels webchat embed` for the copilot and writes
   app/support_portal/static/copilot-config.json (read by copilot-embed.js).
2. With --disable-security: turns off embedded chat security on the
   Orchestrate instance (anonymous access, instance-wide).
   With --status: only shows the current security configuration.

Usage, from orchestrate/ with the ADK venv active and the environment active:
    python3 make_copilot_embed.py wxo.env                       # config only
    python3 make_copilot_embed.py wxo.env --disable-security    # config + security off
    python3 make_copilot_embed.py wxo.env --status              # show security config
"""
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "app" / "support_portal" / "static" / "copilot-config.json"
KEYS = ["orchestrationID", "hostURL", "deploymentPlatform", "crn", "agentId", "agentEnvironmentId"]


def read_env(path):
    env = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip().replace("\r", "")
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        if v:
            env[k.strip()] = v
    return env


def iam_token(api_key):
    data = urllib.parse.urlencode({
        "grant_type": "urn:ibm:params:oauth:grant-type:apikey", "apikey": api_key}).encode()
    req = urllib.request.Request("https://iam.cloud.ibm.com/identity/token", data=data,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    return json.load(urllib.request.urlopen(req, timeout=30))["access_token"]


def security_call(wxo_url, token, payload=None):
    url = wxo_url.rstrip("/") + "/v1/embed/secure/config"
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=body, method="POST" if body else "GET", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        txt = r.read().decode()
    try:
        cfg = json.loads(txt)
    except ValueError:
        return txt
    # never print keys in full
    for k in ("public_key", "client_public_key"):
        if isinstance(cfg, dict) and cfg.get(k):
            cfg[k] = "(present)"
    return cfg


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    env = read_env(sys.argv[1])
    flags = sys.argv[2:]
    wxo_url, api_key = env.get("WXO_URL"), env.get("WXO_API_KEY")
    agent = "support_ops_copilot" + env.get("SUFFIX", "")

    if "--status" in flags or "--disable-security" in flags:
        if not (wxo_url and api_key):
            sys.exit("WXO_URL and WXO_API_KEY are required in the config file.")
        token = iam_token(api_key)
        if "--disable-security" in flags:
            print("Embedded chat security: disabling (anonymous access, whole instance)")
            print(security_call(wxo_url, token, {"is_security_enabled": False}))
        print("Current configuration:", security_call(wxo_url, token))
        if "--status" in flags and "--disable-security" not in flags:
            return

    print(f"Embed script for {agent} (live)")
    # If the API key cannot read the IBM Cloud Resource Controller (403), the ADK
    # asks for the CRN on stdin: provide it from WXO_CRN.
    crn = env.get("WXO_CRN", "")
    res = subprocess.run(["orchestrate", "channels", "webchat", "embed", "--agent-name", agent, "--env", "live"],
                         capture_output=True, text=True, input=(crn + "\n") if crn else "")
    out = res.stdout + res.stderr
    cfg = {}
    for k in KEYS:
        m = re.search(rf'\b{k}\s*:\s*["\']([^"\']+)["\']', out)
        if m:
            cfg[k] = re.sub(r"\s+", "", m.group(1))  # the CLI wraps long lines
    if crn and not cfg.get("crn"):
        cfg["crn"] = crn
    if "Could not get CRN" in out and not crn:
        print(out)
        sys.exit("CRN could not be read automatically: add WXO_CRN=crn:v1:... to the config file "
                 "(IBM Cloud > Resource list > watsonx Orchestrate instance > CRN), then re-run.")
    missing = [k for k in ("orchestrationID", "hostURL", "agentId") if k not in cfg]
    if missing:
        print(out)
        sys.exit(f"Values not found in the output: {', '.join(missing)}")
    if env.get("EMBED_LOCALE"):
        cfg["locale"] = env["EMBED_LOCALE"]  # bubble language (en by default)
    OUT.write_text(json.dumps(cfg, indent=2) + "\n")
    print(f"Written: {OUT.relative_to(HERE.parent)}")
    print(json.dumps(cfg, indent=2))


if __name__ == "__main__":
    main()
