"""Offline per-provider contract tests for the LLM port (Phase 10 U1, KTD9 CI tier).

For each supported provider -- Anthropic, OpenAI, Google and Ollama -- through the real openai
SDK + instructor stack with a recorded-shape response fixture:

* valid structured output validates into the Pydantic schema, against the right endpoint;
* a malformed reply is re-asked by exactly one retry layer (SDK retries are off);
* provider-reported usage is parsed (and summed across attempts);
* provider errors map to the port's error types, without leaking the key.
"""

from __future__ import annotations

import logging
import pickle
import traceback

import httpx
import pytest

from folio_insights.llm import (
    LLMAuthError,
    LLMBadRequestError,
    LLMConnectionError,
    LLMOutputError,
    LLMProviderError,
    LLMRateLimitError,
    use_context,
)
from folio_insights.llm.schemas import DistilledOutput
from folio_insights.llm.templates import DISTILL
from tests.llm.conftest import (
    FAKE_KEYS,
    LEAK_MARKER,
    PROVIDERS,
    Recorder,
    load_fixture,
    make_context,
    make_port,
)

MESSAGES = DISTILL.messages(text="Synthetic sentence about objections.", section_path="Synthetic")


async def _structured(port, provider: str):
    with use_context(make_context(provider)) as ctx:
        result, usage = await port.structured("distiller", DistilledOutput, MESSAGES)
    return result, usage, ctx


def _assert_no_leak(*texts: str) -> None:
    for text in texts:
        assert LEAK_MARKER not in text
        for key in FAKE_KEYS.values():
            assert key not in text
            assert key[-6:] not in text


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_valid_structured_output(provider: str) -> None:
    fx = load_fixture(provider)
    rec = Recorder([fx["valid"]])
    result, usage, ctx = await _structured(make_port(rec), provider)

    assert isinstance(result, DistilledOutput)
    assert result.distilled_text == "Object before the answer, not after."
    assert result.preserved_nuances == ["timing"]
    # Exactly one request, to the provider's OpenAI-compatible endpoint, with the user's key.
    assert len(rec.requests) == 1
    req = rec.requests[0]
    assert req.url.host == fx["host"]
    assert req.url.path == fx["path"]
    assert req.headers["authorization"] == f"Bearer {FAKE_KEYS[provider]}"
    body = rec.bodies()[0]
    assert body["model"] == fx["model"]
    for key in fx["body_keys"]:
        assert key in body, f"{provider} request lacks {key}"
    assert body[fx["max_tokens_param"]] == DISTILL.max_tokens  # per-template output cap
    # Template identity reached the run context.
    assert ctx.templates_used == {DISTILL.id: DISTILL.hash}


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_usage_parsed_from_provider_response(provider: str) -> None:
    fx = load_fixture(provider)
    rec = Recorder([fx["valid"]])
    _result, usage, ctx = await _structured(make_port(rec), provider)
    expected = fx["expected_usage"]
    assert usage.provider == provider
    assert usage.model == fx["model"]
    assert usage.input_tokens == expected["input_tokens"]
    assert usage.output_tokens == expected["output_tokens"]
    assert usage.cached_input_tokens == expected["cached_input_tokens"]
    assert usage.attempts == 1
    assert ctx.records[-1].usage == usage and ctx.records[-1].status == "ok"


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_malformed_reply_is_retried_by_exactly_one_layer(provider: str) -> None:
    fx = load_fixture(provider)
    rec = Recorder([fx["malformed"], fx["valid"]])
    result, usage, _ctx = await _structured(make_port(rec), provider)

    assert result.distilled_text  # the re-ask succeeded
    # One malformed reply -> one re-ask: two HTTP requests in total. Had the SDK kept its own
    # retries on top of instructor's, a transport fault would multiply; for bad output the SDK
    # cannot see the problem, so the count proves instructor re-asked exactly once.
    assert len(rec.requests) == 2
    assert usage.attempts == 2
    # Usage is billed for both attempts.
    mal = fx["malformed"]["body"]["usage"]
    good = fx["valid"]["body"]["usage"]
    assert usage.input_tokens == mal["prompt_tokens"] + good["prompt_tokens"]
    assert usage.output_tokens == mal["completion_tokens"] + good["completion_tokens"]
    # The re-ask carries the validation feedback back to the model.
    assert len(rec.bodies()[1]["messages"]) > len(rec.bodies()[0]["messages"])


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_persistently_malformed_reply_raises_output_error_with_usage(provider: str) -> None:
    fx = load_fixture(provider)
    rec = Recorder([fx["malformed"]])
    port = make_port(rec, max_attempts=3)
    with use_context(make_context(provider)) as ctx, pytest.raises(LLMOutputError) as info:
        await port.structured("distiller", DistilledOutput, MESSAGES)
    assert len(rec.requests) == 3
    err = info.value
    assert err.provider == provider
    assert err.usage is not None and err.usage.attempts == 3
    assert err.usage.input_tokens == 3 * fx["malformed"]["body"]["usage"]["prompt_tokens"]
    assert ctx.records[-1].status == "error" and ctx.records[-1].error_kind == "invalid_output"


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_server_error_is_retried_only_by_the_port(provider: str) -> None:
    fx = load_fixture(provider)
    rec = Recorder([fx["server_error"]])
    with use_context(make_context(provider)), pytest.raises(LLMProviderError) as info:
        await make_port(rec, max_attempts=3).structured("distiller", DistilledOutput, MESSAGES)
    # 3 attempts, not 3 x (1 + SDK default 2 retries) = 9.
    assert len(rec.requests) == 3
    assert info.value.status_code == fx["server_error"]["status"]
    assert info.value.retryable


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_rate_limit_then_success(provider: str) -> None:
    fx = load_fixture(provider)
    rec = Recorder([fx["rate_limit"], fx["valid"]])
    result, usage, _ctx = await _structured(make_port(rec), provider)
    assert result.distilled_text and len(rec.requests) == 2 and usage.attempts == 2


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_rate_limit_exhausted_maps_to_rate_limit_error(provider: str) -> None:
    fx = load_fixture(provider)
    rec = Recorder([fx["rate_limit"]])
    with use_context(make_context(provider)), pytest.raises(LLMRateLimitError):
        await make_port(rec, max_attempts=2).structured("distiller", DistilledOutput, MESSAGES)
    assert len(rec.requests) == 2


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_auth_error_maps_without_retry_or_key_leak(provider: str, caplog) -> None:
    fx = load_fixture(provider)
    rec = Recorder([fx["auth_error"]])
    caplog.set_level(logging.DEBUG)
    with use_context(make_context(provider)), pytest.raises(LLMAuthError) as info:
        await make_port(rec).structured("distiller", DistilledOutput, MESSAGES)
    assert len(rec.requests) == 1  # never retried
    err = info.value
    assert err.kind == "auth" and err.provider == provider and not err.retryable
    # The SDK exception (whose body can echo a masked key) is not chained.
    assert err.__cause__ is None and err.__suppress_context__
    rendered = "".join(traceback.format_exception(err))
    _assert_no_leak(str(err), repr(err), rendered, caplog.text)


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_bad_request_maps_without_retry(provider: str) -> None:
    fx = load_fixture(provider)
    rec = Recorder([fx["bad_request"]])
    with use_context(make_context(provider)), pytest.raises(LLMBadRequestError) as info:
        await make_port(rec).structured("distiller", DistilledOutput, MESSAGES)
    assert len(rec.requests) == 1
    assert info.value.status_code == fx["bad_request"]["status"]
    assert "nonexistent" in str(info.value)  # the provider's reason survives, scrubbed


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_connection_error_maps_after_port_retries(provider: str) -> None:
    rec = Recorder([httpx.ConnectError("synthetic connection refused")])
    with use_context(make_context(provider)), pytest.raises(LLMConnectionError):
        await make_port(rec, max_attempts=2).structured("distiller", DistilledOutput, MESSAGES)
    assert len(rec.requests) == 2


@pytest.mark.parametrize("provider", PROVIDERS)
async def test_free_text_completion_returns_text_and_usage(provider: str) -> None:
    from folio_insights.llm.templates import CONTRADICTION

    body = {
        "id": "synthetic", "object": "chat.completion", "created": 1, "model": "m",
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": '{"is_contradiction": false}'}}],
        "usage": {"prompt_tokens": 21, "completion_tokens": 7, "total_tokens": 28},
    }
    rec = Recorder([{"status": 200, "body": body}])
    with use_context(make_context(provider)):
        text, usage = await make_port(rec).complete(
            "contradiction", CONTRADICTION.messages(text_a="a", text_b="b", task_label="t")
        )
    assert text == '{"is_contradiction": false}'
    assert (usage.input_tokens, usage.output_tokens) == (21, 7)
    body_sent = rec.bodies()[0]
    assert "tools" not in body_sent and "response_format" not in body_sent


async def test_ollama_needs_no_key() -> None:
    from folio_insights.llm import Credentials, LLMRunContext

    fx = load_fixture("ollama")
    rec = Recorder([fx["valid"]])
    ctx = LLMRunContext(credentials=Credentials.empty(), provider="ollama", model="llama3.2")
    with use_context(ctx):
        result, _usage = await make_port(rec).structured("distiller", DistilledOutput, MESSAGES)
    assert result.distilled_text


def test_port_errors_are_picklable_and_carry_no_key() -> None:
    err = LLMAuthError("openai rejected the API key (HTTP 401)", provider="openai", status_code=401)
    assert pickle.loads(pickle.dumps(err)).args == err.args
