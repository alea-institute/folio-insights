"""Cost meter and spend cap (KTD8, R4).

:class:`CostMeter` is the run context's :class:`~folio_insights.llm.context.UsageMeter`. It is
consulted at three points of every port call:

* ``before_call`` -- refuses an unpriced model under a cap, and a call whose first attempt
  alone could not fit;
* ``reserve_attempt`` -- runs inside the HTTP transport immediately before EACH request
  (first attempt and every re-ask or retry) is sent, with the exact request body in hand. The
  attempt's worst case is ``price(request_bytes + overhead input tokens, max_tokens output
  tokens)``: every tokenizer the supported providers use spends at least one UTF-8 byte per
  input token, and ``max_tokens`` caps the output. If what the run has spent, plus what
  in-flight attempts have reserved, plus this bound would exceed the cap, the request is never
  sent (``BudgetExhaustedError``). The reservation is written to the ledger as an
  ``in_flight`` row first, so a crash or kill mid-call leaves the run charged at that bound;
* ``settle_call`` -- books the provider-reported usage at the table price, plus the reserved
  worst case of every attempt that may have been billed without reporting usage (read timeout
  after send, 5xx, cancellation, a 2xx without ``usage``). Settled spend therefore never
  exceeds what was reserved, and reserved spend never exceeds the cap.

The meter starts from the ledger's total for its run id (settled rows plus any ``in_flight``
rows a crash left behind), so a job resumed after ``budget_exhausted`` or retried after a crash
keeps counting what it already spent.

Stdlib-only: the lean worker image imports it.
"""

from __future__ import annotations

import dataclasses
import os
import threading
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from folio_insights.llm.errors import BudgetExhaustedError, UnpricedModelError
from folio_insights.llm.pricing import PriceRow, PriceTable, default_price_table
from folio_insights.llm.usage import UsageLedger, UsageRecord

SPEND_CAP_ENV = "FOLIO_INSIGHTS_LLM_MAX_SPEND_USD"
# Tokens the provider adds beyond the request body (tool-use system prompts and chat framing;
# Anthropic's tool system prompt is ~600 tokens). Generous on purpose.
_OVERHEAD_TOKENS = 1024


def attempt_bound(price: PriceRow, request_bytes: int, max_tokens: int) -> Decimal:
    """Upper bound on the cost of ONE request with a ``request_bytes`` body."""
    return price.cost(int(request_bytes) + _OVERHEAD_TOKENS, int(max_tokens), 0)


def worst_case_cost(planned: Any, price: PriceRow) -> Decimal:
    """Upper bound on a planned call's first attempt (its prompt and schema, before framing)."""
    return attempt_bound(price, int(planned.prompt_bytes), int(planned.max_tokens))


def parse_cap(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        cap = Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"spend cap {value!r} is not a number") from None
    if not cap.is_finite() or cap <= 0:
        raise ValueError("spend cap must be a finite, positive number of USD")
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

    def _committed(self) -> Decimal:
        return self.spent + sum(self._reserved.values(), Decimal(0))

    def _refuse(self, planned: Any, bound: Decimal) -> BudgetExhaustedError:
        committed = self._committed()
        return BudgetExhaustedError(
            f"spend cap ${self.cap} reached: ${self.spent} spent (${committed - self.spent} "
            f"reserved in flight); the next {planned.task} request could cost up to "
            f"${bound.quantize(Decimal('0.000001'))}",
            provider=planned.route.provider, model=planned.route.model,
        )

    def _price(self, planned: Any) -> PriceRow | None:
        route = planned.route
        price = self.prices.lookup(route.provider, route.model)
        if price is None and self.cap is not None:
            raise UnpricedModelError(
                f"spend cap ${self.cap} is set but price table {self.prices.version} has no row "
                f"for {route.provider}/{route.model}; refusing an unbounded call",
                provider=route.provider, model=route.model,
            )
        return price

    def before_call(self, planned: Any) -> None:
        """Cheap pre-check: refuse an unpriced model, or a first attempt that cannot fit."""
        price = self._price(planned)
        if self.cap is None or price is None:
            return
        bound = worst_case_cost(planned, price)
        with self._lock:
            if self._committed() + bound > self.cap:
                raise self._refuse(planned, bound)

    def reserve_attempt(self, account: Any, request_bytes: int) -> Decimal | None:
        """Reserve one request's worst case before it is sent; raise if it could exceed the cap."""
        planned = account.planned
        price = self._price(planned)
        bound = None if price is None else attempt_bound(price, request_bytes, planned.max_tokens)
        key = id(account)
        with self._lock:
            if bound is not None:
                if self.cap is not None and self._committed() + bound > self.cap:
                    raise self._refuse(planned, bound)
                self._reserved[key] = self._reserved.get(key, Decimal(0)) + bound
            reserved = self._reserved.get(key)
        if self.ledger is not None:
            if account.ledger_row is None:
                account.ledger_row = self.ledger.open_in_flight(
                    run_id=self.run_id, task=planned.task, provider=planned.route.provider,
                    model=planned.route.model, template_id=planned.template_id,
                    template_hash=planned.template_hash, reserved=reserved or Decimal(0),
                    price_table_version=self.prices.version, job_id=self.job_id,
                    corpus_id=self.corpus_id,
                )
            else:
                self.ledger.raise_in_flight(account.ledger_row, reserved or Decimal(0),
                                            account.sent_count + 1)
        return bound

    def settle_call(self, account: Any, record: UsageRecord) -> UsageRecord:
        """Book a finished call: reported usage at price + worst case of unaccounted attempts."""
        price = self.prices.lookup(record.usage.provider, record.usage.model)
        worst = Decimal(0)
        if price is None:
            cost = None
        else:
            worst = sum((b for b in account.unaccounted_bounds() if b is not None), Decimal(0))
            cost = price.cost(record.usage.input_tokens, record.usage.output_tokens,
                              record.usage.cached_input_tokens) + worst
        with self._lock:
            self._reserved.pop(id(account), None)
            if cost is None:
                self._unpriced += 1
            else:
                self.spent += cost
        record = dataclasses.replace(record, worst_case_usd=worst)
        if self.ledger is not None:
            if account.ledger_row is not None:
                self.ledger.settle(account.ledger_row, record, cost=cost)
            else:
                self.ledger.record(record, run_id=self.run_id, cost=cost,
                                   price_table_version=self.prices.version,
                                   job_id=self.job_id, corpus_id=self.corpus_id)
        return record

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
    """Meter for a queued job: ledger in the queue database, cap from the job or environment.

    Raises ``ValueError`` for a malformed cap; the worker fails such a job permanently.
    """
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
