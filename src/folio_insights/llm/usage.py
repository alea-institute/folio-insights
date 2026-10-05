"""Provider-reported token usage (KTD8): the port returns one :class:`Usage` per call.

Usage is accounting, not estimation: every number here is what the provider's response said.
When instructor re-asks after a malformed reply, the provider bills every attempt, so the usage
of a call is the sum across its attempts (instructor accumulates it on the final completion, or
on the retry exception when every attempt failed).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Usage:
    """Tokens one port call consumed, as the provider reported them."""

    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    #: Portion of ``input_tokens`` served from the provider's prompt cache (if reported).
    cached_input_tokens: int = 0
    attempts: int = 1

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @classmethod
    def from_openai_usage(
        cls, provider: str, model: str, usage: Any, *, attempts: int = 1
    ) -> Usage:
        """Read an OpenAI-shaped ``CompletionUsage`` (every supported endpoint returns one)."""
        if usage is None:
            return cls(provider=provider, model=model, attempts=attempts)
        details = getattr(usage, "prompt_tokens_details", None)
        cached = int(getattr(details, "cached_tokens", 0) or 0) if details is not None else 0
        return cls(
            provider=provider,
            model=model,
            input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            cached_input_tokens=cached,
            attempts=attempts,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class UsageRecord:
    """One port call as the run context and the cost ledger see it."""

    task: str
    template_id: str
    template_hash: str
    usage: Usage
    status: str = "ok"  # "ok" | "error"
    error_kind: str = ""

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["usage"] = self.usage.to_dict()
        return out
