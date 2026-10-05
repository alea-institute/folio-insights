"""Regression tests for the Phase 10 U1-U3 review findings on the LLM side (2026-10-05).

Each test names the finding it pins. All offline: recorded transports, fake keys, temp roots.
"""

from __future__ import annotations

import asyncio
import json
import logging
import traceback
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from pydantic import BaseModel

from folio_insights.llm import (
    BudgetExhaustedError,
    Credentials,
    LLMAuthError,
    LLMError,
    LLMModelNotFoundError,
    LLMPort,
    LLMRunContext,
    Route,
    use_context,
)
from folio_insights.llm.cost import CostMeter, attempt_bound
from folio_insights.llm.pricing import default_price_table
from folio_insights.llm.schemas import DistilledOutput
from folio_insights.llm.templates import CLASSIFY, DISTILL
from folio_insights.llm.usage import IN_FLIGHT, UsageLedger
from tests.llm.conftest import FAKE_KEYS, LEAK_MARKER, Recorder, load_fixture, make_context, make_port

MESSAGES = DISTILL.messages(text="Synthetic sentence about objections.", section_path="Synthetic")
KEY = "sk-proj-FAKEKEYabcdef0123456789zzzz"


class Out(BaseModel):
    x: int


def _port(handler, **kw) -> LLMPort:
    kw.setdefault("retry_wait_seconds", 0)
    kw.setdefault("max_attempts", 3)
    return LLMPort(http_client_factory=lambda _s: httpx.AsyncClient(
        transport=httpx.MockTransport(handler)), **kw)


def _ok(usage: dict | None = None):
    body = {"id": "x", "object": "chat.completion", "created": 0, "model": "gpt-4.1-mini",
            "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                "role": "assistant", "content": None, "tool_calls": [{
                    "id": "c", "type": "function",
                    "function": {"name": "Out", "arguments": '{"x": 1}'}}]}}]}
    if usage is not None:
        body["usage"] = usage
    return body


# ---- P1-3: the spend cap is an upper bound ----------------------------------------------------


async def test_p1_3_timeouts_are_booked_at_worst_case_and_spend_never_passes_the_cap() -> None:
    calls = {"n": 0}

    def timeout(req):
        calls["n"] += 1
        raise httpx.ReadTimeout("read timed out", request=req)  # sent; maybe billed

    port = _port(timeout)
    cap = Decimal("0.50")
    meter = CostMeter(run_id="r1", cap_usd=cap)
    ctx = LLMRunContext(credentials=Credentials.single("openai", KEY), provider="openai",
                        model="gpt-4.1", meter=meter)
    refused = False
    with use_context(ctx):
        for _ in range(40):
            try:
                await port.structured("distiller", Out, [{"role": "user", "content": "x" * 2000}])
            except BudgetExhaustedError:
                refused = True
                break
            except LLMError:
                continue
    assert refused, "the cap never stopped the run"
    assert Decimal(0) < meter.spent <= cap
    assert not meter._reserved
    # each request body is >= 2000 bytes, so each booked bound is at least this much
    bound = attempt_bound(default_price_table().lookup("openai", "gpt-4.1"), 2000, DISTILL.max_tokens)
    assert calls["n"] <= int(cap / bound) + 1  # every sent attempt was booked at its bound
    assert all(r.usage.unaccounted_attempts == r.usage.attempts for r in ctx.records)


@pytest.mark.parametrize("case,booked", [
    ("server_error", True),     # 5xx after send: may be billed
    ("no_usage", True),         # 2xx without a usage block
    ("bad_request", False),     # 4xx: never billed
    ("connect_error", False),   # never left the client
])
async def test_p1_3_unreported_attempts_are_booked_only_when_they_may_be_billed(case, booked) -> None:
    def handler(req):
        if case == "server_error":
            return httpx.Response(500, json={"error": {"message": "boom"}})
        if case == "no_usage":
            return httpx.Response(200, json=_ok(None))
        if case == "bad_request":
            return httpx.Response(400, json={"error": {"message": "bad param"}})
        raise httpx.ConnectError("refused", request=req)

    meter = CostMeter(run_id="r", cap_usd="100")
    ctx = LLMRunContext(credentials=Credentials.single("openai", KEY), provider="openai",
                        model="gpt-4.1-mini", meter=meter)
    with use_context(ctx):
        try:
            await _port(handler, max_attempts=1).structured(
                "distiller", Out, [{"role": "user", "content": "hi"}])
        except LLMError:
            pass
    rec = ctx.records[-1]
    assert (rec.usage.unaccounted_attempts == 1) is booked
    assert (meter.spent > 0) is booked and (rec.worst_case_usd > 0) is booked


async def test_p1_3_in_flight_calls_survive_a_crash_and_cancellation_is_booked(tmp_path) -> None:
    gate = asyncio.Event()

    async def hang(req):
        await gate.wait()
        return httpx.Response(200, json=_ok({"prompt_tokens": 5, "completion_tokens": 1}))

    ledger = UsageLedger(tmp_path / "q.sqlite3")
    meter = CostMeter(run_id="job-1", ledger=ledger, cap_usd="10")
    ctx = LLMRunContext(credentials=Credentials.single("openai", KEY), provider="openai",
                        model="gpt-4.1-mini", meter=meter)

    async def call():
        with use_context(ctx):
            await _port(hang).structured("distiller", Out, [{"role": "user", "content": "hi"}])

    task = asyncio.create_task(call())
    for _ in range(200):
        rows = ledger.rows("job-1")
        if rows:
            break
        await asyncio.sleep(0.01)
    assert rows and rows[0]["status"] == IN_FLIGHT and Decimal(rows[0]["cost_usd"]) > 0
    # A process that died here leaves the bound on the books: a new meter starts from it.
    assert CostMeter(run_id="job-1", ledger=ledger).spent == Decimal(rows[0]["cost_usd"])

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    settled = ledger.rows("job-1")[0]
    assert settled["status"] == "error" and settled["unaccounted_attempts"] == 1
    assert Decimal(settled["cost_usd"]) == Decimal(rows[0]["cost_usd"])  # booked at worst case


# ---- P1-4: LLM failures that should halt do halt ----------------------------------------------


@pytest.mark.parametrize("status,exc_type", [(401, LLMAuthError), (404, LLMModelNotFoundError)])
async def test_p1_4_rejected_key_or_unknown_model_halts_the_stage(status, exc_type) -> None:
    from folio_insights.llm import set_default_port
    from folio_insights.models.knowledge_unit import KnowledgeType, KnowledgeUnit, Span
    from folio_insights.pipeline.stages.base import InsightsJob
    from folio_insights.pipeline.stages.distiller import DistillerStage

    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(status, json={"error": {"message": "no"}})

    set_default_port(_port(handler))
    try:
        units = [KnowledgeUnit(text=f"Always object to leading questions, synthetic unit {i}.",
                               original_span=Span(start=0, end=10, source_file="s.md"),
                               unit_type=KnowledgeType.ADVICE, source_file="s.md")
                 for i in range(10)]
        job = InsightsJob(corpus_name="c", source_dir=Path("."), units=units)
        ctx = LLMRunContext(credentials=Credentials.single("openai", KEY), provider="openai",
                            model="gpt-4.1-mini")
        with use_context(ctx), pytest.raises(exc_type):
            await DistillerStage().execute(job)
        assert isinstance(ctx.halted, exc_type)
        assert calls["n"] <= 15  # one batch at most; later calls fail fast without a request
    finally:
        set_default_port(None)


async def test_p1_4_per_unit_failures_above_the_ratio_fail_the_stage() -> None:
    from folio_insights.llm import set_default_port
    from folio_insights.models.knowledge_unit import KnowledgeType, KnowledgeUnit, Span
    from folio_insights.pipeline.stages.base import InsightsJob, StageFailureRatioError
    from folio_insights.pipeline.stages.knowledge_classifier import KnowledgeClassifierStage

    def handler(req):  # a per-call problem (not a halt): every classify call fails
        return httpx.Response(400, json={"error": {"message": "content too long"}})

    set_default_port(_port(handler))
    try:
        units = [KnowledgeUnit(text=f"Synthetic unit {i}.",
                               original_span=Span(start=0, end=10, source_file="s.md"),
                               unit_type=KnowledgeType.ADVICE, source_file="s.md")
                 for i in range(4)]
        job = InsightsJob(corpus_name="c", source_dir=Path("."), units=units)
        ctx = LLMRunContext(credentials=Credentials.single("openai", KEY), provider="openai",
                            model="gpt-4.1-mini")
        with use_context(ctx), pytest.raises(StageFailureRatioError, match="4 of 4"):
            await KnowledgeClassifierStage().execute(job)
        assert job.metadata["llm_failures"]["knowledge_classifier.classify"]["failed"] == 4
    finally:
        set_default_port(None)


async def test_p1_4_concept_path_failures_count_toward_the_ratio(monkeypatch) -> None:
    from folio_insights.config import get_settings
    from folio_insights.models.knowledge_unit import KnowledgeType, KnowledgeUnit, Span
    from folio_insights.pipeline.stages.base import InsightsJob, StageFailureRatioError
    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage
    from folio_insights.services.bridge import llm_bridge

    get_settings.cache_clear()
    monkeypatch.setenv("FOLIO_INSIGHTS_REQUIRE_DETERMINISTIC_IRI", "false")

    class _Broken:
        async def structured(self, *a, **k):
            raise RuntimeError("synthetic concept failure")

    monkeypatch.setattr(llm_bridge.LLMBridge, "get_llm_for_task", lambda self, task, **k: _Broken())
    stage = FolioTaggerStage()
    monkeypatch.setattr(stage, "_get_folio_service", lambda: None)
    monkeypatch.setattr(stage, "_get_embedding_service", lambda: None)
    units = [KnowledgeUnit(text=f"A synthetic sentence about an objection rule, unit {i}.",
                           original_span=Span(start=0, end=10, source_file="s.md"),
                           unit_type=KnowledgeType.ADVICE, source_file="s.md",
                           source_section=["Synthetic"]) for i in range(3)]
    job = InsightsJob(corpus_name="c", source_dir=Path("."), units=units)
    try:
        with pytest.raises(StageFailureRatioError, match="concept"):
            await stage.execute(job)
    finally:
        get_settings.cache_clear()


# ---- P1-2: a pinned run's key never goes to another provider or host ---------------------------


async def test_p1_2_pinned_run_sends_every_task_to_its_provider(monkeypatch) -> None:
    monkeypatch.setenv("LLM_DISTILLER_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_CLASSIFIER_PROVIDER", "google")
    rec = Recorder([load_fixture("openai")["valid"]])
    ctx = LLMRunContext(credentials=Credentials.single("openai", FAKE_KEYS["openai"]),
                        provider="openai", pin_provider=True)
    with use_context(ctx):
        await make_port(rec).structured("distiller", DistilledOutput, MESSAGES)
        with pytest.raises(LLMError, match="pinned"):  # an explicit foreign route is refused
            await make_port(rec).structured("distiller", DistilledOutput, MESSAGES,
                                            route=Route("anthropic", "claude-haiku-4-5"))
    assert [r.url.host for r in rec.requests] == ["api.openai.com"]


# ---- P2-5: SDK clients (which hold the key) live only as long as the run -------------------------


async def test_p2_5_clients_are_scoped_to_the_run_and_closed() -> None:
    rec = Recorder([load_fixture("openai")["valid"]])
    port = make_port(rec)
    assert not hasattr(port, "_clients")  # no process-wide cache of keyed clients
    ctx = make_context("openai")
    with use_context(ctx):
        await port.structured("distiller", DistilledOutput, MESSAGES)
    assert len(ctx.clients) == 1
    await ctx.aclose()
    assert ctx.clients == {}
    # Without an installed context, the client is closed right after the call.
    from folio_insights.llm.context import current_context

    eph = current_context()
    assert eph.ephemeral and eph.clients == {}


# ---- P2-6 and nit: no key in logs or in the exception graph --------------------------------------


async def test_p2_6_debug_logs_never_show_the_key_or_its_tail(caplog) -> None:
    caplog.set_level(logging.DEBUG)
    for name in ("openai", "httpx", "instructor"):
        logging.getLogger(name).setLevel(logging.DEBUG)

    def echo(req):  # a provider that echoes the Authorization header back
        return httpx.Response(500, json={"error": {"message": f"echo {req.headers['authorization']}"}})

    ctx = LLMRunContext(credentials=Credentials.single("openai", KEY), provider="openai",
                        model="gpt-4.1-mini")
    with use_context(ctx), pytest.raises(LLMError) as info:
        await _port(echo, max_attempts=2).structured("distiller", Out, [{"role": "user", "content": "hi"}])
    rec = Recorder([load_fixture("openai")["auth_error"]])
    with use_context(make_context("openai")), pytest.raises(LLMAuthError):
        await make_port(rec).structured("distiller", DistilledOutput, MESSAGES)
    text = caplog.text
    assert KEY not in text and LEAK_MARKER not in text and KEY[-6:] not in text
    assert "3333" not in text  # the masked echo "sk-test-****3333" of the fixture key
    err = info.value
    assert err.__cause__ is None and err.__context__ is None
    assert KEY not in "".join(traceback.format_exception(err))


# ---- P2-9: Gemini thinking tokens ----------------------------------------------------------------


async def test_p2_9_output_tokens_include_thinking_tokens() -> None:
    rec = Recorder([{"status": 200, "body": {**load_fixture("google")["valid"]["body"],
                     "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 150}}}])
    with use_context(make_context("google")):
        _r, usage = await make_port(rec).structured("distiller", DistilledOutput, MESSAGES)
    assert (usage.input_tokens, usage.output_tokens) == (100, 50)


# ---- nits ---------------------------------------------------------------------------------------


async def test_nit_output_caps_are_per_template() -> None:
    rec = Recorder([{"status": 200, "body": {**load_fixture("openai")["valid"]["body"]}}])
    with use_context(make_context("openai")):
        try:
            await make_port(rec, max_attempts=1).structured(
                "classifier", DistilledOutput, CLASSIFY.messages(text="t", section_path="s"))
        except LLMError:
            pass
    assert json.loads(rec.requests[0].content)["max_completion_tokens"] == CLASSIFY.max_tokens == 1024


def test_nit_polysemy_refuses_unknown_model_prefixes(monkeypatch) -> None:
    from folio_insights.polysemy import detector

    def _never(*a, **k):
        raise AssertionError("no call for an unknown provider")

    monkeypatch.setattr(detector, "_structured_call", _never)

    class _Cluster:
        term = "consideration"
        shards_by_framework: dict = {}
        cross_framework_cosine_distance = {("a", "b"): 0.4}

    verdict = detector._invoke_llm_fallback(_Cluster(), llm_provider="mystery-model-7",
                                            matched_rules=["r"])
    assert verdict.decision == "uncertain" and verdict.provider == "unknown"
