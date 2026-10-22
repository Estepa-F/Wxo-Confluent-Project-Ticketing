#!/usr/bin/env bash
# Adds the Goodwill Policy Advisor (AWS agent, A2A) to Orchestrate and declares
# it as a collaborator of the Support Ops Copilot. Does not touch the
# escalation agent, the controls or the app.
#
# Usage (from orchestrate/, ADK venv active):
#   bash add_policy_advisor.sh wxo.env
# The config file must contain POLICY_ADVISOR_ARN (setup_demo.sh step 5, or
# the output of external-agents/aws-policy-advisor/deploy.sh).
#
# Rollback: bash add_policy_advisor.sh wxo.env --rollback
#   (re-imports the copilot without the collaborator).
set -euo pipefail
cd "$(dirname "$0")"

CONFIG_FILE="${1:-wxo.env}"
[ -f "$CONFIG_FILE" ] || { echo "Config file not found: $CONFIG_FILE" >&2; exit 1; }
while IFS= read -r line || [ -n "$line" ]; do
  line="${line%$'\r'}"
  case "$line" in ''|\#*) continue ;; esac
  key="${line%%=*}"; val="${line#*=}"
  key="$(echo "$key" | tr -d '[:space:]')"
  val="${val#\"}"; val="${val%\"}"; val="${val#\'}"; val="${val%\'}"
  [[ "$key" =~ ^[A-Z_][A-Z0-9_]*$ ]] || continue
  if [ -z "${!key+x}" ] && [ -n "$val" ]; then export "$key=$val"; fi
done < "$CONFIG_FILE"

: "${WXO_API_KEY:?WXO_API_KEY missing}"
ROLLBACK=""; [ "${2:-}" = "--rollback" ] && ROLLBACK=1
[ -n "$ROLLBACK" ] || : "${POLICY_ADVISOR_ARN:?POLICY_ADVISOR_ARN missing in $CONFIG_FILE}"

ENV_NAME="${WXO_ENV_NAME:-wxo-dswt2026}"
SUFFIX="${SUFFIX:-}"
LABEL="${LABEL:-}"
TAG=""; [ -n "$LABEL" ] && TAG=" ($LABEL)"
CONN_A2A="${COGNITO_APP_ID:-bedrock_cognito_a2a${SUFFIX}}"
CONN_RTCE="confluent_rtce${SUFFIX}"
COPILOT="support_ops_copilot${SUFFIX}"
ADVISOR="goodwill_policy_advisor${SUFFIX}"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

step() { printf '\n=== %s ===\n' "$1"; }

step "1. ADK environment ($ENV_NAME)"
orchestrate env activate "$ENV_NAME" --api-key "$WXO_API_KEY"

if [ -z "$ROLLBACK" ]; then
  URL=$(python3 -c 'import sys, urllib.parse; print("https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/" + urllib.parse.quote(sys.argv[1], safe="") + "/invocations?qualifier=DEFAULT")' "$POLICY_ADVISOR_ARN")
  sed -e "s#^api_url: .*#api_url: \"$URL\"#" \
      -e "s#^name: goodwill_policy_advisor\$#name: $ADVISOR#" \
      -e "s#^nickname: goodwill_policy_advisor\$#nickname: $ADVISOR#" \
      -e "s#^title: \(.*\)\$#title: \1${TAG}#" \
      -e "s#^app_id: .*#app_id: $CONN_A2A#" \
      external-agents/aws-policy-advisor/goodwill_policy_advisor.yaml > "$WORK/advisor.yaml"
  step "2. External agent $ADVISOR (A2A, connection $CONN_A2A)"
  grep -E "^(name|title|api_url|app_id):" "$WORK/advisor.yaml"
  orchestrate agents import -f "$WORK/advisor.yaml"
fi

sed -e "s#confluent_rtce:#${CONN_RTCE}:#g" \
    -e "s#^name: support_ops_copilot\$#name: $COPILOT#" \
    -e "s#^display_name: .*#display_name: Support Ops Copilot${TAG}#" \
    copilot/support_ops_copilot.yaml > "$WORK/copilot.yaml"
if [ -z "$ROLLBACK" ]; then
  ADVISOR="$ADVISOR" python3 - "$WORK/copilot.yaml" <<'PY'
import os, sys
p, adv = sys.argv[1], os.environ["ADVISOR"]
s = open(p, encoding="utf-8").read()
rule = f"""  RÈGLE OBLIGATOIRE - politique de geste commercial. Toute question sur
  les règles de geste commercial (quel bon d'achat pour quel client ou
  quelle panne, récurrence, rappel prioritaire, plafond de 30 euros,
  validation humaine, remboursements) ne se trouve PAS dans les topics
  Confluent. Ne répondez jamais vous-même et n'utilisez pas les outils
  Confluent pour ces questions : transférez-les TOUJOURS au collaborateur
  {adv} (« Conseiller politique commerciale (AWS) »), agent de l'équipe
  Relation client hébergé sur AWS, en lui passant une question autonome
  qui reprend le tier, le service, l'état du service et la récurrence
  quand ils sont connus.

"""
rule_en = f"""  MANDATORY RULE - goodwill policy. Any question about goodwill rules
  (which voucher for which customer or outage, recurrence, priority
  callback, 30 euro cap, human approval, refunds) is NOT in the Confluent
  topics. Never answer it yourself and do not use the Confluent tools for
  it: ALWAYS transfer it to the collaborator {adv} ("Goodwill Policy
  Advisor (AWS)"), the Customer Relations team's agent hosted on AWS,
  with a self-contained question that includes the tier, the service, the
  service status and the recurrence when they are known.

"""
import re
m = re.search(r"^  (?:Vous ne pouvez rien modifier|You cannot modify|You can't modify|You can not modify)", s, re.M)
if m:
    english = not m.group(0).startswith("  Vous")
    s = s[:m.start()] + (rule_en if english else rule) + s[m.start():]
else:
    # No known anchor: put the rule at the top of the instructions block.
    m = re.search(r"^instructions:\s*[|>][-+]?\s*\n", s, re.M)
    assert m, "instructions block not found in the copilot YAML"
    english = not re.search(r"\b(vous|les|des|une)\b", s[m.end():m.end()+2000])
    s = s[:m.end()] + (rule_en if english else rule) + s[m.end():]
# rstrip: a file without a final newline would glue "collaborators:" to
# the last line and break the YAML ("mapping values are not allowed here").
s = s.rstrip("\n") + f"\ncollaborators:\n  - {adv}\n"
open(p, "w", encoding="utf-8").write(s)
PY
  step "3. Copilot $COPILOT with collaborator $ADVISOR"
else
  step "3. Copilot $COPILOT without collaborator (rollback)"
fi
orchestrate agents import -f "$WORK/copilot.yaml"
orchestrate agents deploy -n "$COPILOT"

echo
echo "Done. Test in the chat (Orchestrate or the dashboard bubble):"
echo "  \"What is our goodwill rule for a gold customer hit by a recurring payments outage?\""
