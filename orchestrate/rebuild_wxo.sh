#!/usr/bin/env bash
# Builds the entire watsonx Orchestrate side of the DSWT 2026 demo on one
# instance: Cognito connection, ask_goodwill_agent tool, escalation agent,
# PII control, AWS agent in the directory, and — if an RTCE key is provided —
# the Support Ops Copilot.
#
# Usage (from the orchestrate/ folder):
#   cp wxo.env.example wxo.env   # then fill in wxo.env
#   bash rebuild_wxo.sh          # reads wxo.env
#   bash rebuild_wxo.sh my-other.env      # or another file
#
# The same settings can also be passed as environment variables:
#   export WXO_URL="https://api.<region>.watson-orchestrate.cloud.ibm.com/instances/<id>"
#   export WXO_API_KEY="<IBM Cloud API key for the instance>"
#   # AWS account hosting the "Goodwill" agent:
#   export COGNITO_POOL_ID="us-east-1_XXXXXXXXX"
#   export COGNITO_CLIENT_ID="xxxxxxxxxxxxxxxxxxxxxxxxxx"
#   export COGNITO_TOKEN_URL="https://<domain>.auth.us-east-1.amazoncognito.com/oauth2/token"
#   export AGENTCORE_ARN="arn:aws:bedrock-agentcore:us-east-1:<account>:runtime/customer_goodwill_agent-XXXX"
#   # Optional, for the Support Ops Copilot:
#   export RTCE_URL="https://mcp.us-east-1.aws.confluent.cloud/mcp/v1/context-engine/organizations/<org>/environments/<env>/kafka-clusters/<lkc>"
#   export RTCE_KEY="<Confluent Global API key>"
#   export RTCE_SECRET="<secret>"
#   # Optional, to run two demos on the same instance side by side:
#   export SUFFIX="_jd"      # appended to all technical names (agents, tool, connections, controls)
#   export LABEL="Jane"      # appended to display names
#   bash rebuild_wxo.sh
#
# COGNITO_* and AGENTCORE_ARN are required (setup_demo.sh steps 3-4 create them).
# Prerequisites: ADK activated (venv "orchestrate") and AWS CLI connected to the
# account hosting the Cognito pool (AWS_PROFILE).

set -euo pipefail
cd "$(dirname "$0")"

# Config file: 1st argument, otherwise wxo.env if it exists.
# Format: KEY=VALUE (see wxo.env.example). A variable already defined in the
# shell or on the command line takes precedence over the file.
CONFIG_FILE="${1:-wxo.env}"
if [ -f "$CONFIG_FILE" ]; then
  echo "Config: $CONFIG_FILE"
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    case "$line" in ''|\#*) continue ;; esac
    key="${line%%=*}"; val="${line#*=}"
    key="$(echo "$key" | tr -d '[:space:]')"
    val="${val#\"}"; val="${val%\"}"; val="${val#\'}"; val="${val%\'}"
    [[ "$key" =~ ^[A-Z_][A-Z0-9_]*$ ]] || continue
    if [ -z "${!key+x}" ] && [ -n "$val" ]; then export "$key=$val"; fi
  done < "$CONFIG_FILE"
elif [ -n "${1:-}" ]; then
  echo "Config file not found: $1" >&2; exit 1
fi

: "${WXO_URL:?WXO_URL missing}"
: "${WXO_API_KEY:?WXO_API_KEY missing}"

POOL_ID="${COGNITO_POOL_ID:?COGNITO_POOL_ID missing (setup_demo.sh step 3)}"
CLIENT_ID="${COGNITO_CLIENT_ID:?COGNITO_CLIENT_ID missing (setup_demo.sh step 3)}"
TOKEN_URL="${COGNITO_TOKEN_URL:?COGNITO_TOKEN_URL missing (setup_demo.sh step 3)}"
ARN="${AGENTCORE_ARN:?AGENTCORE_ARN missing (setup_demo.sh step 4)}"
AGENTCORE_HOST="https://bedrock-agentcore.us-east-1.amazonaws.com"
AGENTCORE_URL=$(python3 -c 'import sys, urllib.parse; print("https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/" + urllib.parse.quote(sys.argv[1], safe="") + "/invocations?qualifier=DEFAULT")' "$ARN")
ENV_NAME="${WXO_ENV_NAME:-wxo-dswt2026}"
SUFFIX="${SUFFIX:-}"
LABEL="${LABEL:-}"
CONN_A2A="${COGNITO_APP_ID:-bedrock_cognito_a2a${SUFFIX}}"
CONN_RTCE="confluent_rtce${SUFFIX}"
AGENT="escalation_agent${SUFFIX}"
COPILOT="support_ops_copilot${SUFFIX}"
TAG=""; [ -n "$LABEL" ] && TAG=" ($LABEL)"

# Working copies: repo files are not modified.
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/tools" "$WORK/external" "$WORK/agents" "$WORK/controls" "$WORK/copilot"
sed -e "s#^AGENTCORE_URL = .*#AGENTCORE_URL = \"$AGENTCORE_URL\"#" \
    -e "s#^APP_ID = .*#APP_ID = \"$CONN_A2A\"#" \
    -e "s#^def ask_goodwill_agent(#def ask_goodwill_agent${SUFFIX}(#" \
    tools/goodwill_tool.py > "$WORK/tools/goodwill_tool.py"
cp tools/requirements.txt "$WORK/tools/"
sed -e "s#ask_goodwill_agent#ask_goodwill_agent${SUFFIX}#g" \
    -e "s#^name: escalation_agent\$#name: $AGENT#" \
    -e "s#^display_name: \(.*\)\$#display_name: \1${TAG}#" \
    agents/escalation_agent.yaml > "$WORK/agents/escalation_agent.yaml"
sed -e "s#^  name: pii_escalation_input\$#  name: pii_escalation_input${SUFFIX}#" \
    -e "s#^    - escalation_agent\$#    - $AGENT#" \
    -e "s#^  display_name: \(.*\)\$#  display_name: \1${TAG}#" \
    controls/pii_control.yaml > "$WORK/controls/pii_control.yaml"
sed -e "s#^  name: escalation_guardrails\$#  name: escalation_guardrails${SUFFIX}#" \
    -e "s#^    - escalation_agent\$#    - $AGENT#" \
    -e "s#^  display_name: \(.*\)\$#  display_name: \1${TAG}#" \
    controls/escalation_guardrails.yaml > "$WORK/controls/escalation_guardrails.yaml"
sed -e "s#^api_url: .*#api_url: \"$AGENTCORE_URL\"#" \
    -e "s#^name: customer_goodwill_agent\$#name: customer_goodwill_agent${SUFFIX}#" \
    -e "s#^nickname: customer_goodwill_agent\$#nickname: customer_goodwill_agent${SUFFIX}#" \
    -e "s#^title: \(.*\)\$#title: \1${TAG}#" \
    -e "s#^app_id: .*#app_id: $CONN_A2A#" \
    external-agents/aws-compensation/customer_goodwill_agent.yaml > "$WORK/external/customer_goodwill_agent.yaml"
sed -e "s#confluent_rtce#$CONN_RTCE#g" copilot/confluent_rtce_toolkit.yaml > "$WORK/copilot/confluent_rtce_toolkit.yaml"
[ -n "${RTCE_URL:-}" ] && sed -i.bak "s#^url: .*#url: $RTCE_URL#" "$WORK/copilot/confluent_rtce_toolkit.yaml"
sed -e "s#confluent_rtce:#${CONN_RTCE}:#g" \
    -e "s#^name: support_ops_copilot\$#name: $COPILOT#" \
    -e "s#^display_name: .*#display_name: Support Ops Copilot${TAG}#" \
    copilot/support_ops_copilot.yaml > "$WORK/copilot/support_ops_copilot.yaml"

step() { printf '\n=== %s ===\n' "$1"; }

# "connections add" fails if the connection exists: add it only when missing,
# then (re)configure it in both cases, so the script can be re-run.
ensure_connection() {
  if orchestrate connections list 2>/dev/null | grep -qE "(^|[^A-Za-z0-9_])$1([^A-Za-z0-9_]|$)"; then
    echo "(connection $1 already present: reconfigured)"
  else
    orchestrate connections add -a "$1" || echo "(connection $1: add refused, reconfiguring anyway)"
  fi
}

# "controls import" always creates a new control: remove existing controls with
# this exact name first (a random 6-character suffix may have been added),
# without touching those of another SUFFIX. No effect on first run.
replace_control() {   # base name, yaml file
  local old_ctl
  for old_ctl in $(orchestrate controls list 2>/dev/null \
      | grep -oE "(^|[^A-Za-z0-9_])$1(_[A-Za-z0-9]{6})?([^A-Za-z0-9_]|$)" \
      | grep -oE "$1[A-Za-z0-9_]*" | sort -u); do
    echo "(replacing existing control $old_ctl)"
    orchestrate controls remove -n "$old_ctl" || true
  done
  orchestrate controls import -f "$2"
}

step "0. Parameters"
echo "Orchestrate instance: $WXO_URL"
echo "Cognito pool        : $POOL_ID (client $CLIENT_ID), connection $CONN_A2A"
echo "AWS agent           : $ARN"
echo "Technical names     : $AGENT, ask_goodwill_agent${SUFFIX}, $CONN_A2A, $COPILOT, $CONN_RTCE"

step "1. ADK environment"
# "env add" on an existing name prompts interactively: skip that.
if orchestrate env list 2>/dev/null | grep -qE "(^|[^A-Za-z0-9_-])${ENV_NAME}([^A-Za-z0-9_-]|$)"; then
  echo "(environment $ENV_NAME already present)"
else
  orchestrate env add -n "$ENV_NAME" -u "$WXO_URL"
fi
orchestrate env activate "$ENV_NAME" --api-key "$WXO_API_KEY"

step "2. Cognito OAuth2 connection ($CONN_A2A)"
CLIENT_SECRET=$(aws cognito-idp describe-user-pool-client --user-pool-id "$POOL_ID" --client-id "$CLIENT_ID" \
  --region us-east-1 --query UserPoolClient.ClientSecret --output text)
SCOPES=$(aws cognito-idp describe-user-pool-client --user-pool-id "$POOL_ID" --client-id "$CLIENT_ID" \
  --region us-east-1 --query 'join(`" "`, UserPoolClient.AllowedOAuthScopes || `[]`)' --output text)
ensure_connection "$CONN_A2A"
for env in draft live; do
  orchestrate connections configure -a "$CONN_A2A" --env "$env" --type team \
    --kind oauth_auth_client_credentials_flow --url "$AGENTCORE_HOST"
  if [ -n "$SCOPES" ] && [ "$SCOPES" != "None" ]; then
    orchestrate connections set-credentials -a "$CONN_A2A" --env "$env" \
      --client-id "$CLIENT_ID" --client-secret "$CLIENT_SECRET" --token-url "$TOKEN_URL" --scope "$SCOPES"
  else
    orchestrate connections set-credentials -a "$CONN_A2A" --env "$env" \
      --client-id "$CLIENT_ID" --client-secret "$CLIENT_SECRET" --token-url "$TOKEN_URL"
  fi
done

step "3. Tool ask_goodwill_agent${SUFFIX}"
orchestrate tools import -k python -f "$WORK/tools/goodwill_tool.py" -r "$WORK/tools/requirements.txt" --app-id "$CONN_A2A"

step "4. Escalation agent"
orchestrate agents import -f "$WORK/agents/escalation_agent.yaml"

step "5. Controls on the escalation agent: PII filter + content guardrails"
replace_control "pii_escalation_input${SUFFIX}" "$WORK/controls/pii_control.yaml"
replace_control "escalation_guardrails${SUFFIX}" "$WORK/controls/escalation_guardrails.yaml"

step "6. Deploy escalation agent"
orchestrate agents deploy -n "$AGENT"

step "7. AWS agent in the directory (optional, for act 3)"
orchestrate agents import -f "$WORK/external/customer_goodwill_agent.yaml" \
  || echo "(external agent import failed: retry via the interface, Agent directory → Add agent)"

if [ -n "${RTCE_KEY:-}" ] && [ -n "${RTCE_SECRET:-}" ]; then
  step "8. Support Ops Copilot (Real-Time Context Engine)"
  grep "^url" "$WORK/copilot/confluent_rtce_toolkit.yaml"
  ensure_connection "$CONN_RTCE"
  for env in draft live; do
    orchestrate connections configure -a "$CONN_RTCE" --env "$env" --type team --kind basic
    orchestrate connections set-credentials -a "$CONN_RTCE" --env "$env" -u "$RTCE_KEY" -p "$RTCE_SECRET"
  done
  if ! orchestrate toolkits import -f "$WORK/copilot/confluent_rtce_toolkit.yaml" -a "$CONN_RTCE"; then
    if orchestrate tools list 2>/dev/null | grep -q "${CONN_RTCE}:listTopics"; then
      echo "(toolkit $CONN_RTCE already present: kept)"
    else
      echo "ERROR: toolkit $CONN_RTCE not imported and not present on the instance." >&2
      echo "  A \"401 Unauthorized\" means RTCE_KEY/RTCE_SECRET are not a valid Global key for this" >&2
      echo "  organization, or the Real-Time Context Engine is not enabled on the RTCE_URL cluster." >&2
      echo "  Test (200 expected, 401 = wrong key):" >&2
      echo "  curl -s -o /dev/null -w '%{http_code}\\n' -u \"\$RTCE_KEY:\$RTCE_SECRET\" -X POST -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2025-03-26\",\"capabilities\":{},\"clientInfo\":{\"name\":\"t\",\"version\":\"1\"}}}' \"\$RTCE_URL\"" >&2
      exit 1
    fi
  fi
  orchestrate tools list | grep -i "$CONN_RTCE" || true
  orchestrate agents import -f "$WORK/copilot/support_ops_copilot.yaml" \
    && orchestrate agents deploy -n "$COPILOT" \
    || echo "(copilot not imported: check the tool names above and fix copilot/support_ops_copilot.yaml)"
else
  step "8. Support Ops Copilot: skipped (RTCE_KEY / RTCE_SECRET not set)"
fi

step "9. Escalation agent ID (for credentials.env)"
orchestrate agents list -v 2>/dev/null | AGENT="$AGENT" python3 -c '
import json, os, sys
def walk(o):
    if isinstance(o, dict):
        if o.get("name") == os.environ["AGENT"] and o.get("id"):
            yield o["id"]
        for v in o.values():
            yield from walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v)
try:
    ids = sorted(set(walk(json.load(sys.stdin))))
except Exception:
    ids = []
print("TF_VAR_wxo_agent_id=" + ids[0] if ids else "ID not found automatically: last column of \"orchestrate agents list\"")
'

echo
echo "Done. In credentials.env: TF_VAR_wxo_instance_url, TF_VAR_wxo_api_key, TF_VAR_wxo_agent_id."
