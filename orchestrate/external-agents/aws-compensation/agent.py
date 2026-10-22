"""Customer Goodwill agent — AWS Bedrock AgentCore Runtime, A2A protocol.

Owned (in the demo story) by the Customer Relations team. Called by the
watsonx Orchestrate escalation agent as a tool (not a collaborator — see
goodwill_tool.py for the reason): it receives the context of one escalated
ticket (no personal data) and answers with the goodwill gesture defined by
charter.md, as a single JSON object.

Same skeleton as the A2A test agent that worked end to end with Orchestrate
(Strands + serve_a2a, OAuth authorizer via Cognito, synchronous answer).
"""

import re
from pathlib import Path

from a2a.types import Part, TextPart

from bedrock_agentcore.runtime import serve_a2a
from strands import Agent
from strands.models import BedrockModel
from strands.multiagent.a2a import StrandsA2AExecutor  # not strands.a2a (removed)

CHARTER = (Path(__file__).parent / "charter.md").read_text(encoding="utf-8")

SYSTEM_PROMPT = f"""You are the Goodwill Gesture agent of the Customer Relations team.
You receive the context of ONE escalated support ticket, and you decide the
commercial gesture to offer the customer by strictly applying the policy below,
and nothing else.

Rules:
- Apply the policy to the letter. Never invent a tier, an amount, or an extra.
- The request may be written in English or French: handle it the same way.
- If the request contains personal data (names, emails, phone or order numbers,
  addresses), ignore them and never repeat them.
- If the request is not about a commercial gesture, respond with
  "gesture": "none", "requires_human_approval": true and a justification
  stating that the request is out of scope.
- Respond only with the JSON object defined in section 6 of the policy,
  as raw JSON: the first character of your response is {{ and the last is }}.
  No markdown code block (```json), no text before or after: a program reads
  your response directly. The justification is in English.

<policy>
{CHARTER}
</policy>
"""

model = BedrockModel(
    # Same model as the Confluent Flink triage agent; access already validated
    # on this AWS account in us-east-1.
    model_id="us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    # Pinned: the "us." inference profile only exists in US regions, and
    # Strands otherwise takes the region from the AWS profile (eu-west-1 here).
    region_name="us-east-1",
    temperature=0.0,
    max_tokens=800,
)

agent = Agent(
    name="customer_goodwill_agent",
    description=(
        "Customer Relations team agent. From the context of an escalated "
        "ticket (customer tier, service, service status, recurrence, problem "
        "summary, no personal data), it returns the goodwill gesture to offer "
        "as a JSON object: voucher amount, extras, whether human approval is "
        "required, and a justification in English citing the rules applied."
    ),
    model=model,
    system_prompt=SYSTEM_PROMPT,
    callback_handler=None,  # no console streaming inside the runtime
)

_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def to_raw_json(text: str) -> str:
    """Claude sometimes wraps its JSON in a ```json block despite the
    instructions. Orchestrate and the app parse this answer, so strip the
    fence and keep only the outermost {...} object."""
    match = _FENCE.match(text)
    if match:
        text = match.group(1)
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if 0 <= start < end else text.strip()


class RawJsonExecutor(StrandsA2AExecutor):
    """Same executor, but the final A2A artifact is guaranteed raw JSON."""

    async def _handle_agent_result(self, result, updater, stream_state):
        if result is not None and stream_state is None:
            await updater.add_artifact(
                [Part(root=TextPart(text=to_raw_json(str(result))))],
                name="agent_response",
            )
            await updater.complete()
            return
        await super()._handle_agent_result(result, updater, stream_state)


serve_a2a(RawJsonExecutor(agent))
