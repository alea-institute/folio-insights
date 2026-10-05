"""Versioned, dated LLM price table (KTD8).

Cost is accounting, not estimation: the ledger multiplies the usage each provider *reported*
by the price row for that provider/model. Rows live in ``price_table.json`` next to this module,
each with an ``effective_date`` and a ``source`` note; a row without either is refused when the
table loads, so an unsourced price can never reach the ledger.

All arithmetic is :class:`~decimal.Decimal`, so the ledger total equals usage x price exactly.
This module is stdlib-only (the lean worker image imports it).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from importlib import resources
from typing import Any

MILLION = Decimal(1_000_000)


class PriceTableError(ValueError):
    """The price table (or one of its rows) is malformed."""


def _decimal(value: Any, field: str, where: str) -> Decimal:
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise PriceTableError(f"{where}: {field} {value!r} is not a number") from None
    if out < 0 or not out.is_finite():
        raise PriceTableError(f"{where}: {field} must be a finite, non-negative price")
    return out


@dataclass(frozen=True)
class PriceRow:
    """USD per 1,000,000 tokens for one provider/model, with its date and source."""

    provider: str
    model: str
    input_per_mtok: Decimal
    output_per_mtok: Decimal
    cached_input_per_mtok: Decimal | None
    effective_date: date
    source: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any], index: int = 0) -> PriceRow:
        where = f"price row {index} ({raw.get('provider')}/{raw.get('model')})"
        for field in ("provider", "model"):
            if not str(raw.get(field) or "").strip():
                raise PriceTableError(f"{where}: missing {field}")
        when = str(raw.get("effective_date") or "").strip()
        if not when:
            raise PriceTableError(f"{where}: missing effective_date")
        try:
            effective = date.fromisoformat(when)
        except ValueError:
            raise PriceTableError(f"{where}: effective_date {when!r} is not YYYY-MM-DD") from None
        source = str(raw.get("source") or "").strip()
        if not source:
            raise PriceTableError(f"{where}: missing source")
        cached = raw.get("cached_input_per_mtok")
        return cls(
            provider=str(raw["provider"]).strip().lower(),
            model=str(raw["model"]).strip(),
            input_per_mtok=_decimal(raw.get("input_per_mtok"), "input_per_mtok", where),
            output_per_mtok=_decimal(raw.get("output_per_mtok"), "output_per_mtok", where),
            cached_input_per_mtok=(
                None if cached is None else _decimal(cached, "cached_input_per_mtok", where)
            ),
            effective_date=effective,
            source=source,
        )

    def cost(self, input_tokens: int, output_tokens: int, cached_input_tokens: int = 0) -> Decimal:
        """Exact USD cost. Cached tokens are part of ``input_tokens`` (as providers report them)."""
        cached = max(0, min(int(cached_input_tokens), int(input_tokens)))
        fresh = int(input_tokens) - cached
        cached_rate = self.cached_input_per_mtok
        if cached_rate is None:
            cached_rate = self.input_per_mtok
        return (
            Decimal(fresh) * self.input_per_mtok
            + Decimal(cached) * cached_rate
            + Decimal(int(output_tokens)) * self.output_per_mtok
        ) / MILLION


@dataclass(frozen=True)
class PriceTable:
    version: str
    rows: tuple[PriceRow, ...]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PriceTable:
        version = str(raw.get("version") or "").strip()
        if not version:
            raise PriceTableError("price table has no version")
        rows = tuple(PriceRow.from_dict(r, i) for i, r in enumerate(raw.get("rows") or []))
        keys = [(r.provider, r.model) for r in rows]
        if len(keys) != len(set(keys)):
            raise PriceTableError("price table lists a provider/model twice")
        return cls(version=version, rows=rows)

    def lookup(self, provider: str, model: str) -> PriceRow | None:
        """The row for exactly this provider/model, else the provider's ``*`` row, else None.

        No prefix or suffix inference: a dated snapshot can be priced differently from its alias
        (``gpt-4o-2024-05-13`` is not ``gpt-4o``), so every snapshot is listed explicitly.
        """
        provider = provider.strip().lower()
        wildcard: PriceRow | None = None
        for row in self.rows:
            if row.provider != provider:
                continue
            if row.model == model:
                return row
            if row.model == "*":
                wildcard = row
        return wildcard

    def cost_of(self, usage: Any) -> Decimal | None:
        """Exact cost of a :class:`~folio_insights.llm.usage.Usage`, or ``None`` if unpriced."""
        row = self.lookup(usage.provider, usage.model)
        if row is None:
            return None
        return row.cost(usage.input_tokens, usage.output_tokens, usage.cached_input_tokens)


def load_price_table(path: str | None = None) -> PriceTable:
    """The repository's table (or ``path``), validated."""
    if path:
        with open(path, encoding="utf-8") as fh:
            return PriceTable.from_dict(json.load(fh))
    text = resources.files("folio_insights.llm").joinpath("price_table.json").read_text("utf-8")
    return PriceTable.from_dict(json.loads(text))


_DEFAULT: PriceTable | None = None


def default_price_table() -> PriceTable:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = load_price_table()
    return _DEFAULT
