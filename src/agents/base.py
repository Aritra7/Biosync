"""
Shared Anthropic client and helpers used by all agents.

Multi-model support: set MODEL_OVERRIDE env var or pass model= to llm_call()
to switch between claude-sonnet-4-6, claude-haiku-4-5-20251001, etc.
"""

import os
import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from dotenv import load_dotenv

load_dotenv()

# Default model — overridable via MODEL_OVERRIDE env var (for multi-model ablation)
DEFAULT_MODEL = "claude-sonnet-4-6"

SUPPORTED_MODELS = {
    "claude-sonnet-4-6": "claude-sonnet-4-6",
    "claude-haiku-4-5":  "claude-haiku-4-5-20251001",
    "claude-opus-4-6":   "claude-opus-4-6",
}

_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def get_active_model() -> str:
    override = os.environ.get("MODEL_OVERRIDE", "").strip()
    if override:
        return SUPPORTED_MODELS.get(override, override)
    return DEFAULT_MODEL


@retry(
    retry=retry_if_exception_type(anthropic.RateLimitError),
    wait=wait_exponential(multiplier=1, min=15, max=90),
    stop=stop_after_attempt(6),
)
def llm_call(system: str, user: str, max_tokens: int = 4096, model: str | None = None) -> str:
    """
    Single-turn LLM call. Retries with backoff on rate limit errors.

    model: override the active model for this specific call.
           Defaults to MODEL_OVERRIDE env var or claude-sonnet-4-6.
    """
    client = get_client()
    active_model = model or get_active_model()
    response = client.messages.create(
        model=active_model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return response.content[0].text
