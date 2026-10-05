"""The per-run LLM context: whose key, which route, which meter.

Stage code calls ``LLMBridge().get_llm_for_task(task)`` exactly as before; what that call may
use is decided here, by whoever started the run:

* the CLI installs a process default built from the invoking user's environment and its
  ``--llm-provider`` / ``--llm-model`` flags;
* a queued job installs a context for the duration of the job, holding the user's in-memory
  credential handle and the job's cost meter.

With no context installed (library use, tests, the API process outside a job) the effective
context has **no credentials**, so a provider that needs a key raises
:class:`~folio_insights.llm.errors.MissingCredentialsError` instead of reaching for an ambient
server key (R2).
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol

from folio_insights.llm.credentials import Credentials
from folio_insights.llm.errors import RunHalted
from folio_insights.llm.usage import UsageRecord


class UsageMeter(Protocol):
    """What the port consults around each call (the cost meter implements it)."""

    def before_call(self, planned: Any) -> None:
        """Raise :class:`~folio_insights.llm.errors.RunHalted` to refuse the call."""

    def after_call(self, record: UsageRecord, planned: Any = None) -> None:
        """Account for a completed (or failed-but-billed) call and release its reservation."""


@dataclass(eq=False)
class LLMRunContext:
    """Credentials, route defaults and accounting for one run."""

    credentials: Credentials = field(default_factory=Credentials.empty)
    #: Run-wide provider/model (CLI flags, API request). Per-task env overrides still win.
    provider: str | None = None
    model: str | None = None
    run_id: str | None = None
    meter: UsageMeter | None = None
    records: list[UsageRecord] = field(default_factory=list)
    #: template id -> template hash, for every template this run actually called.
    templates_used: dict[str, str] = field(default_factory=dict)
    halted: RunHalted | None = None

    def halt(self, exc: RunHalted) -> None:
        if self.halted is None:
            self.halted = exc

    def raise_if_halted(self) -> None:
        if self.halted is not None:
            raise self.halted

    def usage_summary(self) -> dict[str, Any]:
        """Token totals per (task, provider, model) for run reports. No credential data."""
        groups: dict[tuple[str, str, str], dict[str, int]] = {}
        for rec in self.records:
            key = (rec.task, rec.usage.provider, rec.usage.model)
            g = groups.setdefault(key, {"calls": 0, "errors": 0, "input_tokens": 0,
                                        "output_tokens": 0, "cached_input_tokens": 0})
            g["calls"] += 1
            g["errors"] += rec.status != "ok"
            g["input_tokens"] += rec.usage.input_tokens
            g["output_tokens"] += rec.usage.output_tokens
            g["cached_input_tokens"] += rec.usage.cached_input_tokens
        summary: dict[str, Any] = {
            "calls": len(self.records),
            "by_task": [
                {"task": t, "provider": p, "model": m, **vals}
                for (t, p, m), vals in sorted(groups.items())
            ],
            "templates": dict(sorted(self.templates_used.items())),
        }
        report = getattr(self.meter, "report", None)
        if report is not None:
            summary["cost"] = report()
        return summary


_CURRENT: contextvars.ContextVar[LLMRunContext | None] = contextvars.ContextVar(
    "folio_insights_llm_context", default=None
)
_PROCESS_DEFAULT: LLMRunContext | None = None


def current_context() -> LLMRunContext:
    """The installed context, else the process default, else an empty (keyless) one."""
    ctx = _CURRENT.get()
    if ctx is not None:
        return ctx
    if _PROCESS_DEFAULT is not None:
        return _PROCESS_DEFAULT
    return LLMRunContext()


@contextmanager
def use_context(ctx: LLMRunContext) -> Iterator[LLMRunContext]:
    """Install ``ctx`` for the enclosed block (and every task it spawns)."""
    token = _CURRENT.set(ctx)
    try:
        yield ctx
    finally:
        _CURRENT.reset(token)


def set_process_default(ctx: LLMRunContext | None) -> None:
    """Install a process-wide fallback context. Only the CLI entry point calls this."""
    global _PROCESS_DEFAULT
    _PROCESS_DEFAULT = ctx
