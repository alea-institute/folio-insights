"""Formal consistency cannot stand in for an unexecuted textual screen."""
from types import SimpleNamespace

import pytest

from folio_insights.bench.corpus04 import cluster_validation
from folio_insights.models.framework import FrameworkRegistry
from folio_insights.validation import validator
from folio_insights.validation.coverage import TaskNode
from tests.validation.conftest import FakeNli, FakeReasoner, folio, type_triple, vshard


@pytest.fixture
def corpus_inputs(monkeypatch):
    rows = [vshard(
        number, source_uri="urn:x:benchmark", reference=folio("Synthetic"),
        speech_act="holding", triple=type_triple("urn:x:entity", "urn:x:Class"), sense=text,
    ) for number, text in [
        (1, "The synthetic rule is applicable."),
        (2, "The synthetic rule is not applicable."),
    ]]

    async def load_inputs(ctx):
        return rows, FrameworkRegistry.with_defaults()

    monkeypatch.setattr(validator, "load_corpus_inputs", load_inputs)
    return SimpleNamespace(corpus="benchmark"), [TaskNode("task", "Synthetic", folio("Synthetic"))]


async def test_executed_text_screen_finds_contradiction_despite_consistent_axioms(corpus_inputs):
    ctx, tasks = corpus_inputs
    result = await cluster_validation(ctx, tasks=tasks, reasoner=FakeReasoner(), nli=FakeNli())
    assert result["status"] == "fail"
    assert result["by_kind"] == {"contradiction": 1}
    assert result["cluster_modes"] == {"formal+textual": result["clusters"]}


@pytest.mark.parametrize("disabled", [False, True])
async def test_capped_or_disabled_text_screen_is_incomplete(corpus_inputs, disabled):
    ctx, tasks = corpus_inputs
    result = await cluster_validation(
        ctx, tasks=tasks, reasoner=FakeReasoner(), nli=None if disabled else FakeNli(),
        max_nli_pairs=0,
    )
    assert result["status"] == "incomplete", result
    assert result["cluster_modes"] == {"formal": result["clusters"]}
    assert result["nli_checked_clusters"] == 0
    assert "nli_not_run_for_all_clusters" in result["reasons"]
