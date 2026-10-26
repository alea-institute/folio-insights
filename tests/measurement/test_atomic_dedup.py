"""Occurrence deduplication over synthetic atomic extraction output."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from folio_insights.config import Settings
from folio_insights.models.knowledge_unit import (
    KnowledgeUnit,
    PropositionLink,
    UnresolvedCitation,
    finalize_document,
)
from folio_insights.pipeline.orchestrator import PipelineOrchestrator
from folio_insights.pipeline.stages.base import InsightsJob
from folio_insights.pipeline.stages.deduplicator import DeduplicatorStage

SOURCE = (
    "A plaintiff must prove formation, performance, and breach of a contract."
)


def atomic_unit(unit_id: str, *, source: str = SOURCE, source_file: str = "contract.txt",
                start: int = 0, end: int | None = None, **changes) -> KnowledgeUnit:
    end = len(source) if end is None else end
    data = {
        "id": unit_id,
        "text": source[start:end],
        "original_span": {"start": start, "end": end, "source_file": source_file},
        "source_file": source_file,
        "source_snippet": source[start:end],
        "provenance": {
            "source_snapshot_id": source_file,
            "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "genre": "opinions",
        },
        "proposition_kind": "rule",
        "unit_type": "procedural_rule",
        "confidence": 0.8,
    }
    data.update(changes)
    data["content_hash"] = hashlib.sha256(data["text"].encode("utf-8")).hexdigest()
    return KnowledgeUnit.model_validate(data)


@pytest.fixture
def similar_embeddings(monkeypatch):
    # Every pair exceeds the legacy near-removal threshold, without loading a model.
    monkeypatch.setattr(DeduplicatorStage, "_encode_units",
                        lambda self, units: np.ones((len(units), 1)))


async def dedup(units: list[KnowledgeUnit]) -> list[KnowledgeUnit]:
    job = InsightsJob(corpus_name="atomic", source_dir="/tmp/synthetic", units=units)
    return (await DeduplicatorStage().execute(job)).units


async def test_equal_text_occurrences_survive_full_pipeline(tmp_path, monkeypatch,
                                                            similar_embeddings):
    """Run all seven stages and persisted output, with offline extraction/tagging fakes.

    U38 owns atomic splitting/grounding; its fake supplies exact repeated offsets here.
    Ingestion, structure, boundaries, dedup, checkpoints and output writing stay real.
    """
    from folio_insights.pipeline.stages.distiller import DistillerStage
    from folio_insights.pipeline.stages.folio_tagger import FolioTaggerStage
    from folio_insights.pipeline.stages.knowledge_classifier import KnowledgeClassifierStage
    from folio_insights.services.bridge.ingestion_bridge import IngestionBridge

    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "first.txt").write_text(SOURCE + "\n\n" + SOURCE)
    (sources / "second.txt").write_text(SOURCE)
    monkeypatch.setattr(IngestionBridge, "__init__", lambda self: None)
    monkeypatch.setattr(IngestionBridge, "detect_and_ingest",
                        lambda self, path: (path.read_text(), []))

    async def extract_atomic(self, job):
        assert len(job.units) == 3  # The preceding real boundaries found both documents.
        job.units = []
        for source_file, ingested in job.metadata["ingested"].items():
            source = ingested["text"]
            for index, start in enumerate(range(0, len(source), len(SOURCE) + 2)):
                job.units.append(atomic_unit(
                    f"{Path(source_file).stem}-{index}", source=source,
                    source_file=source_file, start=start, end=start + len(SOURCE),
                ))
        return job

    async def offline_tags(self, job):
        return job

    monkeypatch.setattr(DistillerStage, "execute", extract_atomic)
    monkeypatch.setattr(KnowledgeClassifierStage, "execute", offline_tags)
    monkeypatch.setattr(FolioTaggerStage, "execute", offline_tags)
    monkeypatch.setattr(PipelineOrchestrator, "_run_b5_canary", lambda self: None)
    settings = Settings(_env_file=None, output_dir=tmp_path / "output")
    result = await PipelineOrchestrator(settings).run(sources, "atomic", resume=False)

    assert len(result.units) == 3
    assert len({(u.source_file, u.original_span.start) for u in result.units}) == 3
    for unit in result.units:
        source = result.metadata["ingested"][unit.source_file]["text"]
        assert unit.is_grounded(source, source_snapshot_id=unit.source_file)
    saved = json.loads((settings.output_dir / "atomic" / "extraction.json").read_text())
    assert {u["id"] for u in saved["units"]} == {u.id for u in result.units}
    assert saved["total_units"] == 3


async def test_similar_contract_elements_preserve_rule_and_three_conditions(similar_embeddings):
    rule = atomic_unit("rule")
    elements = [atomic_unit(
        element, text=f"The plaintiff must prove {element} of the contract.",
        proposition_kind="element", links=[{"relation": "condition-of", "target_id": "rule"}],
    ) for element in ("formation", "performance", "breach")]
    result = await dedup([rule, *elements])
    assert [u.id for u in result] == ["rule", "formation", "performance", "breach"]
    assert len(finalize_document(result, source_text=SOURCE,
                                 source_snapshot_id="contract.txt")) == 4
    assert all(u.links == [PropositionLink(relation="condition-of", target_id="rule")]
               for u in result[1:])
    diagnostics = [e for u in result for e in u.lineage if e.action == "similar"]
    assert diagnostics
    assert all(e.stage == "deduplicator" for e in diagnostics)
    assert not any(e.action == "merge" for u in result for e in u.lineage)


@pytest.mark.parametrize("relation", [
    "exception-to", "penalty-for", "condition-of", "cites", "contradicts",
])
async def test_duplicate_alias_links_follow_survivor_and_keep_outbound_links(
    relation, similar_embeddings,
):
    duplicate = atomic_unit("alias", confidence=0.5,
                            links=[{"relation": "cites", "target_id": "other"}],
                            unresolved_citations=[
                                {"citation": "Synthetic external authority"},
                                {"citation": "Synthetic second authority"},
                            ])
    survivor = atomic_unit("survivor", confidence=0.9,
                           unresolved_citations=[{"citation": "Synthetic external authority"}])
    other = atomic_unit("other", text="A separate supported atomic claim.", links=[
        {"relation": relation, "target_id": "alias"},
        {"relation": relation, "target_id": "survivor"},
    ])
    result = await dedup([duplicate, survivor, other])
    assert [u.id for u in result] == ["survivor", "other"]
    assert survivor.cross_references == ["alias"]
    assert survivor.links == [PropositionLink(relation="cites", target_id="other")]
    assert survivor.unresolved_citations == [
        UnresolvedCitation(citation="Synthetic external authority"),
        UnresolvedCitation(citation="Synthetic second authority"),
    ]
    assert other.links == [PropositionLink(relation=relation, target_id="survivor")]
    assert len(finalize_document(result, source_text=SOURCE,
                                 source_snapshot_id="contract.txt")) == 2
    assert sum(e.action == "merge" for e in survivor.lineage) == 1
    assert [u.id for u in await dedup(result)] == ["survivor", "other"]
    assert sum(e.action == "merge" for e in survivor.lineage) == 1


async def test_alias_remapping_is_document_scoped(similar_embeddings):
    first = atomic_unit("alias", confidence=0.5)
    survivor = atomic_unit("survivor", confidence=0.9)
    second = atomic_unit("alias", source_file="second.txt")
    second_child = atomic_unit("child", source_file="second.txt", text="An element.",
                               links=[{"relation": "condition-of", "target_id": "alias"}])
    result = await dedup([first, survivor, second, second_child])
    assert len(result) == 3
    assert second_child.links[0].target_id == "alias"
    assert len(finalize_document([u for u in result if u.source_file == "second.txt"],
                                 source_text=SOURCE, source_snapshot_id="second.txt")) == 2


async def test_coalescing_duplicate_links_cannot_leave_self_link(similar_embeddings):
    duplicate = atomic_unit("alias", confidence=0.5)
    survivor = atomic_unit("survivor", confidence=0.9,
                           links=[{"relation": "cites", "target_id": "alias"}])
    result = await dedup([duplicate, survivor])
    assert result == [survivor]
    assert survivor.links == []
    assert finalize_document(result, source_text=SOURCE,
                             source_snapshot_id="contract.txt") == result


async def test_nfc_statement_identity_ignores_content_hash(monkeypatch):
    monkeypatch.setattr(DeduplicatorStage, "_encode_units",
                        lambda self, units: np.eye(len(units)))
    first = atomic_unit("first", text="A café must give notice.")
    duplicate = atomic_unit("duplicate", text="A cafe\u0301 must give notice.")
    assert first.content_hash != duplicate.content_hash
    assert [u.id for u in await dedup([first, duplicate])] == ["first"]


@pytest.mark.parametrize("change", ["digest", "snapshot", "offset", "statement"])
async def test_occurrence_identity_uses_snapshot_offsets_and_statement(change, similar_embeddings):
    first = atomic_unit("first")
    second = atomic_unit("second")
    if change == "digest":
        second.provenance = second.provenance.model_copy(update={"source_sha256": "0" * 64})
    elif change == "snapshot":
        second.provenance = second.provenance.model_copy(update={"source_snapshot_id": "v2"})
    elif change == "offset":
        second.original_span.start += 1
    else:
        second.text += " "  # NFC does not trim statements.
    assert len(await dedup([first, second])) == 2


async def test_legacy_read_behavior_is_separate_from_atomic_occurrences(similar_embeddings):
    atomic = atomic_unit("atomic")
    legacy = KnowledgeUnit.model_validate({
        **atomic.model_dump(), "id": "legacy", "provenance": None,
        "proposition_kind": None, "parent_id": "retired-parent",
    })
    duplicate = legacy.model_copy(update={"id": "legacy-duplicate"}, deep=True)
    result = await dedup([atomic, legacy, duplicate])
    assert [u.id for u in result] == ["atomic", "legacy"]
    assert "parent_id" not in legacy.model_dump()
    assert legacy.links == []
