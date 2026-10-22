#!/usr/bin/env bash
# Redeploys the Commercial Policy Advisor with its own trace forwarding
# to watsonx Orchestrate (Analyze / Observability).
#
# Usage (from this folder, ADK venv active, AWS profile for the agent's account):
#   bash enable_tracing.sh ../../wxo.env         # enable
#   bash enable_tracing.sh ../../wxo.env --off   # disable (same code, empty variables)
#
# Reads WXO_URL, WXO_API_KEY, WXO_ENV_NAME and SUFFIX from the config file.
set -euo pipefail
cd "$(dirname "$0")"

CONFIG_FILE="${1:?Config file required, e.g. ../../wxo.env}"
while IFS= read -r line || [ -n "$line" ]; do
  line="${line%$'\r'}"
  case "$line" in ''|\#*) continue ;; esac
  key="${line%%=*}"; val="${line#*=}"
  key="$(echo "$key" | tr -d '[:space:]')"
  val="${val#\"}"; val="${val%\"}"; val="${val#\'}"; val="${val%\'}"
  [[ "$key" =~ ^[A-Z_][A-Z0-9_]*$ ]] || continue
  if [ -z "${!key+x}" ] && [ -n "$val" ]; then export "$key=$val"; fi
done < "$CONFIG_FILE"

export AWS_PROFILE="${AWS_PROFILE:-default}" AGENTCORE_SUPPRESS_RECOMMENDATION=1
ADVISOR="goodwill_policy_advisor${SUFFIX:-}"

if [ "${2:-}" = "--off" ]; then
  echo "=== Disabling trace forwarding to Orchestrate ==="
  agentcore deploy --auto-update-on-conflict --env WXO_OTEL_EXPORT_URL= --env WXO_API_KEY=
  exit 0
fi

: "${WXO_URL:?WXO_URL missing}"; : "${WXO_API_KEY:?WXO_API_KEY missing}"

echo "=== 1. Orchestrate credentials ==="
orchestrate env activate "${WXO_ENV_NAME:-wxo-dswt2026}" --api-key "$WXO_API_KEY" >/dev/null
AGENT_ID=$(orchestrate agents list -k external -v 2>/dev/null | ADVISOR="$ADVISOR" python3 -c '
import json, os, sys
def walk(o):
    if isinstance(o, dict):
        if o.get("name") == os.environ["ADVISOR"] and o.get("id"):
            yield o["id"]
        for v in o.values(): yield from walk(v)
    elif isinstance(o, list):
        for v in o: yield from walk(v)
try: print(next(walk(json.load(sys.stdin))))
except Exception: print("")
')
[ -n "$AGENT_ID" ] || { echo "ID for agent $ADVISOR not found: check 'orchestrate agents list -k external'." >&2; exit 1; }
TENANT_ID="${WXO_TENANT_ID:-$(python3 -c 'import json; print(json.load(open("../../../app/support_portal/static/copilot-config.json"))["orchestrationID"])')}"
EXPORT_URL="${WXO_URL%/}/v1/orchestrate/inject/traces"
echo "Orchestrate agent: $ADVISOR ($AGENT_ID)"
echo "Tenant           : $TENANT_ID"
echo "Ingestion URL    : $EXPORT_URL"

echo
echo "=== 2. AgentCore redeploy with tracing variables ==="
# The local AgentCore config must belong to the current AWS account: a copy from
# another folder or a colleague points to other roles and ECR repositories.
CALLER=$(aws sts get-caller-identity --query Account --output text)
if [ ! -f .bedrock_agentcore.yaml ] || ! grep -q "$CALLER" .bedrock_agentcore.yaml \
   || grep -E "[0-9]{12}" .bedrock_agentcore.yaml | grep -vq "$CALLER"; then
  echo "(AgentCore config missing or from another account: regenerated for account $CALLER)"
  rm -rf .bedrock_agentcore.yaml .bedrock_agentcore
  : "${COGNITO_POOL_ID:?COGNITO_POOL_ID missing}"; : "${COGNITO_CLIENT_ID:?COGNITO_CLIENT_ID missing}"
  AUTH="{\"customJWTAuthorizer\":{\"discoveryUrl\":\"https://cognito-idp.us-east-1.amazonaws.com/${COGNITO_POOL_ID}/.well-known/openid-configuration\",\"allowedClients\":[\"${COGNITO_CLIENT_ID}\"]}}"
  agentcore configure -e agent.py -n goodwill_policy_advisor --protocol A2A -r us-east-1 --deployment-type container \
    --requirements-file requirements.txt --disable-memory --authorizer-config "$AUTH" \
    --request-header-allowlist Authorization --non-interactive
fi
agentcore deploy --auto-update-on-conflict \
  --env "WXO_OTEL_EXPORT_URL=$EXPORT_URL" \
  --env "WXO_API_KEY=$WXO_API_KEY" \
  --env "WXO_TENANT_ID=$TENANT_ID" \
  --env "WXO_AGENT_ID=$AGENT_ID" \
  --env "WXO_ENVIRONMENT=live"

echo
echo "=== 3. Test (one question, then check Observability in 2–5 minutes) ==="
ARN=$(grep -E "agent_arn:" .bedrock_agentcore.yaml | grep goodwill_policy_advisor | head -1 | awk '{print $2}')
python3 test.py "$ARN"
echo
echo "If responses stop working: bash enable_tracing.sh $CONFIG_FILE --off"
