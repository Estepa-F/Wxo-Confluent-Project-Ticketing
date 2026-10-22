"""Minimal watsonx Orchestrate client: one-turn ("headless") agent calls.

Pattern: exchange an IBM Cloud API key for an IAM bearer token (cached until
shortly before it expires), then POST the whole request as a single user
message to {instance_url}/v1/orchestrate/{agent_id}/chat/completions with
stream=false, and read choices[0].message.content. No thread is reused:
every escalated ticket gets a fresh conversation.
"""

import logging
import time

import httpx

from support_portal.config import settings

logger = logging.getLogger(__name__)

_token: str | None = None
_token_expires_at: float = 0.0


def is_configured() -> bool:
    return bool(settings.wxo_instance_url and settings.wxo_api_key and settings.wxo_agent_id)


async def _get_token(client: httpx.AsyncClient) -> str:
    global _token, _token_expires_at
    if _token and time.time() < _token_expires_at - 60:
        return _token
    resp = await client.post(
        settings.wxo_iam_url,
        data={"grant_type": "urn:ibm:params:oauth:grant-type:apikey", "apikey": settings.wxo_api_key},
        headers={"Accept": "application/json"},
    )
    resp.raise_for_status()
    body = resp.json()
    _token = body["access_token"]
    _token_expires_at = time.time() + int(body.get("expires_in", 3600))
    return _token


def _content_text(content) -> str:
    """content is usually a string; tolerate a list of typed parts too."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict))
    return str(content or "")


async def ask_agent(message: str, agent_id: str | None = None) -> str:
    """Sends one message to the agent and returns its final answer text.
    Raises on HTTP errors or an empty answer -- callers decide what to show."""
    agent_id = agent_id or settings.wxo_agent_id
    url = f"{settings.wxo_instance_url.rstrip('/')}/v1/orchestrate/{agent_id}/chat/completions"
    async with httpx.AsyncClient(timeout=settings.wxo_timeout_seconds) as client:
        token = await _get_token(client)
        resp = await client.post(
            url,
            json={"messages": [{"role": "user", "content": message}], "stream": False},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        resp.raise_for_status()
        body = resp.json()
    choices = body.get("choices") or []
    text = _content_text((choices[0].get("message") or {}).get("content")) if choices else ""
    if not text.strip():
        raise ValueError(f"Empty answer from Orchestrate agent (keys: {sorted(body)[:8]})")
    return text
