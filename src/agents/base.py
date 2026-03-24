"""
Shared Anthropic client and helpers used by all agents.
"""

import os
import time
import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-sonnet-4-6"

_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


@retry(
    retry=retry_if_exception_type(anthropic.RateLimitError),
    wait=wait_exponential(multiplier=1, min=15, max=90),
    stop=stop_after_attempt(6),
)
def llm_call(system: str, user: str, max_tokens: int = 4096) -> str:
    """Single-turn LLM call. Retries with backoff on rate limit errors."""
    client = get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return response.content[0].text
