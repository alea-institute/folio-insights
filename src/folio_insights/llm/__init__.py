"""Provider-neutral LLM access for folio-insights (Phase 10 U1).

Every LLM call in the pipeline, discovery, the judge and polysemy goes through
:class:`~folio_insights.llm.port.LLMPort`, built on the pinned ``instructor`` + ``openai`` SDKs:

* :mod:`.port` -- the port, route resolution and the bridge-compatible :class:`TaskLLM`;
* :mod:`.providers` -- provider specs, client construction and SDK error mapping;
* :mod:`.credentials` -- bring-your-own-key handles that never print, pickle or persist;
* :mod:`.templates` -- versioned prompt templates and their identity hashes;
* :mod:`.context` -- the per-run context (credentials, route defaults, meter);
* :mod:`.usage` -- provider-reported usage records.

The folio-enrich LLM registry (reached through a ``sys.path`` bridge) is no longer used here.
"""

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # static names for linters and IDEs; runtime loads lazily below
    from folio_insights.llm.context import (
        LLMRunContext,
        current_context,
        set_process_default,
        use_context,
    )
    from folio_insights.llm.credentials import Credentials, SecretKey
    from folio_insights.llm.errors import (
        BudgetExhaustedError,
        LLMAuthError,
        LLMBadRequestError,
        LLMConnectionError,
        LLMError,
        LLMModelNotFoundError,
        LLMOutputError,
        LLMProviderError,
        LLMRateLimitError,
        MissingCredentialsError,
        RunHalted,
        UnknownProviderError,
        UnpricedModelError,
    )
    from folio_insights.llm.port import (
        LLMPort,
        PlannedCall,
        Route,
        TaskLLM,
        get_default_port,
        resolve_route,
        run_sync,
        set_default_port,
    )
    from folio_insights.llm.usage import Usage, UsageRecord

_EXPORTS: dict[str, str] = {
    "BudgetExhaustedError": "errors",
    "Credentials": "credentials",
    "LLMAuthError": "errors",
    "LLMBadRequestError": "errors",
    "LLMConnectionError": "errors",
    "LLMError": "errors",
    "LLMModelNotFoundError": "errors",
    "LLMOutputError": "errors",
    "LLMPort": "port",
    "LLMProviderError": "errors",
    "LLMRateLimitError": "errors",
    "LLMRunContext": "context",
    "MissingCredentialsError": "errors",
    "PlannedCall": "port",
    "Route": "port",
    "RunHalted": "errors",
    "SecretKey": "credentials",
    "TaskLLM": "port",
    "UnknownProviderError": "errors",
    "UnpricedModelError": "errors",
    "Usage": "usage",
    "UsageRecord": "usage",
    "current_context": "context",
    "get_default_port": "port",
    "resolve_route": "port",
    "run_sync": "port",
    "set_default_port": "port",
    "set_process_default": "context",
    "use_context": "context",
}



def __getattr__(name: str) -> Any:
    """Load exports lazily: ``credentials``/``context``/``errors``/``usage`` are stdlib-only, so
    the worker image (no pydantic) can import them without pulling in the port and templates."""
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module 'folio_insights.llm' has no attribute {name!r}")
    value = getattr(importlib.import_module(f"folio_insights.llm.{module}"), name)
    globals()[name] = value
    return value


__all__ = [
    "BudgetExhaustedError",
    "Credentials",
    "LLMAuthError",
    "LLMBadRequestError",
    "LLMConnectionError",
    "LLMError",
    "LLMModelNotFoundError",
    "LLMOutputError",
    "LLMPort",
    "LLMProviderError",
    "LLMRateLimitError",
    "LLMRunContext",
    "MissingCredentialsError",
    "PlannedCall",
    "Route",
    "RunHalted",
    "SecretKey",
    "TaskLLM",
    "UnknownProviderError",
    "UnpricedModelError",
    "Usage",
    "UsageRecord",
    "current_context",
    "get_default_port",
    "resolve_route",
    "run_sync",
    "set_default_port",
    "set_process_default",
    "use_context",
]
