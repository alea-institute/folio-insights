"""Subprocess-only harness: run the REAL extraction handler over synthetic stages.

Importing this module (only ever inside a child process started by a test) patches
``PipelineOrchestrator._build_stages`` to :func:`tests.jobs.fake_stages.fake_stages` and points
the LLM port at a recorded Gemini-compatible transport that accepts only ``$FAKE_LLM_KEY``. The
real ``api.services.pipeline_runner.run_extraction_job`` handler, the real orchestrator
checkpoint/resume path, the real queue and the real worker then run unchanged.
"""

from __future__ import annotations

import json
import os

import httpx

from folio_insights.pipeline.orchestrator import PipelineOrchestrator
from tests.jobs.fake_stages import _log, fake_stages

_VALID = {
    "id": "synthetic", "object": "chat.completion", "created": 1, "model": "gemini-2.5-flash-lite",
    "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
        "role": "assistant", "content": None, "tool_calls": [{
            "id": "call_0", "type": "function", "function": {
                "name": "DistilledOutput",
                "arguments": json.dumps({"distilled_text": "Synthetic distilled insight."})}}]}}],
    "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
}


def _patched_build_stages(self):  # noqa: ANN001 - patched onto PipelineOrchestrator
    return fake_stages()


PipelineOrchestrator._build_stages = _patched_build_stages  # type: ignore[method-assign]


def install_recorded_provider() -> None:
    """Route the port to a recorded Gemini-compatible transport that checks the key."""
    from folio_insights.llm import LLMPort, set_default_port

    expected = os.environ.get("FAKE_LLM_KEY", "")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("authorization") != f"Bearer {expected}":
            return httpx.Response(400, json=[{"error": {"code": 400,
                                                        "message": "API key not valid."}}])
        _log("provider:auth_ok")
        return httpx.Response(200, json=_VALID)

    set_default_port(LLMPort(
        http_client_factory=lambda _spec: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        retry_wait_seconds=0,
    ))


install_recorded_provider()

from api.services.pipeline_runner import run_extraction_job  # noqa: E402

HANDLERS = {"extract": run_extraction_job}
