"""Cost meter and spend cap (KTD8, R4).

:class:`CostMeter` is the run context's :class:`~folio_insights.llm.context.UsageMeter`. The
port consults it around every call:

* ``before_call`` -- with a cap set, refuses the call (``BudgetExhaustedError``) when what the
  run has spent, plus what in-flight calls have reserved, plus this call's *worst case* would
  exceed the cap. The worst case is an upper bound, not a guess: every tokenizer the supported
  providers use spends at least one UTF-8 byte per input token, so the prompt's byte count
  (plus per-message and re-ask overhead) bounds its input tokens, and ``max_tokens`` bounds each
  attempt's output. The cap therefore stops a run *before* the call that could exceed it. An
  unpriced model under a cap is refused outright (``UnpricedModelError``).
* ``after_call`` -- releases the reservation and books the provider-reported usage at the
  table's price into the :class:`~folio_insights.llm.usage.UsageLedger`.

The meter starts from the ledger's existing total for its run id, so a job resumed after
``budget_exhausted`` (or retried after a crash) keeps counting what it already spent.

Stdlib-only: the lean worker image imports it.
"""

from __future__ import annotations

import os
import threading
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from folio_insights.llm.errors import BudgetExhaustedError, UnpricedModelError
from folio_insights.llm.pricing import PriceTable, default_price_table
from folio_insights.llm.usage import UsageLedger, UsageRecord

SPEND_CAP_ENV = "FOLIO_INSIGHTS_LLM_MAX_SPEND_USD"
# Per-message chat framing and tool-use system prompts, in tokens (generous: Anthropic's tool
# system prompt is ~600 tokens, OpenAI/Gemini framing is smaller).
_OVERHEAD_TOKENS = 1024
# A re-ask appends the previous reply (<= max_tokens) and the validation error text.
_REASK_ERROR_TOKENS = 2048


def worst_case_cost(planned: Any, price: Any) -> Decimal:
    """Upper bound on the USD cost of a planned call, across all its retry attempts."""
    n = int(planned.max_attempts)
    base_in = int(planned.prompt_bytes) + _OVERHEAD_TOKENS
    growth = int(planned.max_tokens) + _REASK_ERROR_TOKENS
    input_tokens = n * base_in + growth * n * (n - 1) // 2
    output_tokens = n * int(planned.max_tokens)
    # Cached input is never dearer than fresh input, so price everything as fresh.
    return price.cost(input_tokens, output_tokens, 0)


def parse_cap(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        cap = Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"spend cap {value!r} is not a number") from None
    if not cap.is_finite() or cap <= 0:
        raise ValueError("spend cap must be a positive number of USD")
    return cap


class CostMeter:
    """Books every call's cost and enforces an optional spend cap for one run."""

    def __init__(
        self,
        *,
        run_id: str,
        ledger: UsageLedger | None = None,
        price_table: PriceTable | None = None,
        cap_usd: Decimal | float | str | None = None,
        job_id: str | None = None,
        corpus_id: str = "",
    ) -> None:
        self.run_id = run_id
        self.ledger = ledger
        self.prices = price_table or default_price_table()
        self.cap = parse_cap(cap_usd)
        self.job_id = job_id
        self.corpus_id = corpus_id
        self.spent = ledger.run_total(run_id) if ledger is not None else Decimal(0)
        self._reserved: dict[int, Decimal] = {}
        self._unpriced = 0
        self._lock = threading.Lock()

    def before_call(self, planned: Any) -> None:
        if self.cap is None:
            return
        route = planned.route
        price = self.prices.lookup(route.provider, route.model)
        if price is None:
            raise UnpricedModelError(
                f"spend cap ${self.cap} is set but price table {self.prices.version} has no row "
                f"for {route.provider}/{route.model}; refusing an unbounded call",
                provider=route.provider, model=route.model,
            )
        bound = worst_case_cost(planned, price)
        with self._lock:
            committed = self.spent + sum(self._reserved.values(), Decimal(0))
            if committed + bound > self.cap:
                raise BudgetExhaustedError(
                    f"spend cap ${self.cap} reached: ${self.spent} spent"
                    f" (${committed - self.spent} in flight); the next {planned.task} call"
                    f" could cost up to ${bound.quantize(Decimal('0.000001'))}",
                    provider=route.provider, model=route.model,
                )
            self._reserved[id(planned)] = bound

    def after_call(self, record: UsageRecord, planned: Any = None) -> None:
        cost = self.prices.cost_of(record.usage)
        with self._lock:
            if planned is not None:
                self._reserved.pop(id(planned), None)
            if cost is None:
                self._unpriced += 1
            else:
                self.spent += cost
        if self.ledger is not None:
            self.ledger.record(record, run_id=self.run_id, cost=cost,
                               price_table_version=self.prices.version,
                               job_id=self.job_id, corpus_id=self.corpus_id)

    def release(self, planned: Any) -> None:
        """Drop a reservation for a call that never reached the provider."""
        with self._lock:
            self._reserved.pop(id(planned), None)

    def report(self) -> dict[str, Any]:
        """Cost section of a run report (exact decimal strings; no credentials)."""
        out: dict[str, Any] = {
            "price_table_version": self.prices.version,
            "spent_usd": str(self.spent),
            "cap_usd": None if self.cap is None else str(self.cap),
            "unpriced_calls": self._unpriced,
        }
        if self.ledger is not None:
            out["ledger"] = self.ledger.summary(self.run_id)
        return out


def job_meter_factory(job: Any, queue: Any) -> CostMeter:
    """Meter for a queued job: ledger in the queue database, cap from the job or environment."""
    llm = (getattr(job, "payload", None) or {}).get("llm") or {}
    cap = llm.get("max_spend_usd")
    if cap is None:
        cap = os.environ.get(SPEND_CAP_ENV) or None
    return CostMeter(
        run_id=job.id,
        ledger=UsageLedger(Path(queue.path)),
        cap_usd=cap,
        job_id=job.id,
        corpus_id=getattr(job, "corpus_id", "") or "",
    )
