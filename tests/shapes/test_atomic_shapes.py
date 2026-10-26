"""U35: opt-in atomic records share the local/full SHACL contract."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest
from rdflib import Graph

from folio_insights.shapes import pyshacl_adapter
from folio_insights.shapes.fields import FI
from folio_insights.shapes.pydantic_to_shacl import GENERATED_PATH, check_generated
from folio_insights.shapes.rendering import ValidationGraph, render_shard
from folio_insights.shapes.suite import SUITE_PATHS, default_suite
from folio_insights.shards import load_shard_record
from tests.shards.conftest import _SUBTYPE_TABLE, _sample_shard
from tests.shards.test_atomic_records import _atomic


def atomic_record(**updates):
    data = _atomic().model_dump(mode="json")
    data["folio_tags"] = [
        dict(iri="https://example.org/Duty", label="Duty", confidence=0.99,
             branch="Deontic Specification", extraction_path="entity_ruler"),
        dict(iri="https://example.org/Contract", label="Contract Law", confidence=0.95,
             branch="Area of Law", extraction_path="semantic", judge_status="judged"),
    ]
    data["links"] = [
        dict(relation=relation, target_iri="urn:folio:shard/" + "b" * 32)
        for relation in ("exception-to", "penalty-for", "condition-of", "cites", "contradicts")
    ] + [dict(relation="cites", citation="Example v. State, 1 U.S. 2")]
    data.update(updates)
    return data


def test_multi_tag_atomic_record_passes_local_and_full_shacl():
    data = atomic_record()
    load_shard_record(data, target_schema_version=3)
    assert default_suite().validate_shard(data).conforms
    graph, _ = render_shard(data)
    node = ("I", data["shard_iri"])
    tags = graph.values(node, FI + "folioTags")
    assert len(tags) == 2
    assert {graph.values(t, FI + "branch")[0][1] for t in tags} == {
        "Deontic Specification", "Area of Law",
    }
    links = graph.values(node, FI + "links")
    assert len(links) == 6
    assert {graph.values(link, FI + "relation")[0][1] for link in links} == {
        "exception-to", "penalty-for", "condition-of", "cites", "contradicts",
    }
    report = pyshacl_adapter.validate(graph, SUITE_PATHS, local_only=False)
    assert report.conforms, report.text


@pytest.mark.parametrize("tag,cls", _SUBTYPE_TABLE)
def test_legacy_views_keep_subtype_invariants_and_archive_hierarchy(tag, cls):
    view = load_shard_record(
        _sample_shard(cls, elaborates=["urn:folio:shard/" + "b" * 32]).model_dump(mode="json"),
        target_schema_version=3,
    ).shard
    graph, node = render_shard(view)
    assert default_suite().validate_graph(graph).conforms
    assert pyshacl_adapter.validate(graph, SUITE_PATHS).conforms
    assert not graph.values(node, "https://folio-insights.aleainstitute.ai/vocab/elaborates")
    history, = graph.values(node, FI + "legacyHierarchy")
    assert graph.values(history, FI + "historicalElaborates")[0][1] == "urn:folio:shard/" + "b" * 32
    if tag == "disputed_proposition":
        data = view.model_dump(mode="json")
        data["epistemic_status"] = "demonstrable"
        assert not default_suite().validate_shard(data).conforms
        assert not pyshacl_adapter.validate(render_shard(data)[0], SUITE_PATHS).conforms


def invalid_record(case):
    data = atomic_record()
    if case == "branch":
        data["folio_tags"][0]["branch"] = 3
    elif case == "tag":
        data["folio_tags"][0]["confidence"] = 1.1
    elif case == "tag_extra":
        data["folio_tags"][0]["unrecognized"] = "bad"
    elif case == "relation":
        data["links"][0]["relation"] = "elaborates"
    elif case == "endpoint":
        data["links"] = [dict(relation="contradicts", citation="unresolved")]
    elif case == "empty_target":
        data["links"] = [dict(relation="cites", target_iri="")]
    elif case == "link_extra":
        data["links"][0]["depends_on_shards"] = ["urn:other"]
    elif case == "recipe":
        data["identity_recipe"] = "future-v99"
    elif case == "key":
        data["proposition_key"] = "invalid"
    elif case == "missing_basis":
        data["atomic_identity"] = None
    elif case == "legacy_key":
        data["identity_recipe"] = "legacy-v1"
    elif case == "digest":
        data["atomic_identity"]["source_snapshot_digest"] = "invalid"
    elif case == "negative_offset":
        data["atomic_identity"]["start"] = -1
    elif case == "end_offset":
        data["atomic_identity"]["end"] = 0
    elif case == "schema":
        data["schema_version"] = 99
    elif case == "active_hierarchy":
        data["elaborates"] = ["urn:other"]
    return data


INVALID = (
    "branch", "tag", "tag_extra", "relation", "endpoint", "empty_target", "link_extra",
    "recipe", "key", "missing_basis", "legacy_key", "digest", "negative_offset",
    "end_offset", "schema", "active_hierarchy",
)


@pytest.mark.parametrize("case", INVALID)
def test_invalid_atomic_fields_fail_both_engines(case):
    data = invalid_record(case)
    local = default_suite().validate_shard(data)
    assert not local.conforms, case
    reference = pyshacl_adapter.validate(render_shard(data)[0], SUITE_PATHS)
    assert not reference.conforms, reference.text
    assert any(r.severity == "Violation" for r in local.results)


@pytest.mark.parametrize("case", ("branch", "tag", "relation"))
async def test_invalid_fields_refused_by_preappend_gate(tmp_path, case):
    from folio_insights.storage import ShaclViolation
    from tests.storage.conftest import open_ctx

    ctx = await open_ctx(tmp_path / "storage")
    try:
        head = (await ctx.status()).journal_head
        # U37 owns schema-3 ingestion. Exercise the existing preappend SHACL
        # boundary directly without activating that storage migration here.
        with pytest.raises(ShaclViolation):
            ctx._check_shacl(json.dumps(invalid_record(case)).encode())
        assert (await ctx.status()).journal_head == head
    finally:
        await ctx.close()


def test_reciprocal_contradictions_are_not_dependencies():
    from folio_insights.revision.dependency_graph import DependencyGraph

    a = atomic_record()
    b = load_shard_record(
        _sample_shard(shard_iri="urn:folio:shard/" + "b" * 32).model_dump(mode="json"),
        target_schema_version=3,
    ).shard.model_dump(mode="json")
    a["links"] = [dict(relation="contradicts", target_iri=b["shard_iri"])]
    b["links"] = [dict(relation="contradicts", target_iri=a["shard_iri"])]
    graph = ValidationGraph()
    for data in (a, b):
        render_shard(data, graph=graph)
    assert default_suite().validate_graph(graph).conforms
    assert pyshacl_adapter.validate(graph, SUITE_PATHS, local_only=False).conforms
    assert not any("dependsOn" in p for _, p, _ in graph.triples())
    models = [load_shard_record(d, target_schema_version=3).shard for d in (a, b)]
    assert DependencyGraph.from_shards(models).cycles() == []


def test_unknown_relation_predicate_fails_closed_shape():
    from folio_insights.shapes.rendering import iri

    graph, node = render_shard(atomic_record())
    graph.add(node, FI + "unknownRelation", iri("urn:other"))
    assert not default_suite().validate_graph(graph).conforms
    assert not pyshacl_adapter.validate(graph, SUITE_PATHS).conforms


def test_warning_and_violation_policy_is_preserved():
    data = atomic_record(signatures=[])
    report = default_suite().validate_shard(data)
    assert report.conforms and report.warnings and not report.violations
    data["confidence"] = 2.0
    report = default_suite().validate_shard(data)
    assert not report.conforms and report.violations and report.warnings


def test_generation_has_no_drift():
    assert check_generated()
    Graph().parse(str(GENERATED_PATH), format="turtle")


def test_atomic_core_imports_do_not_load_rdflib():
    result = subprocess.run(
        [sys.executable, "-c", "import sys; import folio_insights.shards.records; "
         "import folio_insights.models.knowledge_unit; "
         "import folio_insights.shapes.pydantic_to_shacl; "
         "assert 'rdflib' not in sys.modules; assert 'pyshacl' not in sys.modules"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
