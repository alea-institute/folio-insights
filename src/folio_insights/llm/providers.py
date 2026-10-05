"""Provider specs and the instructor client factory (KTD1).

Every supported provider is reached through the OpenAI-compatible chat-completions surface it
publishes, with the already-pinned ``openai`` SDK as transport and ``instructor`` for validated
structured output:

==========  =====================================================  ===============
provider    endpoint                                               instructor mode
==========  =====================================================  ===============
openai      https://api.openai.com/v1                              TOOLS
anthropic   https://api.anthropic.com/v1/ (OpenAI SDK compat)      TOOLS
google      https://generativelanguage.googleapis.com/v1beta/openai/  TOOLS
ollama      http://localhost:11434/v1 (operator-configurable)      JSON
==========  =====================================================  ===============

One SDK means one retry policy to switch off (``max_retries=0``), one injectable HTTP transport
for the offline contract tests (KTD9) and no new dependency. The SDK is imported lazily so
modules that only need template identity never load it.

Base URLs come from operator configuration only (``FOLIO_INSIGHTS_LLM_<PROVIDER>_BASE_URL``),
never from a request: a per-request base URL would let any caller point the server at an
arbitrary host (SSRF) and ship a user's key there.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from folio_insights.llm.credentials import SecretKey, scrub
from folio_insights.llm.errors import (
    LLMAuthError,
    LLMBadRequestError,
    LLMConnectionError,
    LLMError,
    LLMModelNotFoundError,
    LLMProviderError,
    LLMRateLimitError,
    RunHalted,
    UnknownProviderError,
)

if TYPE_CHECKING:  # pragma: no cover
    import httpx


@dataclass(frozen=True)
class ProviderSpec:
    """Static description of one provider."""

    name: str
    display_name: str
    base_url: str
    mode: str  # instructor.Mode member name
    requires_key: bool
    default_model: str
    #: Name of the request parameter that caps output tokens on this endpoint.
    max_tokens_param: str = "max_tokens"

    def resolved_base_url(self, environ: dict[str, str] | None = None) -> str:
        env = os.environ if environ is None else environ
        override = (env.get(f"FOLIO_INSIGHTS_LLM_{self.name.upper()}_BASE_URL") or "").strip()
        return override or self.base_url


PROVIDERS: dict[str, ProviderSpec] = {
    "openai": ProviderSpec(
        name="openai",
        display_name="OpenAI",
        base_url="https://api.openai.com/v1",
        mode="TOOLS",
        requires_key=True,
        default_model="gpt-4.1-mini",
        max_tokens_param="max_completion_tokens",
    ),
    "anthropic": ProviderSpec(
        name="anthropic",
        display_name="Anthropic",
        base_url="https://api.anthropic.com/v1/",
        mode="TOOLS",
        requires_key=True,
        default_model="claude-haiku-4-5",
    ),
    "google": ProviderSpec(
        name="google",
        display_name="Google Gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        mode="TOOLS",
        requires_key=True,
        default_model="gemini-2.5-flash-lite",
    ),
    "ollama": ProviderSpec(
        name="ollama",
        display_name="Ollama (local)",
        base_url="http://localhost:11434/v1",
        mode="JSON",
        requires_key=False,
        default_model="llama3.2",
    ),
}

ALIASES: dict[str, str] = {
    "gemini": "google",
    "claude": "anthropic",
    "gpt": "openai",
}


def normalize_provider(name: str) -> str:
    key = (name or "").strip().lower()
    return ALIASES.get(key, key)


def get_provider_spec(name: str) -> ProviderSpec:
    key = normalize_provider(name)
    spec = PROVIDERS.get(key)
    if spec is None:
        raise UnknownProviderError(
            f"unsupported LLM provider {name!r}; supported: {', '.join(sorted(PROVIDERS))}",
            provider=key,
        )
    return spec


def supported_providers() -> list[str]:
    return sorted(PROVIDERS)


# Models that reject a non-default temperature (OpenAI reasoning families).
_NO_TEMPERATURE_PREFIXES = ("o1", "o3", "o4", "gpt-5")


def supports_temperature(spec: ProviderSpec, model: str) -> bool:
    return not (spec.name == "openai" and model.startswith(_NO_TEMPERATURE_PREFIXES))


HttpClientFactory = Callable[[ProviderSpec], "httpx.AsyncClient"]


def build_client(
    spec: ProviderSpec,
    *,
    api_key: SecretKey | None,
    timeout: float,
    http_client: httpx.AsyncClient | None = None,
) -> Any:
    """An instructor ``AsyncInstructor`` over the provider's OpenAI-compatible endpoint.

    SDK retries are off (``max_retries=0``): instructor's tenacity loop in the port is the only
    retry layer, so a failing request is attempted exactly ``max_attempts`` times.
    """
    import instructor
    import openai

    # Ollama ignores the key, but the SDK insists on a non-empty one.
    key_value = api_key.reveal() if api_key is not None else "not-required"
    client = openai.AsyncOpenAI(
        api_key=key_value,
        base_url=spec.resolved_base_url(),
        max_retries=0,
        timeout=timeout,
        http_client=http_client,
    )
    return instructor.from_openai(client, mode=getattr(instructor.Mode, spec.mode))


def map_provider_error(
    exc: BaseException,
    *,
    provider: str,
    model: str,
    secrets: list[SecretKey] | tuple[SecretKey, ...] = (),
) -> LLMError:
    """Translate an SDK exception into a port error with a scrubbed message."""
    import openai

    if isinstance(exc, LLMError):
        return exc
    halted = halt_cause(exc)
    if halted is not None:
        return halted
    status = getattr(exc, "status_code", None)
    raw = _provider_message(exc)
    message = scrub(raw, secrets)[:300]
    ctx = {"provider": provider, "model": model, "status_code": status}
    if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
        # Auth bodies are the ones that echo key fragments; say nothing more than the status.
        return LLMAuthError(f"{provider} rejected the API key (HTTP {status})", **ctx)
    if isinstance(exc, openai.RateLimitError):
        return LLMRateLimitError(f"{provider} rate limit (HTTP {status}): {message}", **ctx)
    if isinstance(exc, openai.NotFoundError):
        return LLMModelNotFoundError(
            f"{provider} has no model {model!r} (HTTP {status}): {message}", **ctx)
    if isinstance(
        exc,
        (openai.BadRequestError, openai.UnprocessableEntityError, openai.ConflictError),
    ):
        if _INVALID_KEY.search(raw):
            # Gemini answers a bad key with HTTP 400 "API key not valid", not 401.
            return LLMAuthError(f"{provider} rejected the API key (HTTP {status})", **ctx)
        return LLMBadRequestError(f"{provider} rejected the request (HTTP {status}): {message}", **ctx)
    if isinstance(exc, openai.APITimeoutError):
        return LLMConnectionError(f"{provider} request timed out", **ctx)
    if isinstance(exc, openai.APIConnectionError):
        return LLMConnectionError(f"could not reach {provider}", **ctx)
    if isinstance(exc, openai.APIStatusError):
        return LLMProviderError(f"{provider} server error (HTTP {status}): {message}", **ctx)
    return LLMProviderError(f"{provider} call failed: {type(exc).__name__}: {message}", **ctx)


def halt_cause(exc: BaseException) -> RunHalted | None:
    """A :class:`RunHalted` the SDK wrapped (raised by the port's send hook), if any."""
    seen = 0
    cur: BaseException | None = exc
    while cur is not None and seen < 5:
        if isinstance(cur, RunHalted):
            return cur
        cur = cur.__cause__ or cur.__context__
        seen += 1
    return None


_INVALID_KEY = re.compile(r"api[ _-]?key", re.IGNORECASE)


def _provider_message(exc: BaseException) -> str:
    """The provider's own error message, without the request/response objects."""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        inner = body.get("error", body)
        if isinstance(inner, dict) and isinstance(inner.get("message"), str):
            return inner["message"]
    if isinstance(body, list) and body and isinstance(body[0], dict):
        inner = body[0].get("error", body[0])
        if isinstance(inner, dict) and isinstance(inner.get("message"), str):
            return inner["message"]
    message = getattr(exc, "message", None)
    return message if isinstance(message, str) else str(exc)


def is_retryable(exc: BaseException) -> bool:
    """Instructor's retry predicate: re-ask on bad output, back off on transient faults."""
    import json

    import openai
    from pydantic import ValidationError

    from instructor.core.exceptions import (
        AsyncValidationError,
        ResponseParsingError,
    )
    from instructor.core.exceptions import ValidationError as InstructorValidationError

    if halt_cause(exc) is not None:
        return False  # a spend-cap refusal raised before sending: never retry it
    bad_output = (
        ValidationError,
        json.JSONDecodeError,
        InstructorValidationError,
        AsyncValidationError,
        ResponseParsingError,
    )
    if isinstance(exc, bad_output):
        return True
    if isinstance(exc, (openai.RateLimitError, openai.APIConnectionError, openai.InternalServerError)):
        return True
    return False
