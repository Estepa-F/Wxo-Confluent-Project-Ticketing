"""Goodwill Policy Advisor -- AWS Bedrock AgentCore Runtime, A2A protocol.

Second agent of the Customer Relations team (demo story). It answers, in
plain French, questions about the goodwill policy (charter.md): what gesture
for which case, when a human approval is needed, what is never allowed.

Called by the watsonx Orchestrate Support Ops Copilot as an A2A collaborator:
Orchestrate hands the turn over to this agent, whose answer is shown directly
to the user. Hence prose, not JSON (unlike customer_goodwill_agent).

Same skeleton as customer_goodwill_agent (Strands + serve_a2a, OAuth
authorizer via Cognito, synchronous answer).
"""

import contextvars
from pathlib import Path

from a2a.types import Part, TextPart

from bedrock_agentcore.runtime import serve_a2a
from strands import Agent
from strands.models import BedrockModel
from strands.multiagent.a2a import StrandsA2AExecutor

import wxo_tracing  # own traces to watsonx Orchestrate, off unless configured

CHARTER = (Path(__file__).parent / "charter.md").read_text(encoding="utf-8")

SYSTEM_PROMPT = f"""You are the Commercial Policy Advisor of the Customer Relations
team of an online store. You answer questions from support managers about the
commercial gesture policy below, and nothing else.

Rules:
- Answer in English, in 3 to 6 lines maximum, in a clear and professional tone.
  A short table is fine if it genuinely helps.
- Support every answer with the policy and cite the section used,
  e.g. "(section 3)".
- When the question describes a case (tier, service, service status,
  recurrence), show the step-by-step calculation: severity, base gesture,
  adjustments, total, human approval required or not.
- If an information is missing to conclude, say which one and give the answer
  for each possible value, one line each.
- Never invent a rule, an amount, or an exception not in the policy. If the
  policy doesn't answer, say so.
- Section 6 (JSON format) concerns another agent: you always reply in text,
  never in JSON.
- If the question contains personal data, ignore it and never repeat it.
- If the question is out of scope, reply in one sentence that you only cover
  the commercial gesture policy.

<policy>
{CHARTER}
</policy>
"""

model = BedrockModel(
    model_id="us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    region_name="us-east-1",  # the "us." inference profile only exists in US regions
    temperature=0.0,
    max_tokens=600,
)

agent = Agent(
    name="goodwill_policy_advisor",
    description=(
        "Conseiller politique commerciale de l'équipe Relation client. "
        "Répond en français aux questions sur la politique de geste "
        "commercial : quel bon d'achat pour quel tier et quelle gravité, "
        "ajustements (récurrence, rappel prioritaire), plafond de 30 €, cas "
        "qui exigent une validation humaine, ce qui est interdit."
    ),
    model=model,
    system_prompt=SYSTEM_PROMPT,
    callback_handler=None,
)


_current_run = contextvars.ContextVar("current_run", default=None)


class PlainTextExecutor(StrandsA2AExecutor):
    """Same executor, but the final A2A artifact is one plain-text part, and
    each run is reported to watsonx Orchestrate when tracing is configured."""

    async def execute(self, context, event_queue):
        try:
            user_input = context.get_user_input() or ""
        except Exception:
            user_input = ""
        with wxo_tracing.agent_run(user_input) as run:
            token = _current_run.set(run)
            try:
                await super().execute(context, event_queue)
            finally:
                _current_run.reset(token)

    async def _handle_agent_result(self, result, updater, stream_state):
        run = _current_run.get()
        if run is not None and result is not None:
            run.output = str(result).strip()
        if result is not None and stream_state is None:
            await updater.add_artifact(
                [Part(root=TextPart(text=str(result).strip()))],
                name="agent_response",
            )
            await updater.complete()
            return
        await super()._handle_agent_result(result, updater, stream_state)


serve_a2a(PlainTextExecutor(agent))
