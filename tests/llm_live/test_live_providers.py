"""Opt-in live provider smoke (Phase 10 KTD9, live tier). Never part of default CI.

Runs the same synthetic extraction calls on each provider with the OPERATOR's own keys, read
from the operator's environment the way the CLI reads them. Agents never run this tier.

Enable with::

    FOLIO_INSIGHTS_LIVE_LLM=1 pytest -m live_llm tests/llm_live -q

Each provider runs only when its key is set (Ollama: ``FOLIO_INSIGHTS_LIVE_OLLAMA=1`` and a
local server). ``FOLIO_INSIGHTS_LIVE_LLM_REPORT=<path>`` writes the per-provider usage and cost
table (tokens and ledger cost only; no prompts, no keys).

Cost check (U3, the plan's +/-5% claim): run the smoke on a provider account/project used for
nothing else in the window, read that window's charge from the provider's invoice or usage
export, and pass it as ``FOLIO_INSIGHTS_LIVE_INVOICE_USD_<PROVIDER>`` (for example
``..._GOOGLE=0.000412``). The test then asserts the ledger total is within 5% of it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from decimal import Decimal

from folio_insights.llm import Credentials, LLMPort, LLMRunContext, use_context
from folio_insights.llm.cost import CostMeter
from folio_insights.llm.usage import UsageLedger
from folio_insights.llm.schemas import ClassificationOutput, ConceptOutput, DistilledOutput
from folio_insights.llm.templates import CLASSIFY, CONCEPT, DISTILL

pytestmark = [
    pytest.mark.live_llm,
    pytest.mark.skipif(
        os.environ.get("FOLIO_INSIGHTS_LIVE_LLM") != "1",
        reason="live LLM tier is opt-in (FOLIO_INSIGHTS_LIVE_LLM=1)",
    ),
]

# Synthetic, openly authored text: no book or client source text ever enters this tier.
SYNTHETIC = (
    "Object to a leading question on direct examination before the witness answers; "
    "an objection after the answer preserves the record but cannot un-ring the bell."
)

LIVE_MODELS = {
    "openai": os.environ.get("FOLIO_INSIGHTS_LIVE_OPENAI_MODEL", "gpt-4.1-mini"),
    "anthropic": os.environ.get("FOLIO_INSIGHTS_LIVE_ANTHROPIC_MODEL", "claude-haiku-4-5"),
    "google": os.environ.get("FOLIO_INSIGHTS_LIVE_GOOGLE_MODEL", "gemini-2.5-flash-lite"),
    "ollama": os.environ.get("FOLIO_INSIGHTS_LIVE_OLLAMA_MODEL", "llama3.2"),
}


def _skip_without_access(provider: str, creds: Credentials) -> None:
    if provider == "ollama":
        if os.environ.get("FOLIO_INSIGHTS_LIVE_OLLAMA") != "1":
            pytest.skip("set FOLIO_INSIGHTS_LIVE_OLLAMA=1 with a local Ollama server")
    elif creds.get(provider) is None:
        pytest.skip(f"no {provider} key in the operator environment")


@pytest.mark.parametrize("provider", sorted(LIVE_MODELS))
async def test_live_synthetic_extraction(provider: str, tmp_path: Path) -> None:
    creds = Credentials.from_env()
    _skip_without_access(provider, creds)
    run_id = f"live-smoke-{provider}"
    ledger = UsageLedger(tmp_path / "ledger.sqlite3")
    ctx = LLMRunContext(credentials=creds, provider=provider, model=LIVE_MODELS[provider],
                        run_id=run_id, meter=CostMeter(run_id=run_id, ledger=ledger))
    port = LLMPort()
    with use_context(ctx):
        distilled, _ = await port.structured(
            "distiller", DistilledOutput, DISTILL.messages(text=SYNTHETIC, section_path="Synthetic"))
        classified, _ = await port.structured(
            "classifier", ClassificationOutput, CLASSIFY.messages(text=SYNTHETIC, section_path="Synthetic"))
        concepts, _ = await port.structured(
            "concept", ConceptOutput, CONCEPT.messages(text=SYNTHETIC, context="Synthetic"))
    assert distilled.distilled_text.strip()
    assert classified.unit_type
    assert isinstance(concepts.concepts, list)
    assert all(r.usage.input_tokens > 0 for r in ctx.records)
    total = ledger.run_total(run_id)

    invoice = os.environ.get(f"FOLIO_INSIGHTS_LIVE_INVOICE_USD_{provider.upper()}")
    if invoice:
        expected = Decimal(invoice)
        assert abs(total - expected) <= expected * Decimal("0.05"), (total, expected)

    report = os.environ.get("FOLIO_INSIGHTS_LIVE_LLM_REPORT")
    if report:
        path = Path(report)
        rows = json.loads(path.read_text()) if path.exists() else []
        rows.append({"provider": provider, "model": LIVE_MODELS[provider],
                     "ledger_total_usd": str(total), "summary": ctx.usage_summary()})
        path.write_text(json.dumps(rows, indent=2))
