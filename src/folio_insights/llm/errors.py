"""Provider-neutral LLM errors.

Every provider failure is mapped to one of these types before it leaves the port, so callers
never see an SDK exception, and an error message never carries a credential. The SDK exception
is deliberately NOT chained (``raise ... from None``): provider error bodies can echo a masked
key ("Incorrect API key provided: sk-...abcd"), and a chained cause would print it in any
traceback a caller logs.
"""

from __future__ import annotations


class LLMError(Exception):
    """Base class for every error raised by the LLM port."""

    #: Short machine-readable kind ("auth", "rate_limit", ...), stable across providers.
    kind = "llm_error"
    #: Whether retrying the same request could succeed.
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        provider: str = "",
        model: str = "",
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.status_code = status_code


class LLMAuthError(LLMError):
    """The provider rejected the credential (401/403)."""

    kind = "auth"


class LLMRateLimitError(LLMError):
    """The provider throttled the request (429)."""

    kind = "rate_limit"
    retryable = True


class LLMBadRequestError(LLMError):
    """The provider rejected the request itself (400/404/422): unknown model, bad params."""

    kind = "bad_request"


class LLMProviderError(LLMError):
    """The provider failed server-side (5xx) or returned an unexpected status."""

    kind = "provider_error"
    retryable = True


class LLMConnectionError(LLMError):
    """The provider could not be reached or timed out."""

    kind = "connection"
    retryable = True


class LLMOutputError(LLMError):
    """The model's reply never validated against the output schema within the retry budget."""

    kind = "invalid_output"

    def __init__(self, message: str, *, usage: object | None = None, **kwargs: object) -> None:
        super().__init__(message, **kwargs)  # type: ignore[arg-type]
        #: Accumulated usage across the failed attempts (the tokens were still billed).
        self.usage = usage


class UnknownProviderError(LLMError):
    """The configured provider name is not one the port supports."""

    kind = "unknown_provider"


class RunHalted(LLMError):
    """Base for conditions that must stop a whole run, not just one call.

    Stage code catches ``Exception`` around individual LLM calls so one bad unit degrades
    gracefully. A halt is different: once raised, the run context remembers it, every later
    call fails fast without touching the network, and the orchestrator refuses to checkpoint
    the stage that saw it. The run then ends in a resumable state instead of silently
    producing degraded output.
    """

    kind = "halted"


class MissingCredentialsError(RunHalted):
    """No credential was supplied for a provider that needs one.

    The message names the provider (and, for CLI use, the environment variable the user can
    set), never a value. Server code never falls back to an ambient key.
    """

    kind = "needs_credentials"


class BudgetExhaustedError(RunHalted):
    """The run's spend cap would be exceeded by the next call, so the call was refused."""

    kind = "budget_exhausted"


class UnpricedModelError(RunHalted):
    """A spend cap is set but the price table has no row for the routed model.

    Refusing is the only way to guarantee the cap: an unpriced call has unbounded cost.
    """

    kind = "budget_exhausted"
