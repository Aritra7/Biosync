"""
Shared LLM client and helpers used by all agents.

Supports multiple providers:
  - Anthropic (Claude Haiku, Sonnet, Opus) — default
  - OpenAI (GPT-4o, GPT-4o-mini) — requires OPENAI_API_KEY

Multi-model support: set MODEL_OVERRIDE env var or pass model= to llm_call()
to switch between providers/models for ablation experiments.
"""

import os
import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Optional OpenAI support
# ---------------------------------------------------------------------------
try:
    import openai as _openai_module
    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False

# ---------------------------------------------------------------------------
# Model registries
# ---------------------------------------------------------------------------

# Default model — overridable via MODEL_OVERRIDE env var (for multi-model ablation)
DEFAULT_MODEL = "claude-sonnet-4-6"

ANTHROPIC_MODELS = {
    # Full model IDs
    "claude-sonnet-4-6":         "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001": "claude-haiku-4-5-20251001",
    "claude-haiku-4-5":          "claude-haiku-4-5-20251001",
    "claude-opus-4-6":           "claude-opus-4-6",
    # Short aliases used by multimodel runner
    "sonnet": "claude-sonnet-4-6",
    "haiku":  "claude-haiku-4-5-20251001",
    "opus":   "claude-opus-4-6",
}

OPENAI_MODELS = {
    "gpt-4o":      "gpt-4o",
    "gpt-4o-mini": "gpt-4o-mini",
    "gpt-4-turbo": "gpt-4-turbo",
}

# Combined registry for get_active_model()
SUPPORTED_MODELS = {**ANTHROPIC_MODELS, **OPENAI_MODELS}

# ---------------------------------------------------------------------------
# Anthropic client
# ---------------------------------------------------------------------------
_anthropic_client: anthropic.Anthropic | None = None


def _get_anthropic_client() -> anthropic.Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _anthropic_client


# Backwards-compat alias used by some modules that import get_client directly
def get_client() -> anthropic.Anthropic:
    return _get_anthropic_client()


# ---------------------------------------------------------------------------
# OpenAI client
# ---------------------------------------------------------------------------
_openai_client = None


def _get_openai_client():
    global _openai_client
    if not _OPENAI_AVAILABLE:
        raise ImportError(
            "openai package not installed. Run: pip install openai>=1.0.0"
        )
    if _openai_client is None:
        _openai_client = _openai_module.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _openai_client


# ---------------------------------------------------------------------------
# Model routing
# ---------------------------------------------------------------------------

def get_active_model() -> str:
    override = os.environ.get("MODEL_OVERRIDE", "").strip()
    if override:
        return SUPPORTED_MODELS.get(override, override)
    return DEFAULT_MODEL


def _is_openai_model(model_id: str) -> bool:
    return model_id in OPENAI_MODELS or model_id.startswith("gpt-") or model_id.startswith("o1")


# ---------------------------------------------------------------------------
# Per-provider call implementations
# ---------------------------------------------------------------------------

def _is_retryable_anthropic(exc: BaseException) -> bool:
    """Retry on 429 rate limit and 529 overloaded errors."""
    if isinstance(exc, anthropic.RateLimitError):
        return True
    if isinstance(exc, anthropic.APIStatusError) and exc.status_code == 529:
        return True
    return False


@retry(
    retry=retry_if_exception(_is_retryable_anthropic),
    wait=wait_exponential(multiplier=1, min=15, max=90),
    stop=stop_after_attempt(6),
)
def _anthropic_call(system: str, user: str, max_tokens: int, model_id: str) -> str:
    client = _get_anthropic_client()
    response = client.messages.create(
        model=model_id,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return response.content[0].text


def _openai_call(system: str, user: str, max_tokens: int, model_id: str) -> str:
    client = _get_openai_client()
    response = client.chat.completions.create(
        model=model_id,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
    )
    return response.choices[0].message.content


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def llm_call(system: str, user: str, max_tokens: int = 4096, model: str | None = None) -> str:
    """
    Single-turn LLM call. Routes to Anthropic or OpenAI based on model ID.

    model: override the active model for this specific call.
           Defaults to MODEL_OVERRIDE env var or claude-sonnet-4-6.

    Supported values for MODEL_OVERRIDE / model arg:
      Anthropic: sonnet, haiku, opus, claude-sonnet-4-6, claude-haiku-4-5, claude-opus-4-6
      OpenAI:    gpt-4o, gpt-4o-mini, gpt-4-turbo  (requires OPENAI_API_KEY)
    """
    active_model = model or get_active_model()
    resolved = SUPPORTED_MODELS.get(active_model, active_model)

    if _is_openai_model(resolved):
        return _openai_call(system, user, max_tokens, resolved)
    return _anthropic_call(system, user, max_tokens, resolved)
