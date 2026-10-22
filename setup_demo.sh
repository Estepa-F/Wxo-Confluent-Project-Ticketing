#!/usr/bin/env bash
# =============================================================================
# DSWT 2026: sets up the whole "Confluent + watsonx Orchestrate + AWS" demo
# on top of a Confluent/AWS deployment made with deploy.py, in one command.
#
#   Confluent (escalation-drafts topic) -> AWS (Cognito, 2 AgentCore agents)
#   -> Orchestrate (escalation agent, controls, copilot, external agents, traces)
#   -> app (copilot bubble, escalation agent wiring) -> checks
#
# Prerequisite: deploy.py stages base, app and intelligence (agent enabled)
# already applied from this folder (see docs/installation.md, section 3).
#
# Usage, from the project root:
#   cp orchestrate/wxo.env.example orchestrate/wxo.env   # then fill it in
#   bash setup_demo.sh                    # all steps
#   bash setup_demo.sh --from 5           # resume at step 5
#   bash setup_demo.sh --only 8           # a single step
#   bash setup_demo.sh --list             # list the steps
#
# Re-runnable: what already exists is kept, and the values created (Cognito
# pool, agent ARNs, agent ID) are written to orchestrate/wxo.env and
# credentials.env for the next runs.
# =============================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

CONFIG="${WXO_CONFIG:-$ROOT/orchestrate/wxo.env}"
CREDS="$ROOT/credentials.env"
FROM=1; ONLY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --from) FROM="$2"; shift 2 ;;
    --only) ONLY="$2"; shift 2 ;;
    --config) CONFIG="$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"; shift 2 ;;
    --list) sed -n 's/^step \([0-9]*\) "\(.*\)".*/  \1. \2/p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# ------------------------------------------------------------------ helpers
load_env() {   # KEY=VALUE, quotes and CRLF stripped; the shell wins
  local f="$1" line key val
  [ -f "$f" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    case "$line" in ''|\#*) continue ;; esac
    key="${line%%=*}"; val="${line#*=}"
    key="$(echo "$key" | tr -d '[:space:]')"
    val="${val#\"}"; val="${val%\"}"; val="${val#\'}"; val="${val%\'}"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    if [ -z "${!key:-}" ] && [ -n "$val" ]; then export "$key=$val"; fi
  done < "$f"
}
set_env() {    # writes or replaces KEY=VALUE in a file
  python3 - "$1" "$2" "$3" <<'PY'
import sys, re
path, key, val = sys.argv[1:4]
try:
    lines = open(path, encoding="utf-8").read().splitlines()
except FileNotFoundError:
    lines = []
pat = re.compile(rf"^\s*{re.escape(key)}\s*=")
for i, l in enumerate(lines):
    if pat.match(l):
        lines[i] = f"{key}={val}"
        break
else:
    lines.append(f"{key}={val}")
open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
PY
  export "$2=$3"
}
need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing tool: $1 ($2)" >&2; MISSING=1; }; }
pause() { printf '\n%s\nEnter to continue, Ctrl+C to stop... ' "$1"; read -r _; }
run_step() { [ -n "$ONLY" ] && [ "$1" != "$ONLY" ] && return 1; [ "$1" -lt "$FROM" ] && return 1; return 0; }
STEP_N=0
step() { STEP_N="$1"; printf '\n\033[1m=== %s. %s ===\033[0m\n' "$1" "$2"; }

require_state() {   # refuses to run Terraform without the state of the deployed environment
  local f="terraform/$1/terraform.tfstate"
  if [ ! -s "$f" ] || ! python3 -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get("resources") else 1)' "$f"; then
    echo "STOP: $f missing or empty. Run the deploy.py stages first (docs/installation.md)," >&2
    echo "or run this script in the folder where the demo was deployed. Without the" >&2
    echo "state, Terraform would recreate the whole environment." >&2
    exit 1
  fi
}

agentcore_deploy() {  # folder, name, variable that receives the ARN
  local dir="$1" name="$2" var="$3" auth arn
  ( cd "$dir"
    auth="{\"customJWTAuthorizer\":{\"discoveryUrl\":\"https://cognito-idp.us-east-1.amazonaws.com/${COGNITO_POOL_ID}/.well-known/openid-configuration\",\"allowedClients\":[\"${COGNITO_CLIENT_ID}\"]}}"
    agentcore configure -e agent.py -n "$name" --protocol A2A -r us-east-1 --deployment-type container \
      --requirements-file requirements.txt --disable-memory --authorizer-config "$auth" \
      --request-header-allowlist Authorization --non-interactive
    agentcore deploy --auto-update-on-conflict )
  arn=$(grep -E "agent_arn:" "$dir/.bedrock_agentcore.yaml" | grep "$name" | head -1 | awk '{print $2}')
  [ -n "$arn" ] || { echo "ARN of $name not found: run \"agentcore status\" in $dir" >&2; exit 1; }
  set_env "$CONFIG" "$var" "$arn"
  echo "$var=$arn"
}

# ------------------------------------------------------------------ config
[ -f "$CONFIG" ] || { echo "Config not found: $CONFIG (copy orchestrate/wxo.env.example)" >&2; exit 1; }
load_env "$CONFIG"
: "${WXO_URL:?WXO_URL missing in $CONFIG}"
: "${WXO_API_KEY:?WXO_API_KEY missing in $CONFIG}"
export AWS_PROFILE="${AWS_PROFILE:-default}" AGENTCORE_SUPPRESS_RECOMMENDATION=1 AWS_PAGER=""
SUFFIX="${SUFFIX:-}"
echo "Config: $CONFIG"
echo "Orchestrate instance: $WXO_URL   (suffix: '${SUFFIX}')"

# ================================================================ steps
if run_step 1; then
step 1 "Prerequisites"
MISSING=0
need python3 "Python 3.12+"; need aws "AWS CLI v2"; need terraform "Terraform"; need docker "Docker Desktop"
need agentcore "uv tool install bedrock-agentcore-starter-toolkit"
need orchestrate "venv with ibm-watsonx-orchestrate==2.17.0, activated"
[ "$MISSING" = 0 ] || exit 1
[ -f "$CREDS" ] || { echo "credentials.env missing at the root (see credentials.env.example)" >&2; exit 1; }
echo "AWS account: $(aws sts get-caller-identity --query Account --output text)  (profile $AWS_PROFILE)"
cat <<'TXT'
Manual steps to do BEFORE (consoles, once):
  - deploy.py: stages base, app and intelligence applied, triage agent enabled (docs/installation.md).
  - Bedrock (us-east-1): access to Claude Sonnet 4.5 granted (Model catalog > Submit use case).
  - Confluent: Real-Time Context Engine enabled on tickets.agent-actions,
    tickets.escalation-drafts and tickets.metrics; RTCE_URL / RTCE_KEY /
    RTCE_SECRET in wxo.env (terraform outputs, see wxo.env.example).
  - Orchestrate: instance API key (WXO_API_KEY) and instance URL (WXO_URL).
TXT
pause "Check that all of this is done."
fi

if run_step 2; then
step 2 "Confluent: topic tickets.escalation-drafts (deploy.py --stage base)"
require_state base
echo "The plan must show no change, or ONLY the creation of tickets.escalation-drafts (0 to destroy); otherwise answer \"no\"."
python3 deploy.py --stage base
fi

if run_step 3; then
step 3 "AWS: Cognito pool for Orchestrate -> agents authentication"
if [ -n "${COGNITO_POOL_ID:-}" ] && [ -n "${COGNITO_CLIENT_ID:-}" ] && [ -n "${COGNITO_TOKEN_URL:-}" ]; then
  echo "(pool already set: $COGNITO_POOL_ID)"
else
  POOL=$(aws cognito-idp create-user-pool --pool-name wxo-a2a --region us-east-1 --query UserPool.Id --output text)
  DOMAIN="wxo-a2a-$(date +%s)"
  aws cognito-idp create-user-pool-domain --user-pool-id "$POOL" --domain "$DOMAIN" --region us-east-1 >/dev/null
  aws cognito-idp create-resource-server --user-pool-id "$POOL" --identifier a2a --name a2a \
    --scopes ScopeName=invoke,ScopeDescription=invoke --region us-east-1 >/dev/null
  CLIENT=$(aws cognito-idp create-user-pool-client --user-pool-id "$POOL" --client-name wxo-client --generate-secret \
    --allowed-o-auth-flows client_credentials --allowed-o-auth-scopes a2a/invoke \
    --allowed-o-auth-flows-user-pool-client --region us-east-1 --query UserPoolClient.ClientId --output text)
  set_env "$CONFIG" COGNITO_POOL_ID "$POOL"
  set_env "$CONFIG" COGNITO_CLIENT_ID "$CLIENT"
  set_env "$CONFIG" COGNITO_TOKEN_URL "https://$DOMAIN.auth.us-east-1.amazoncognito.com/oauth2/token"
  echo "Pool $POOL, client $CLIENT (saved in $CONFIG)"
fi
fi

if run_step 4; then
step 4 "AWS: Goodwill Gesture agent on AgentCore"
if [ -n "${AGENTCORE_ARN:-}" ]; then echo "(already deployed: $AGENTCORE_ARN)"
else agentcore_deploy orchestrate/external-agents/aws-compensation customer_goodwill_agent AGENTCORE_ARN; fi
python3 orchestrate/external-agents/aws-policy-advisor/test.py "$AGENTCORE_ARN" \
  $'tier: gold\nservice: payments\nservice_status: outage\nrecurring_issue_same_service: true\nissue_summary: payment refused several times during the outage'
echo "Expected: a JSON object with \"voucher_eur\": 30"
fi

if run_step 5; then
step 5 "AWS: Goodwill Policy Advisor agent on AgentCore"
if [ -n "${POLICY_ADVISOR_ARN:-}" ]; then echo "(already deployed: $POLICY_ADVISOR_ARN)"
else agentcore_deploy orchestrate/external-agents/aws-policy-advisor goodwill_policy_advisor POLICY_ADVISOR_ARN; fi
python3 orchestrate/external-agents/aws-policy-advisor/test.py "$POLICY_ADVISOR_ARN" \
  "What gesture for a gold customer hit by a recurring payments outage?"
echo "Expected: 30 EUR voucher, free shipping, priority callback, citing the policy sections"
fi

if run_step 6; then
step 6 "Orchestrate: connection, tool, escalation agent, controls, external agent, copilot"
( cd orchestrate && bash rebuild_wxo.sh "$CONFIG" )
fi

if run_step 7; then
step 7 "Orchestrate: AWS advisor as a collaborator of the copilot"
if [ -z "${RTCE_KEY:-}" ]; then echo "(RTCE_KEY empty: no copilot, step skipped)"
else ( cd orchestrate && bash add_policy_advisor.sh "$CONFIG" ); fi
fi

if run_step 8; then
step 8 "App: copilot bubble configuration (+ embedded chat security)"
if [ -z "${RTCE_KEY:-}" ]; then echo "(no copilot: step skipped)"
else
  SEC=""; [ "${EMBED_DISABLE_SECURITY:-false}" = "true" ] && SEC="--disable-security"
  ( cd orchestrate && python3 make_copilot_embed.py "$CONFIG" $SEC )
fi
fi

if run_step 9; then
step 9 "AWS: advisor traces to Orchestrate (control plane)"
if [ "${ADVISOR_TRACING:-true}" != "true" ]; then echo "(ADVISOR_TRACING=false: skipped)"
elif [ ! -f app/support_portal/static/copilot-config.json ]; then echo "(no copilot-config.json: run step 8 first)"
else ( cd orchestrate/external-agents/aws-policy-advisor && bash enable_tracing.sh "$CONFIG" ); fi
fi

if run_step 10; then
step 10 "App: wiring to the escalation agent (credentials.env)"
( cd orchestrate && orchestrate env activate "${WXO_ENV_NAME:-wxo-dswt2026}" --api-key "$WXO_API_KEY" >/dev/null )
AGENT_ID=$(cd orchestrate && orchestrate agents list -v 2>/dev/null | AGENT="escalation_agent${SUFFIX}" python3 -c '
import json, os, sys
def walk(o):
    if isinstance(o, dict):
        if o.get("name") == os.environ["AGENT"] and o.get("id"): yield o["id"]
        for v in o.values(): yield from walk(v)
    elif isinstance(o, list):
        for v in o: yield from walk(v)
try: print(next(walk(json.load(sys.stdin))))
except Exception: print("")')
[ -n "$AGENT_ID" ] || { echo "ID of escalation_agent${SUFFIX} not found (orchestrate agents list)" >&2; exit 1; }
set_env "$CREDS" TF_VAR_wxo_instance_url "$WXO_URL"
set_env "$CREDS" TF_VAR_wxo_api_key "$WXO_API_KEY"
set_env "$CREDS" TF_VAR_wxo_agent_id "$AGENT_ID"
echo "credentials.env: TF_VAR_wxo_instance_url, TF_VAR_wxo_api_key, TF_VAR_wxo_agent_id=$AGENT_ID"
fi

if run_step 11; then
step 11 "App: redeploy (deploy.py --stage app, ~10 min)"
require_state base; require_state app-hosting
echo "Each plan must show 0 to add and 0 to destroy (only \"update in-place\"); otherwise answer \"no\"."
python3 deploy.py --stage app
fi

if run_step 12; then
step 12 "Checks"
cat <<TXT
1. Confluent > Flink > Statements: the "...-run-triage-agent-..." statement must be Running.
   If it is Failed (MCP 421): DROP TABLE \`tickets.agent-actions\`; then, in terraform/confluent-intelligence:
   set -a; source ../../credentials.env; set +a; terraform apply -replace='confluent_flink_statement.run_triage_agent[0]'
2. Portal (Gold account): login ticket, urgency High, "Locked out again - page reloads after I enter my password",
   annoyed and recurring text -> Escalated within 1-2 min, proposal in /support-admin, message in tickets.escalation-drafts.
3. /dashboard bubble: "Which topics can you read?", then
   "What is our goodwill rule for a gold customer hit by a recurring payments outage?"
4. Orchestrate > Observability: goodwill_policy_advisor${SUFFIX} has its own conversations.
TXT
fi
echo; echo "Done."
