"""The LLM port: one tested, provider-neutral path for every LLM call (R3, KTD1, KTD2).

``LLMPort.structured(task, schema, messages, *, credentials, template)`` returns
``(validated_model, usage)``; ``LLMPort.complete(...)`` returns ``(text, usage)``. Both:

* route the task to a provider/model (per-task ``LLM_{TASK}_PROVIDER/MODEL`` env overrides win
  over run-wide flags, which win over settings);
* require the caller's credential for providers that need one, never an ambient server key;
* consult the run's meter before the call (spend cap) and record provider-reported usage after;
* run exactly one retry layer: instructor's tenacity loop, with SDK retries off. Malformed
  output is re-asked; rate limits, 5xx and connection faults back off; auth and bad-request
  errors fail at once;
* map every SDK failure to a :mod:`folio_insights.llm.errors` type whose message is scrubbed of
  credentials.

:class:`TaskLLM` is the call-site facade ``LLMBridge.get_llm_for_task`` returns. It keeps the
bridge-era duck type (``await llm.structured(prompt, schema=..., temperature=0) -> dict`` and
``await llm.complete(prompt) -> str``) so the stage code and its test fakes keep their shape,
while the call now carries a registered template's identity and goes through the port.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import os
import weakref
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel

from folio_insights.llm.context import LLMRunContext, current_context
from folio_insights.llm.credentials import Credentials, SecretKey
from folio_insights.llm.errors import (
    LLMError,
    LLMOutputError,
    RunHalted,
)
from folio_insights.llm.providers import (
    HttpClientFactory,
    ProviderSpec,
    build_client,
    get_provider_spec,
    is_retryable,
    map_provider_error,
    normalize_provider,
    supports_temperature,
)
from folio_insights.llm.templates import PromptTemplate, template_for_task
from folio_insights.llm.usage import Usage, UsageRecord

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class Route:
    """The provider and model one task resolves to."""

    provider: str
    model: str


@dataclass(frozen=True)
class PlannedCall:
    """What the meter sees before a call: enough to bound its cost, nothing secret."""

    task: str
    route: Route
    template_id: str
    template_hash: str
    messages: tuple[tuple[str, str], ...]
    output_schema_json: str
    max_tokens: int
    max_attempts: int

    @property
    def prompt_chars(self) -> int:
        return sum(len(content) for _role, content in self.messages) + len(self.output_schema_json)

    @property
    def prompt_bytes(self) -> int:
        return sum(len(c.encode("utf-8")) for _r, c in self.messages) + len(
            self.output_schema_json.encode("utf-8")
        )


def _env_value(environ: dict[str, str] | os._Environ[str], name: str) -> str | None:
    value = (environ.get(name) or "").strip()
    return value or None


def resolve_route(
    task: str,
    *,
    context: LLMRunContext | None = None,
    settings: Any = None,
    environ: dict[str, str] | None = None,
) -> Route:
    """Route ``task``: per-task env override > run-wide (CLI/API) > settings.

    A model only applies to the provider it was configured for: a level that names a model but
    no provider inherits the provider of the level below it, and when the winning provider has
    no model configured at any level its spec default is used. So ``LLM_DISTILLER_PROVIDER=
    anthropic`` alone never sends a Gemini model name to Anthropic.
    """
    if settings is None:
        from folio_insights.config import get_settings

        settings = get_settings()
    env = os.environ if environ is None else environ
    ctx = context if context is not None else current_context()
    upper = task.upper()
    levels: list[tuple[str | None, str | None]] = [
        (_env_value(env, f"LLM_{upper}_PROVIDER"), _env_value(env, f"LLM_{upper}_MODEL")),
        (ctx.provider or None, ctx.model or None),
        (getattr(settings, "llm_provider", None) or None, getattr(settings, "llm_model", None) or None),
    ]
    implied: list[str | None] = [None] * len(levels)
    below: str | None = None
    for i in range(len(levels) - 1, -1, -1):
        provider = levels[i][0]
        implied[i] = normalize_provider(provider) if provider else below
        below = implied[i]
    provider = implied[0]
    if provider is None:
        raise LLMError(f"no LLM provider configured for task {task!r}")
    spec = get_provider_spec(provider)
    model = next(
        (m for (_p, m), ip in zip(levels, implied) if m and ip == spec.name),
        spec.default_model,
    )
    return Route(provider=spec.name, model=model)


class LLMPort:
    """Provider-neutral structured and text completion with one retry layer."""

    def __init__(
        self,
        *,
        settings: Any = None,
        http_client_factory: HttpClientFactory | None = None,
        max_attempts: int | None = None,
        retry_wait_seconds: float | None = None,
        timeout_seconds: float | None = None,
        max_tokens: int | None = None,
    ) -> None:
        self._settings = settings
        self._http_client_factory = http_client_factory
        self.max_attempts = max(1, int(max_attempts or os.environ.get("FOLIO_INSIGHTS_LLM_MAX_ATTEMPTS", 3)))
        self.retry_wait_seconds = float(
            retry_wait_seconds
            if retry_wait_seconds is not None
            else os.environ.get("FOLIO_INSIGHTS_LLM_RETRY_WAIT", 1.0)
        )
        self.timeout_seconds = float(
            timeout_seconds or os.environ.get("FOLIO_INSIGHTS_LLM_TIMEOUT", 120.0)
        )
        self.max_tokens = int(max_tokens or os.environ.get("FOLIO_INSIGHTS_LLM_MAX_TOKENS", 4096))
        # loop -> {(provider, base_url, id(key)): (key, client)}. Clients bind to the loop that
        # first used them, so each loop gets its own.
        self._clients: weakref.WeakKeyDictionary[Any, dict[tuple[Any, ...], tuple[Any, Any]]] = (
            weakref.WeakKeyDictionary()
        )

    # ---- routing ---------------------------------------------------------------------------

    def _get_settings(self) -> Any:
        if self._settings is None:
            from folio_insights.config import get_settings

            return get_settings()
        return self._settings

    def resolve_route(self, task: str, *, context: LLMRunContext | None = None) -> Route:
        return resolve_route(task, context=context, settings=self._get_settings())

    # ---- public calls ----------------------------------------------------------------------

    async def structured(
        self,
        task: str,
        schema: type[T],
        messages: list[dict[str, str]],
        *,
        credentials: Credentials | None = None,
        template: PromptTemplate | None = None,
        route: Route | None = None,
        temperature: float | None = 0.0,
        max_tokens: int | None = None,
        context: LLMRunContext | None = None,
    ) -> tuple[T, Usage]:
        """Validated structured output: ``(schema instance, usage)``."""
        result, usage = await self._call(
            task, messages, schema=schema, credentials=credentials, template=template,
            route=route, temperature=temperature, max_tokens=max_tokens, context=context,
        )
        return result, usage

    async def complete(
        self,
        task: str,
        messages: list[dict[str, str]],
        *,
        credentials: Credentials | None = None,
        template: PromptTemplate | None = None,
        route: Route | None = None,
        temperature: float | None = 0.0,
        max_tokens: int | None = None,
        context: LLMRunContext | None = None,
    ) -> tuple[str, Usage]:
        """Free-text completion: ``(text, usage)``."""
        completion, usage = await self._call(
            task, messages, schema=None, credentials=credentials, template=template,
            route=route, temperature=temperature, max_tokens=max_tokens, context=context,
        )
        choices = getattr(completion, "choices", None) or []
        text = (choices[0].message.content or "") if choices else ""
        return text, usage

    # ---- internals -------------------------------------------------------------------------

    def _client_for(self, spec: ProviderSpec, key: SecretKey | None) -> Any:
        loop = asyncio.get_running_loop()
        per_loop = self._clients.setdefault(loop, {})
        cache_key = (spec.name, spec.resolved_base_url(), id(key) if key is not None else None)
        cached = per_loop.get(cache_key)
        if cached is not None and cached[0] is key:
            return cached[1]
        http_client = self._http_client_factory(spec) if self._http_client_factory else None
        client = build_client(
            spec, api_key=key, timeout=self.timeout_seconds, http_client=http_client
        )
        per_loop[cache_key] = (key, client)
        return client

    def _retrying(self) -> Any:
        from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt

        base = self.retry_wait_seconds

        def _wait(retry_state: Any) -> float:
            outcome = retry_state.outcome
            exc = outcome.exception() if outcome is not None else None
            # Re-asks after malformed output need no back-off; transient faults do.
            from pydantic import ValidationError

            if exc is None or isinstance(exc, (ValidationError, ValueError)):
                return 0.0
            return min(base * (2 ** (retry_state.attempt_number - 1)), 30.0)

        return AsyncRetrying(
            stop=stop_after_attempt(self.max_attempts),
            retry=retry_if_exception(is_retryable),
            wait=_wait,
        )

    async def _call(
        self,
        task: str,
        messages: list[dict[str, str]],
        *,
        schema: type[BaseModel] | None,
        credentials: Credentials | None,
        template: PromptTemplate | None,
        route: Route | None,
        temperature: float | None,
        max_tokens: int | None,
        context: LLMRunContext | None,
    ) -> tuple[Any, Usage]:
        ctx = context if context is not None else current_context()
        ctx.raise_if_halted()
        template = template or template_for_task(task)
        route = route or self.resolve_route(task, context=ctx)
        spec = get_provider_spec(route.provider)
        creds = credentials if credentials is not None else ctx.credentials
        try:
            key = creds.require(spec.name, requires_key=spec.requires_key)
        except RunHalted as exc:
            ctx.halt(exc)
            raise
        if key is None:
            key = creds.get(spec.name)  # optional key (e.g. an authenticated Ollama proxy)

        cap = int(max_tokens or self.max_tokens)
        planned = PlannedCall(
            task=task,
            route=route,
            template_id=template.id,
            template_hash=template.hash,
            messages=tuple((m.get("role", ""), m.get("content", "")) for m in messages),
            output_schema_json="" if schema is None else json.dumps(schema.model_json_schema()),
            max_tokens=cap,
            max_attempts=self.max_attempts,
        )
        if ctx.meter is not None:
            try:
                ctx.meter.before_call(planned)
            except RunHalted as exc:
                ctx.halt(exc)
                raise

        try:
            client = self._client_for(spec, key)
        except Exception:
            # Never reached the provider: drop the meter's reservation for this call.
            release = getattr(ctx.meter, "release", None)
            if release is not None:
                release(planned)
            raise
        retrying = self._retrying()
        kwargs: dict[str, Any] = {
            "model": route.model,
            "messages": messages,
            "response_model": schema,
            "max_retries": retrying,
            spec.max_tokens_param: cap,
        }
        if temperature is not None and supports_temperature(spec, route.model):
            kwargs["temperature"] = temperature

        secrets = creds.secrets()
        try:
            result, completion = await client.chat.completions.create_with_completion(**kwargs)
        except Exception as exc:  # noqa: BLE001 - every failure is mapped below
            mapped, usage = self._map_failure(exc, spec, route, retrying, secrets)
            self._record(ctx, task, template, usage, planned, status="error",
                         error_kind=mapped.kind)
            raise mapped from None

        if schema is None:
            completion = result  # free text: instructor hands back the raw ChatCompletion
        attempts = int(retrying.statistics.get("attempt_number", 1) or 1)
        usage = Usage.from_openai_usage(
            spec.name, route.model, getattr(completion, "usage", None), attempts=attempts
        )
        self._record(ctx, task, template, usage, planned)
        if schema is None:
            return completion, usage
        return result, usage

    def _map_failure(
        self,
        exc: BaseException,
        spec: ProviderSpec,
        route: Route,
        retrying: Any,
        secrets: list[SecretKey],
    ) -> tuple[LLMError, Usage]:
        from instructor.core.exceptions import InstructorRetryException

        attempts = int(retrying.statistics.get("attempt_number", 1) or 1)
        if isinstance(exc, InstructorRetryException):
            usage = Usage.from_openai_usage(
                spec.name, route.model, getattr(exc, "total_usage", None),
                attempts=int(getattr(exc, "n_attempts", attempts) or attempts),
            )
            last = exc.args[0] if exc.args and isinstance(exc.args[0], BaseException) else None
            if last is None or (is_retryable(last) and not _is_transport_fault(last)):
                return (
                    LLMOutputError(
                        f"{spec.name}/{route.model} output failed validation after "
                        f"{usage.attempts} attempt(s)",
                        usage=usage, provider=spec.name, model=route.model,
                    ),
                    usage,
                )
            return map_provider_error(last, provider=spec.name, model=route.model, secrets=secrets), usage
        usage = Usage(provider=spec.name, model=route.model, attempts=attempts)
        return map_provider_error(exc, provider=spec.name, model=route.model, secrets=secrets), usage

    @staticmethod
    def _record(
        ctx: LLMRunContext,
        task: str,
        template: PromptTemplate,
        usage: Usage,
        planned: PlannedCall | None = None,
        *,
        status: str = "ok",
        error_kind: str = "",
    ) -> None:
        record = UsageRecord(
            task=task, template_id=template.id, template_hash=template.hash,
            usage=usage, status=status, error_kind=error_kind,
        )
        ctx.records.append(record)
        ctx.templates_used[template.id] = template.hash
        if ctx.meter is not None:
            ctx.meter.after_call(record, planned)


def _is_transport_fault(exc: BaseException) -> bool:
    import openai

    return isinstance(exc, (openai.APIError,))


_DEFAULT_PORT: LLMPort | None = None


def get_default_port() -> LLMPort:
    global _DEFAULT_PORT
    if _DEFAULT_PORT is None:
        _DEFAULT_PORT = LLMPort()
    return _DEFAULT_PORT


def set_default_port(port: LLMPort | None) -> None:
    """Swap the process port (tests inject one with a recorded transport)."""
    global _DEFAULT_PORT
    _DEFAULT_PORT = port


class TaskLLM:
    """The object ``LLMBridge.get_llm_for_task`` returns: one task, bridge-compatible calls.

    Credentials, run-wide route defaults and the meter come from the current
    :class:`~folio_insights.llm.context.LLMRunContext` at call time, so retrieving a TaskLLM never
    fails and never reads a key.
    """

    def __init__(
        self,
        task: str,
        *,
        port: LLMPort | None = None,
        route: Route | None = None,
    ) -> None:
        self.task = task
        self._port = port
        self._route = route

    @property
    def port(self) -> LLMPort:
        return self._port or get_default_port()

    def __repr__(self) -> str:
        return f"TaskLLM(task={self.task!r}, route={self._route!r})"

    def _template(self, template: PromptTemplate | None) -> PromptTemplate:
        return template or template_for_task(self.task)

    def _schema(self, schema: Any, template: PromptTemplate) -> type[BaseModel]:
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            return schema
        if template.output_schema is not None:
            # Legacy dict schemas are superseded by the template's validated model.
            return template.output_schema
        raise TypeError(f"LLM task {self.task!r} needs a Pydantic output schema")

    async def structured_model(
        self,
        prompt: str,
        schema: Any = None,
        *,
        template: PromptTemplate | None = None,
        temperature: float | None = 0.0,
        max_tokens: int | None = None,
    ) -> BaseModel:
        tpl = self._template(template)
        model_cls = self._schema(schema, tpl)
        result, _usage = await self.port.structured(
            self.task, model_cls, tpl.messages(prompt=prompt), template=tpl,
            route=self._route, temperature=temperature, max_tokens=max_tokens,
        )
        return result

    async def structured(
        self,
        prompt: str,
        schema: Any = None,
        *,
        template: PromptTemplate | None = None,
        temperature: float | None = 0.0,
        max_tokens: int | None = None,
        **_ignored: Any,
    ) -> dict[str, Any]:
        """Bridge-compatible: validated output returned as a plain dict."""
        result = await self.structured_model(
            prompt, schema, template=template, temperature=temperature, max_tokens=max_tokens
        )
        return result.model_dump()

    async def complete(
        self,
        prompt: str,
        *,
        template: PromptTemplate | None = None,
        temperature: float | None = 0.0,
        max_tokens: int | None = None,
        **_ignored: Any,
    ) -> str:
        tpl = self._template(template)
        text, _usage = await self.port.complete(
            self.task, tpl.messages(prompt=prompt), template=tpl, route=self._route,
            temperature=temperature, max_tokens=max_tokens,
        )
        return text

    def structured_model_sync(
        self,
        prompt: str,
        schema: Any = None,
        *,
        template: PromptTemplate | None = None,
        temperature: float | None = 0.0,
    ) -> BaseModel:
        """Blocking variant for synchronous callers (the polysemy detector and FP audit)."""
        return run_sync(
            lambda: self.structured_model(prompt, schema, template=template, temperature=temperature)
        )


def run_sync(coro_factory: Any) -> Any:
    """Run a coroutine to completion from synchronous code, inside or outside a running loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro_factory())
    ctx = contextvars.copy_context()
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(ctx.run, lambda: asyncio.run(coro_factory())).result()
