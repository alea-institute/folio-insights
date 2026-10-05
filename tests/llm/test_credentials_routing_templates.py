"""BYOK credential handles, task routing and template identity (Phase 10 U1)."""

from __future__ import annotations

import copy
import json
import logging
import pickle
from types import SimpleNamespace

import pytest

from folio_insights.llm import (
    Credentials,
    LLMRunContext,
    MissingCredentialsError,
    Route,
    SecretKey,
    TaskLLM,
    UnknownProviderError,
    resolve_route,
    use_context,
)
from folio_insights.llm.credentials import scrub
from folio_insights.llm.schemas import DistilledOutput
from folio_insights.llm.templates import (
    DISTILL,
    PromptTemplate,
    all_templates,
    combined_prompt_hash,
    register,
    template_for_task,
)
from tests.llm.conftest import FAKE_KEYS, LEAK_MARKER, Recorder, load_fixture, make_port

SETTINGS = SimpleNamespace(llm_provider="google", llm_model="gemini-2.5-flash-lite")

# ---- SecretKey / Credentials -------------------------------------------------------------------


def test_secret_key_is_redacted_in_every_textual_form() -> None:
    key = SecretKey(FAKE_KEYS["openai"])
    for text in (repr(key), str(key), f"{key}", f"{key!r}", "%s" % key, repr([key]),
                 repr(Credentials.single("openai", key))):
        assert LEAK_MARKER not in text
    assert key.reveal() == FAKE_KEYS["openai"]


def test_secret_key_refuses_serialization() -> None:
    key = SecretKey(FAKE_KEYS["anthropic"])
    creds = Credentials.single("anthropic", key)
    for obj in (key, creds):
        with pytest.raises(TypeError):
            pickle.dumps(obj)
        with pytest.raises(TypeError):
            json.dumps(obj)
    assert copy.deepcopy(key) is key  # copies never duplicate the value
    with pytest.raises(AttributeError):
        key._value = "x"  # type: ignore[misc]


def test_secret_key_equality_is_identity_only() -> None:
    a, b = SecretKey(FAKE_KEYS["google"]), SecretKey(FAKE_KEYS["google"])
    assert a == a and a != b


def test_credentials_from_env_reads_only_provider_key_vars() -> None:
    env = {"OPENAI_API_KEY": FAKE_KEYS["openai"], "GEMINI_API_KEY": FAKE_KEYS["google"],
           "UNRELATED_SECRET": "nope"}
    creds = Credentials.from_env(env)
    assert creds.providers() == ["google", "openai"]
    assert creds.get("openai").reveal() == FAKE_KEYS["openai"]
    assert creds.get("anthropic") is None


def test_missing_credentials_names_provider_never_a_value() -> None:
    with pytest.raises(MissingCredentialsError) as info:
        Credentials.empty().require("anthropic")
    assert "anthropic" in str(info.value) and "ANTHROPIC_API_KEY" in str(info.value)
    assert Credentials.empty().require("ollama", requires_key=False) is None


def test_scrub_removes_keys_fragments_and_masked_echoes() -> None:
    key = SecretKey(FAKE_KEYS["openai"])
    text = (f"bad key {FAKE_KEYS['openai']} / Incorrect API key provided: sk-test-****3333 "
            f"/ suffix {FAKE_KEYS['openai'][-6:]}")
    cleaned = scrub(text, [key])
    assert LEAK_MARKER not in cleaned and "3333" not in cleaned
    assert FAKE_KEYS["openai"][-6:] not in cleaned


async def test_keyless_context_refuses_before_any_request() -> None:
    """No credentials installed -> MissingCredentialsError, zero HTTP requests (R2)."""
    rec = Recorder([load_fixture("openai")["valid"]])
    ctx = LLMRunContext(provider="openai")
    with use_context(ctx), pytest.raises(MissingCredentialsError):
        await make_port(rec).structured("distiller", DistilledOutput, DISTILL.messages(
            text="x", section_path="y"))
    assert rec.requests == []
    # The halt sticks: later calls in the same run fail fast without the network either.
    with use_context(ctx), pytest.raises(MissingCredentialsError):
        await make_port(rec).structured("distiller", DistilledOutput, DISTILL.messages(
            text="x", section_path="y"))
    assert rec.requests == [] and ctx.halted is not None


def test_port_never_reads_ambient_env_keys(monkeypatch) -> None:
    """An API key in the server environment is ignored unless a caller hands it in."""
    import asyncio

    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEYS["openai"])
    rec = Recorder([load_fixture("openai")["valid"]])
    with use_context(LLMRunContext(provider="openai")), pytest.raises(MissingCredentialsError):
        asyncio.run(make_port(rec).structured(
            "distiller", DistilledOutput, DISTILL.messages(text="x", section_path="y")))
    assert rec.requests == []


async def test_no_key_in_logs_across_a_successful_call(caplog) -> None:
    caplog.set_level(logging.DEBUG)
    rec = Recorder([load_fixture("anthropic")["valid"]])
    ctx = LLMRunContext(credentials=Credentials.single("anthropic", FAKE_KEYS["anthropic"]),
                        provider="anthropic")
    with use_context(ctx):
        await make_port(rec).structured("distiller", DistilledOutput, DISTILL.messages(
            text="x", section_path="y"))
    assert LEAK_MARKER not in caplog.text
    assert LEAK_MARKER not in json.dumps(ctx.usage_summary())
    assert LEAK_MARKER not in repr(ctx.records)


# ---- routing -----------------------------------------------------------------------------------

TASKS = ("boundary", "classifier", "distiller", "novelty", "concept", "branch_judge",
         "task_discovery", "task_ordering", "contradiction", "polysemy_fallback")


@pytest.mark.parametrize("task", TASKS)
def test_run_wide_flags_reach_every_task(task: str) -> None:
    ctx = LLMRunContext(provider="anthropic", model="claude-sonnet-4-5")
    assert resolve_route(task, context=ctx, settings=SETTINGS, environ={}) == Route(
        "anthropic", "claude-sonnet-4-5")


@pytest.mark.parametrize("task", TASKS)
def test_per_task_env_override_wins_over_flags(task: str) -> None:
    ctx = LLMRunContext(provider="anthropic", model="claude-sonnet-4-5")
    env = {f"LLM_{task.upper()}_PROVIDER": "openai", f"LLM_{task.upper()}_MODEL": "gpt-4.1"}
    assert resolve_route(task, context=ctx, settings=SETTINGS, environ=env) == Route(
        "openai", "gpt-4.1")
    # Other tasks still follow the flags.
    other = "distiller" if task != "distiller" else "classifier"
    assert resolve_route(other, context=ctx, settings=SETTINGS, environ=env).provider == "anthropic"


def test_settings_are_the_fallback() -> None:
    assert resolve_route("distiller", context=LLMRunContext(), settings=SETTINGS, environ={}) == Route(
        "google", "gemini-2.5-flash-lite")


def test_model_never_crosses_providers() -> None:
    ctx = LLMRunContext()
    env = {"LLM_DISTILLER_PROVIDER": "anthropic"}  # provider only: settings' Gemini model must not follow
    assert resolve_route("distiller", context=ctx, settings=SETTINGS, environ=env) == Route(
        "anthropic", "claude-haiku-4-5")
    # A model-only flag applies to the provider it inherits.
    ctx = LLMRunContext(model="gemini-2.5-pro")
    assert resolve_route("distiller", context=ctx, settings=SETTINGS, environ={}) == Route(
        "google", "gemini-2.5-pro")
    # A model-only per-task override applies to the flag's provider.
    ctx = LLMRunContext(provider="openai")
    env = {"LLM_CONCEPT_MODEL": "gpt-4.1-nano"}
    assert resolve_route("concept", context=ctx, settings=SETTINGS, environ=env) == Route(
        "openai", "gpt-4.1-nano")


def test_provider_aliases_and_unknown_provider() -> None:
    assert resolve_route("distiller", context=LLMRunContext(provider="gemini"), settings=SETTINGS,
                         environ={}).provider == "google"
    with pytest.raises(UnknownProviderError):
        resolve_route("distiller", context=LLMRunContext(provider="nonesuch"), settings=SETTINGS,
                      environ={})


async def test_task_llm_routes_through_the_port_with_the_task_template() -> None:
    rec = Recorder([load_fixture("google")["valid"]])
    ctx = LLMRunContext(credentials=Credentials.single("google", FAKE_KEYS["google"]),
                        provider="google")
    llm = TaskLLM("distiller", port=make_port(rec))
    with use_context(ctx):
        out = await llm.structured("rendered prompt", schema={"type": "object"}, temperature=0)
    assert out["distilled_text"]  # legacy dict schema -> the template's validated model
    assert rec.bodies()[0]["messages"][-1]["content"] == "rendered prompt"
    assert ctx.templates_used == {DISTILL.id: DISTILL.hash}


# ---- templates -----------------------------------------------------------------------------------


def test_template_hash_is_stable_and_independent_of_unit_text() -> None:
    again = PromptTemplate(id=DISTILL.id, version=DISTILL.version, task=DISTILL.task,
                           user=DISTILL.user, output_schema=DISTILL.output_schema)
    assert again.hash == DISTILL.hash
    assert DISTILL.render(text="one", section_path="a") != DISTILL.render(text="two", section_path="b")
    assert len(DISTILL.hash) == 64


@pytest.mark.parametrize("change", [
    {"version": "2"},
    {"user": "Different prompt {text} {section_path}"},
    {"system": "You are terse."},
    {"output_schema": None},
])
def test_template_hash_changes_when_the_template_changes(change: dict) -> None:
    fields = {"id": DISTILL.id, "version": DISTILL.version, "task": DISTILL.task,
              "user": DISTILL.user, "output_schema": DISTILL.output_schema}
    fields.update(change)
    assert PromptTemplate(**fields).hash != DISTILL.hash


def test_registry_rejects_silent_redefinition() -> None:
    with pytest.raises(ValueError):
        register(PromptTemplate(id=DISTILL.id, version=DISTILL.version, task="distiller",
                                user="edited without a version bump"))


def test_every_routed_task_has_a_template() -> None:
    for task in TASKS:
        assert template_for_task(task).task == task
    ids = [t.id for t in all_templates()]
    assert len(ids) == len(set(ids))


def test_combined_prompt_hash_is_order_independent() -> None:
    hashes = [t.hash for t in all_templates()[:3]]
    assert combined_prompt_hash(hashes) == combined_prompt_hash(list(reversed(hashes)))
    assert combined_prompt_hash(hashes) != combined_prompt_hash(hashes[:2])
