#!/usr/bin/env bash
# Deploys the Commercial Policy Advisor on AgentCore Runtime (us-east-1),
# with the same Cognito pool as customer_goodwill_agent, then tests it.
#
# Usage (from this folder):
#   bash deploy.sh            # configure + deploy + test
#   bash deploy.sh test       # test only
set -euo pipefail
cd "$(dirname "$0")"

export AWS_PROFILE="${AWS_PROFILE:?AWS_PROFILE missing}" AGENTCORE_SUPPRESS_RECOMMENDATION=1
POOL_ID="${COGNITO_POOL_ID:?COGNITO_POOL_ID missing (e.g. us-east-1_XXXXXXXXX)}"
CLIENT_ID="${COGNITO_CLIENT_ID:?COGNITO_CLIENT_ID missing (26-char Cognito app client ID)}"
NAME=goodwill_policy_advisor

if [ "${1:-}" != "test" ]; then
  AUTH="{\"customJWTAuthorizer\":{\"discoveryUrl\":\"https://cognito-idp.us-east-1.amazonaws.com/${POOL_ID}/.well-known/openid-configuration\",\"allowedClients\":[\"${CLIENT_ID}\"]}}"
  agentcore configure -e agent.py -n "$NAME" --protocol A2A -r us-east-1 --deployment-type container --requirements-file requirements.txt --disable-memory --authorizer-config "$AUTH" --request-header-allowlist Authorization --non-interactive
  agentcore deploy
fi

ARN=$(grep -E "agent_arn:" .bedrock_agentcore.yaml | grep "$NAME" | head -1 | awk '{print $2}')
if [ -z "$ARN" ]; then
  echo "ARN not found in .bedrock_agentcore.yaml: run 'agentcore status' and re-run 'python3 test.py <ARN>'." >&2
  exit 1
fi
echo
echo "=== Test (real Cognito token, as Orchestrate would use) ==="
python3 test.py "$ARN"
echo
echo "=== Add to your orchestrate/wxo.env (or wxo-<you>.env) ==="
echo "POLICY_ADVISOR_ARN=$ARN"
