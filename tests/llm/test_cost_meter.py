"""Usage ledger, price table, cost meter and spend cap (Phase 10 U3)."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from decimal import Decimal

import pytest

from folio_insights.llm import (
    BudgetExhaustedError,
    LLMRunContext,
    UnpricedModelError,
    use_context,
)
from folio_insights.llm.cost import CostMeter, worst_case_cost
from folio_insights.llm.pricing import (
    PriceRow,
    PriceTable,
    PriceTableError,
    default_price_table,
    load_price_table,
)
from folio_insights.llm.schemas import DistilledOutput
from folio_insights.llm.templates import DISTILL
from folio_insights.llm.usage import Usage, UsageLedger
from tests.llm.conftest import FAKE_KEYS, LEAK_MARKER, Recorder, load_fixture, make_context, make_port

MESSAGES = DISTILL.messages(text="Synthetic sentence about objections.", section_path="Synthetic")


# ---- price table ---------------------------------------------------------------------------------


def test_repository_price_table_rows_are_dated_and_sourced() -> None:
    table = default_price_table()
    assert table.version == "2026-10-05"
    assert table.rows
    for row in table.rows:
        assert row.effective_date.isoformat() and row.source.strip()
    # The settings default and every provider's default model are priced.
    from folio_insights.llm.providers import PROVIDERS

    for spec in PROVIDERS.values():
        assert table.lookup(spec.name, spec.default_model) is not None, spec.name


@pytest.mark.parametrize("drop", ["effective_date", "source"])
def test_price_table_rejects_rows_without_date_or_source(drop: str) -> None:
    row = {"provider": "openai", "model": "gpt-x", "input_per_mtok": "1", "output_per_mtok": "2",
           "effective_date": "2026-10-05", "source": "https://example.invalid/pricing"}
    row.pop(drop)
    with pytest.raises(PriceTableError, match=drop):
        PriceTable.from_dict({"version": "v", "rows": [row]})


@pytest.mark.parametrize("bad", [
    {"effective_date": "05/10/2026"},
    {"input_per_mtok": "-1"},
    {"output_per_mtok": "free"},
    {"source": "   "},
])
def test_price_table_rejects_malformed_rows(bad: dict) -> None:
    row = {"provider": "openai", "model": "gpt-x", "input_per_mtok": "1", "output_per_mtok": "2",
           "effective_date": "2026-10-05", "source": "https://example.invalid/pricing", **bad}
    with pytest.raises(PriceTableError):
        PriceTable.from_dict({"version": "v", "rows": [row]})


def test_price_table_rejects_duplicates_and_missing_version(tmp_path) -> None:
    row = {"provider": "openai", "model": "gpt-x", "input_per_mtok": "1", "output_per_mtok": "2",
           "effective_date": "2026-10-05", "source": "s"}
    with pytest.raises(PriceTableError):
        PriceTable.from_dict({"version": "v", "rows": [row, row]})
    with pytest.raises(PriceTableError):
        PriceTable.from_dict({"rows": [row]})
    path = tmp_path / "t.json"
    path.write_text(json.dumps({"version": "v", "rows": [row]}))
    assert load_price_table(str(path)).lookup("openai", "gpt-x") is not None


def test_lookup_matches_snapshots_but_not_other_models() -> None:
    table = default_price_table()
    assert table.lookup("anthropic", "claude-haiku-4-5-20251001").model == "claude-haiku-4-5"
    assert table.lookup("openai", "gpt-4.1-mini-2025-04-14").model == "gpt-4.1-mini"
    assert table.lookup("openai", "gpt-4.1-turbo") is None  # not a snapshot of gpt-4.1
    assert table.lookup("ollama", "llama3.2").cost(10_000, 10_000) == 0
    assert table.lookup("google", "gemini-nonexistent") is None


def test_cost_arithmetic_is_exact_including_cached_input() -> None:
    row = default_price_table().lookup("openai", "gpt-4.1-mini")
    # 412 input (128 cached) + 37 output: (284*0.40 + 128*0.10 + 37*1.60) / 1e6
    expected = (Decimal(284) * Decimal("0.40") + Decimal(128) * Decimal("0.10")
                + Decimal(37) * Decimal("1.60")) / Decimal(1_000_000)
    assert row.cost(412, 37, 128) == expected == Decimal("0.0001856")


# ---- ledger ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("provider", ["openai", "anthropic", "google", "ollama"])
async def test_ledger_sum_equals_reported_usage_times_price_exactly(tmp_path, provider: str) -> None:
    fx = load_fixture(provider)
    rec = Recorder([fx["valid"], fx["malformed"], fx["valid"], fx["valid"]])
    ledger = UsageLedger(tmp_path / "queue.sqlite3")
    meter = CostMeter(run_id="run-1", ledger=ledger, corpus_id="synthetic")
    ctx = make_context(provider, meter=meter)
    port = make_port(rec)
    with use_context(ctx):
        for _ in range(3):  # the second call is re-asked once: 4 HTTP requests, 3 ledger rows
            await port.structured("distiller", DistilledOutput, MESSAGES)

    rows = ledger.rows("run-1")
    assert len(rows) == 3 and len(rec.requests) == 4
    price = default_price_table().lookup(provider, fx["model"])
    expected_total = Decimal(0)
    for row, record in zip(rows, ctx.records):
        u = record.usage
        expected = price.cost(u.input_tokens, u.output_tokens, u.cached_input_tokens)
        assert Decimal(row["cost_usd"]) == expected
        assert (row["input_tokens"], row["output_tokens"]) == (u.input_tokens, u.output_tokens)
        assert row["template_hash"] == DISTILL.hash and row["price_table_version"] == "2026-10-05"
        expected_total += expected
    assert ledger.run_total("run-1") == expected_total == meter.spent
    summary = ledger.summary("run-1")
    assert Decimal(summary["total_cost_usd"]) == expected_total and summary["calls"] == 3
    report = ctx.usage_summary()["cost"]
    assert Decimal(report["spent_usd"]) == expected_total


def test_ledger_never_holds_a_key_or_prompt(tmp_path) -> None:
    ledger = UsageLedger(tmp_path / "queue.sqlite3")
    assert not (tmp_path / "queue.sqlite3").exists()  # lazy: nothing until a call is booked
    from folio_insights.llm.usage import UsageRecord

    ledger.record(UsageRecord(task="distiller", template_id=DISTILL.id, template_hash=DISTILL.hash,
                              usage=Usage("openai", "gpt-4.1-mini", 10, 2)),
                  run_id="r", cost=Decimal("0.0000072"), price_table_version="2026-10-05")
    with sqlite3.connect(tmp_path / "queue.sqlite3") as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(llm_usage)")]
    assert not [c for c in cols if "key" in c or "prompt" in c or "text" in c]


# ---- spend cap ------------------------------------------------------------------------------------


def _bound(provider: str, model: str, port) -> Decimal:
    from folio_insights.llm import Route
    from folio_insights.llm.port import PlannedCall

    planned = PlannedCall(
        task="distiller", route=Route(provider, model), template_id=DISTILL.id,
        template_hash=DISTILL.hash, messages=tuple((m["role"], m["content"]) for m in MESSAGES),
        output_schema_json=json.dumps(DistilledOutput.model_json_schema()),
        max_tokens=port.max_tokens, max_attempts=port.max_attempts)
    return worst_case_cost(planned, default_price_table().lookup(provider, model))


async def test_cap_refuses_the_call_that_could_exceed_it_before_any_request(tmp_path) -> None:
    fx = load_fixture("openai")
    rec = Recorder([fx["valid"]])
    port = make_port(rec)
    first_cost = default_price_table().lookup("openai", fx["model"]).cost(412, 37, 128)
    bound = _bound("openai", fx["model"], port)
    assert bound > first_cost  # the bound really is an upper bound for this fixture
    cap = first_cost + bound - Decimal("0.0000001")  # room for call 1, not for call 2's worst case
    ledger = UsageLedger(tmp_path / "q.sqlite3")
    ctx = make_context("openai", meter=CostMeter(run_id="r", ledger=ledger, cap_usd=cap))
    with use_context(ctx):
        await port.structured("distiller", DistilledOutput, MESSAGES)
        with pytest.raises(BudgetExhaustedError) as info:
            await port.structured("distiller", DistilledOutput, MESSAGES)
    assert len(rec.requests) == 1  # refused before the request, not after
    assert ctx.halted is info.value  # the run stops (resumable), it does not degrade
    assert ledger.run_total("r") == first_cost <= cap
    assert LEAK_MARKER not in str(info.value)


async def test_concurrent_calls_reserve_their_worst_case(tmp_path) -> None:
    fx = load_fixture("google")
    rec = Recorder([fx["valid"]])
    port = make_port(rec)
    bound = _bound("google", fx["model"], port)
    ctx = make_context("google", meter=CostMeter(run_id="r", cap_usd=bound * Decimal("1.5")))
    with use_context(ctx):
        results = await asyncio.gather(
            *(port.structured("distiller", DistilledOutput, MESSAGES) for _ in range(4)),
            return_exceptions=True)
    assert sum(isinstance(r, BudgetExhaustedError) for r in results) == 3
    assert len(rec.requests) == 1


async def test_unpriced_model_under_a_cap_is_refused(tmp_path) -> None:
    rec = Recorder([load_fixture("openai")["valid"]])
    ctx = make_context("openai", model="gpt-unlisted",
                       meter=CostMeter(run_id="r", cap_usd="5"))
    with use_context(ctx), pytest.raises(UnpricedModelError):
        await make_port(rec).structured("distiller", DistilledOutput, MESSAGES)
    assert rec.requests == []
    # Without a cap the call is allowed and booked as unpriced.
    ctx = make_context("openai", model="gpt-unlisted", meter=CostMeter(run_id="r2"))
    with use_context(ctx):
        await make_port(Recorder([load_fixture("openai")["valid"]])).structured(
            "distiller", DistilledOutput, MESSAGES)
    assert ctx.usage_summary()["cost"]["unpriced_calls"] == 1


def test_meter_resumes_from_prior_spend(tmp_path) -> None:
    from folio_insights.llm.usage import UsageRecord

    ledger = UsageLedger(tmp_path / "q.sqlite3")
    ledger.record(UsageRecord(task="distiller", template_id="t", template_hash="h",
                              usage=Usage("google", "gemini-2.5-flash-lite", 1000, 100)),
                  run_id="job-1", cost=Decimal("0.00014"), price_table_version="2026-10-05")
    meter = CostMeter(run_id="job-1", ledger=ledger, cap_usd="1")
    assert meter.spent == Decimal("0.00014")


@pytest.mark.parametrize("bad", ["0", "-1", "abc", "nan"])
def test_cap_must_be_a_positive_number(bad: str) -> None:
    with pytest.raises(ValueError):
        CostMeter(run_id="r", cap_usd=bad)


def test_price_row_type_is_frozen() -> None:
    row = default_price_table().rows[0]
    assert isinstance(row, PriceRow)
    with pytest.raises(AttributeError):
        row.source = "x"  # type: ignore[misc]


def test_fake_keys_are_unused_here() -> None:
    assert all(LEAK_MARKER in k for k in FAKE_KEYS.values())


def test_llm_run_context_without_meter_has_no_cost_section() -> None:
    assert "cost" not in LLMRunContext().usage_summary()
