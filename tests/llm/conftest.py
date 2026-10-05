"""Shared offline harness for the LLM port contract tests (KTD9, CI tier).

Every request goes through an ``httpx.MockTransport`` injected into the openai SDK client, so the
tests exercise the real SDK + instructor stack with recorded-shape responses and no network.

Fake keys all carry the marker ``FAKEKEY`` so a grep of captured output proves none leaked.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from folio_insights.llm import Credentials, LLMPort, LLMRunContext

FIXTURES = Path(__file__).parent / "fixtures"
PROVIDERS = ("openai", "anthropic", "google", "ollama")
LEAK_MARKER = "FAKEKEY"

FAKE_KEYS: dict[str, str] = {
    "openai": "sk-test-FAKEKEY-openai-0000111122223333",
    "anthropic": "sk-ant-test-FAKEKEY-anthropic-4444555566667777",
    "google": "AIzaTestFAKEKEYgoogle88889999aaaabbbb",
    "ollama": "ollama-test-FAKEKEY-ccccddddeeeeffff",
}


def load_fixture(provider: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{provider}.json").read_text(encoding="utf-8"))


class Recorder:
    """A scripted MockTransport: replays responses in order and records every request."""

    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        step = self.script[min(len(self.requests), len(self.script)) - 1]
        if isinstance(step, Exception):
            raise step
        if callable(step):
            return step(request)
        return httpx.Response(step["status"], json=step["body"])

    def factory(self) -> Callable[[Any], httpx.AsyncClient]:
        return lambda _spec: httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests]


def make_port(recorder: Recorder, **kwargs: Any) -> LLMPort:
    kwargs.setdefault("retry_wait_seconds", 0)
    kwargs.setdefault("max_attempts", 3)
    return LLMPort(http_client_factory=recorder.factory(), **kwargs)


def make_context(provider: str, model: str | None = None, **kwargs: Any) -> LLMRunContext:
    return LLMRunContext(
        credentials=Credentials.single(provider, FAKE_KEYS[provider]),
        provider=provider,
        model=model or load_fixture(provider)["model"],
        **kwargs,
    )


@pytest.fixture(autouse=True)
def _no_task_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """Per-task env overrides from the developer's shell must not steer contract tests."""
    import os

    for name in list(os.environ):
        if name.startswith("LLM_") and (name.endswith("_PROVIDER") or name.endswith("_MODEL")):
            monkeypatch.delenv(name, raising=False)
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY",
                 "OLLAMA_API_KEY"):
        monkeypatch.delenv(name, raising=False)
