"""Flat extraction contracts; all source material here is synthetic."""
from __future__ import annotations

import hashlib
import json

import pytest
from pydantic import ValidationError

from folio_insights.models.knowledge_unit import (
    KnowledgeUnit,
    PropositionLink,
    SourceProvenance,
    UnresolvedCitation,
    finalize_document,
)

SOURCE = "🦉 A party must file a notice unless excused."
SNAPSHOT_ID = "synthetic-notice-v1"
RELATIONS = ["exception-to", "penalty-for", "condition-of", "cites", "contradicts"]


def old_unit() -> dict:
    return {
        "id": "rule",
        "text": "A party must file a notice unless excused.",
        "original_span": {"start": 2, "end": len(SOURCE), "source_file": "notice.txt"},
        "source_snippet": SOURCE[2:],
        "anchor_verified": True,
        "anchor_score": 1.0,
        "unit_type": "procedural_rule",
        "source_file": "notice.txt",
    }


def atomic_unit(**changes) -> KnowledgeUnit:
    data = old_unit()
    data.update(
        provenance={
            "source_snapshot_id": SNAPSHOT_ID,
            "source_sha256": hashlib.sha256(SOURCE.encode("utf-8")).hexdigest(),
            "genre": "statutes-regulations",
            "subgenre": "regulation",
        },
        proposition_kind="rule",
    )
    data.update(changes)
    return KnowledgeUnit.model_validate(data)


def finalize(units: list[KnowledgeUnit]) -> list[KnowledgeUnit]:
    return finalize_document(units, source_text=SOURCE, source_snapshot_id=SNAPSHOT_ID)


def test_old_extraction_json_reads_with_empty_new_fields_and_no_active_hierarchy():
    data = old_unit()
    data.update(parent_id="historical-parent", elaborates="historical-parent")
    unit = KnowledgeUnit.model_validate_json(json.dumps(data))
    assert unit.links == []
    assert unit.unresolved_citations == []
    assert unit.provenance is None
    assert unit.proposition_kind is None
    assert unit.anchor_verified
    assert not unit.is_grounded(SOURCE, source_snapshot_id=SNAPSHOT_ID)
    output = unit.model_dump()
    assert "parent_id" not in output
    assert "elaborates" not in output
    assert not output["links"]  # Historical hierarchy never becomes condition-of.


def test_atomic_provenance_and_flat_links_round_trip():
    unit = atomic_unit(links=[{"relation": "condition-of", "target_id": "other"}])
    loaded = KnowledgeUnit.model_validate_json(unit.model_dump_json())
    assert loaded == unit
    assert loaded.provenance.source_snapshot_id == SNAPSHOT_ID
    assert loaded.provenance.genre == "statutes-regulations"
    assert loaded.provenance.subgenre == "regulation"
    assert "parent_id" not in loaded.model_dump()


@pytest.mark.parametrize("relation", RELATIONS)
def test_all_five_relations_resolve_after_document_ids_are_known(relation):
    child = atomic_unit(id="child", links=[{"relation": relation, "target_id": "rule"}])
    rule = atomic_unit()
    assert finalize([child, rule]) == [child, rule]  # Forward reference is valid.
    assert child.links[0].relation == relation


@pytest.mark.parametrize("relation", ["elaborates", "depends_on", "unknown"])
def test_unknown_relations_are_rejected(relation):
    with pytest.raises(ValidationError):
        PropositionLink(relation=relation, target_id="rule")


def test_dangling_target_is_rejected_only_at_document_finalization():
    unit = atomic_unit(links=[{"relation": "exception-to", "target_id": "missing"}])
    with pytest.raises(ValueError, match="missing link target"):
        finalize([unit])


@pytest.mark.parametrize("target_id", ["", "https://example.test/proposition", "urn:shard:1"])
def test_links_accept_only_local_ids(target_id):
    with pytest.raises(ValidationError):
        PropositionLink(relation="cites", target_id=target_id)


def test_duplicate_ids_and_self_links_are_rejected_at_finalization():
    with pytest.raises(ValueError, match="duplicate proposition ID"):
        finalize([atomic_unit(), atomic_unit()])
    with pytest.raises(ValueError, match="self link"):
        finalize([atomic_unit(links=[{"relation": "cites", "target_id": "rule"}])])


@pytest.mark.parametrize("relation", ["cites", "contradicts"])
def test_reciprocal_links_are_not_logical_dependencies(relation):
    first = atomic_unit(id="first", links=[{"relation": relation, "target_id": "second"}])
    second = atomic_unit(id="second", links=[{"relation": relation, "target_id": "first"}])
    assert finalize([first, second]) == [first, second]


def test_external_citation_stays_explicitly_unresolved_without_an_invented_target():
    unit = atomic_unit(unresolved_citations=[{"citation": "Synthetic Rule 12"}])
    assert finalize([unit]) == [unit]
    assert unit.links == []
    assert unit.model_dump()["unresolved_citations"] == [
        {"relation": "cites", "citation": "Synthetic Rule 12"},
    ]
    with pytest.raises(ValidationError):
        UnresolvedCitation(citation="Synthetic Rule 12", target_id="invented")


def test_grounding_allows_atomic_paraphrases_on_the_same_exact_unicode_span():
    rule = atomic_unit(text="A notice is required.")
    exception = atomic_unit(id="exception", text="Excused parties need not file.",
                            proposition_kind="exception")
    assert rule.is_grounded(SOURCE, source_snapshot_id=SNAPSHOT_ID)
    assert finalize([rule, exception]) == [rule, exception]


@pytest.mark.parametrize("mismatch", [
    "hash", "snapshot", "start", "negative", "end", "empty", "snippet", "file", "missing",
])
def test_hash_offset_or_snippet_mismatch_cannot_be_labelled_grounded(mismatch):
    data = atomic_unit().model_dump()
    if mismatch == "hash":
        data["provenance"]["source_sha256"] = "0" * 64
    elif mismatch == "snapshot":
        data["provenance"]["source_snapshot_id"] = "other-snapshot"
    elif mismatch == "start":
        data["original_span"]["start"] = 3
    elif mismatch == "negative":
        data["original_span"]["start"] = -1
    elif mismatch == "end":
        data["original_span"]["end"] += 1
    elif mismatch == "empty":
        data["original_span"]["end"] = data["original_span"]["start"]
        data["source_snippet"] = ""
    elif mismatch == "snippet":
        data["source_snippet"] = "Invented supporting material."
    elif mismatch == "file":
        data["original_span"]["source_file"] = "other.txt"
    else:
        data["provenance"] = None
    unit = KnowledgeUnit.model_validate(data)
    assert unit.anchor_verified  # The legacy flag is not proof against a snapshot.
    assert not unit.is_grounded(SOURCE, source_snapshot_id=SNAPSHOT_ID)
    with pytest.raises(ValueError, match="not grounded"):
        finalize([unit])


@pytest.mark.parametrize("genre", ["opinions", "statutes-regulations", "briefs", "know-how"])
def test_source_provenance_supports_each_planned_genre(genre):
    data = atomic_unit().provenance.model_dump()
    data["genre"] = genre
    assert SourceProvenance.model_validate(data).genre == genre


def test_source_provenance_rejects_malformed_digest():
    data = atomic_unit().provenance.model_dump()
    data["source_sha256"] = "not-a-digest"
    with pytest.raises(ValidationError):
        SourceProvenance.model_validate(data)
