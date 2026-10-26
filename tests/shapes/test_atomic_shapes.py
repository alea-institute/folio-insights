"""U35: opt-in atomic records share the local/full SHACL contract."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest
from rdflib import Dataset, Graph, Literal, URIRef

from folio_insights.shapes import pyshacl_adapter
from folio_insights.shapes.fields import FI, XSD_STRING
from folio_insights.shapes.pydantic_to_shacl import GENERATED_PATH, check_generated
from folio_insights.shapes.rendering import ValidationGraph, lit, render_shard
from folio_insights.shapes.suite import SUITE_PATHS, default_suite
from folio_insights.shards import load_shard_record
from tests.shards.conftest import _SUBTYPE_TABLE, _sample_shard
from tests.shards.test_atomic_records import _atomic


# pyshacl's Dataset loader/cloner still uses the deprecated rdflib property.
# Its queries also reach rdflib's deprecated Dataset accessors internally.
pytestmark = [
    pytest.mark.filterwarnings(
        r"ignore:^Dataset\.default_context is deprecated, use Dataset\.default_graph instead\.$:"
        r"DeprecationWarning:^pyshacl\.(rdfutil\.(load|clone)|shapes_graph)$"
    ),
    pytest.mark.filterwarnings(
        r"ignore:^Dataset\.default_context is deprecated, use Dataset\.default_graph instead\.$:"
        r"DeprecationWarning:^rdflib\.graph$"
    ),
    pytest.mark.filterwarnings(
        r"ignore:^Dataset\.identifier is deprecated and will be removed in future versions\.$:"
        r"DeprecationWarning:^rdflib\.graph$"
    ),
]


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


@pytest.mark.parametrize("conflicting_key", (False, True))
def test_dataset_union_preserves_atomic_identity(conflicting_key):
    from folio_insights.shapes.identity_binding import BINDING_COMPONENT

    data = atomic_record()
    graph, node = render_shard(data)
    dataset = Dataset()
    for name in ("urn:first", "urn:second"):
        pyshacl_adapter.to_rdflib(graph, into=dataset.graph(URIRef(name)))
    if conflicting_key:
        dataset.graph(URIRef("urn:second")).add((
            URIRef(data["shard_iri"]), URIRef(FI + "propositionKey"), Literal("b" * 64),
        ))

    report = pyshacl_adapter.validate(dataset, SUITE_PATHS)
    assert report.conforms is (not conflicting_key), report.text
    assert any(r["component"] == BINDING_COMPONENT for r in report.results) is conflicting_key
    union = pyshacl_adapter.from_rdflib(dataset)
    keys = union.values(node, FI + "propositionKey")
    assert len(keys) == (2 if conflicting_key else 1)
    assert len(union.triples()) == len(set(union.triples()))
    assert set(keys) == {lit(data["proposition_key"], XSD_STRING)} | ({
        lit("b" * 64, XSD_STRING),
    } if conflicting_key else set())


@pytest.mark.parametrize("parents", ((), ("urn:first",), ("urn:first", "urn:second")))
def test_tuple_and_list_archives_produce_identical_rdf(parents):
    tuple_data = atomic_record(legacy_hierarchy={"elaborates": parents})
    list_data = {**tuple_data, "legacy_hierarchy": {"elaborates": list(parents)}}
    for data in (tuple_data, list_data):
        load_shard_record(data, target_schema_version=3)

    tuple_graph, node = render_shard(tuple_data)
    list_graph, _ = render_shard(list_data)
    assert tuple_graph.triples() == list_graph.triples()
    history, = tuple_graph.values(node, FI + "legacyHierarchy")
    assert [value[1] for value in tuple_graph.values(history, FI + "historicalElaborates")] == list(parents)
    for data, graph in ((tuple_data, tuple_graph), (list_data, list_graph)):
        assert default_suite().validate_shard(data).conforms
        report = pyshacl_adapter.validate(graph, SUITE_PATHS)
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


@pytest.mark.parametrize("engine", ("compiled", "reference"))
@pytest.mark.parametrize("end,conforms", ((10, False), (5, False), (90, True)))
def test_atomic_offset_ordering(engine, end, conforms):
    data = atomic_record()
    data["atomic_identity"]["end"] = end  # start is 10; every end here is positive.
    graph, _ = render_shard(data)
    if engine == "compiled":
        report = default_suite().validate_graph(graph)
        assert report.conforms is conforms
    else:
        # Exercise the generated SHACL itself, independently of model checks.
        passed, _, text = pyshacl_adapter.pyshacl.validate(
            pyshacl_adapter.to_rdflib(graph),
            shacl_graph=Graph().parse(str(GENERATED_PATH), format="turtle"),
            allow_warnings=True,
        )
        assert bool(passed) is conforms, text


@pytest.mark.parametrize("change", ("key", "iri", "intact"))
@pytest.mark.parametrize("entrypoint", (
    "shard", "graph", "compiled", "reference", "reference_rdf", "reference_full",
    "api", "payload_gate", "chunk", "owl_validator", "owl_report", "rdf_bridge",
))
def test_atomic_identity_binding_at_validation_entrypoints(tmp_path, change, entrypoint):
    from folio_insights.storage import ShaclViolation

    data = atomic_record()
    if change == "key":
        data["proposition_key"] = "b" * 64
    elif change == "iri":
        data["shard_iri"] = "urn:folio:shard/" + "b" * 32
    expected = change == "intact"
    graph, _ = render_shard(data)
    suite = default_suite()
    if entrypoint == "shard":
        report = suite.validate_shard(data)
    elif entrypoint == "graph":
        report = suite.validate_graph(graph)
    elif entrypoint == "compiled":
        from folio_insights.shapes.suite import Report

        report = Report(tuple(suite.compiled.validate(graph)))
    elif entrypoint.startswith("reference"):
        if entrypoint == "reference_rdf":
            # Round-trip through RDF: no renderer side channel can carry the check.
            graph = Graph().parse(
                data=pyshacl_adapter.to_rdflib(graph).serialize(format="nt"), format="nt",
            )
        report = pyshacl_adapter.validate(
            graph, SUITE_PATHS, local_only=entrypoint != "reference_full",
        )
        assert report.conforms is expected, report.text
        if not expected:
            assert any(r["severity"].endswith("#Violation") for r in report.results)
            assert "Conforms: True" not in report.text
        return
    elif entrypoint == "api":
        from api.routes.validate import _validate

        report = _validate(data)
        assert report.model_valid is expected
        assert report.conforms is expected
        assert bool(report.violations) is (not expected)
        return
    elif entrypoint.startswith("owl_"):
        from folio_insights.services.shacl_validator import SHACLValidator

        validator = SHACLValidator()
        rdf = pyshacl_adapter.to_rdflib(graph)
        if entrypoint == "owl_validator":
            report = validator.validate(rdf)
            assert bool(report.violations) is (not expected)
        else:
            report = validator.generate_report(rdf)
            assert (report.checks[0].status == "FAIL") is (not expected)
        assert report.conforms is expected
        return
    elif entrypoint == "rdf_bridge":
        from pyoxigraph import NamedNode, RdfFormat

        from folio_insights.shapes.rendering import to_ntriples
        from folio_insights.store.pyoxigraph_store import PyoxigraphStore

        store = PyoxigraphStore()
        store.store.load(
            input=to_ntriples(graph), format=RdfFormat.N_TRIPLES, to_graph=NamedNode("urn:test"),
        )
        # Even a caller-supplied shape suite cannot waive model hash binding.
        path = tmp_path / "empty.ttl"
        path.write_text("@prefix sh: <http://www.w3.org/ns/shacl#> .\n")
        conforms, text = store.validate_shard_via_rdflib_bridge(NamedNode(data["shard_iri"]), path)
        assert conforms is expected, text
        return
    elif entrypoint == "payload_gate":
        from folio_insights.storage.shacl_status import check_shard_payload

        if expected:
            check_shard_payload(data, suite)
        else:
            with pytest.raises(ShaclViolation):
                check_shard_payload(data, suite)
        return
    else:
        from folio_insights.storage._parallel import validate_chunk

        failures, _warnings = validate_chunk(
            [json.dumps(data).encode()], tuple(str(p) for p in SUITE_PATHS),
        )
        assert bool(failures) is (not expected)
        if failures:
            assert all(r["severity"] == "Violation" for r in failures)
        return
    assert report.conforms is expected
    assert bool(report.violations) is (not expected)
    reference = pyshacl_adapter.validate(graph, SUITE_PATHS)
    assert {(r.focus, r.path, r.component, r.severity) for r in report.results} == {
        (r["focus"], r["path"], r["component"].removeprefix("http://www.w3.org/ns/shacl#"),
         r["severity"].removeprefix("http://www.w3.org/ns/shacl#"))
        for r in reference.results
    }


@pytest.mark.parametrize("change", ("key", "iri", "intact"))
@pytest.mark.parametrize("entrypoint", ("http", "preappend"))
async def test_atomic_binding_http_and_preappend(tmp_path, change, entrypoint):
    data = atomic_record()
    if change == "key":
        data["proposition_key"] = "b" * 64
    elif change == "iri":
        data["shard_iri"] = "urn:folio:shard/" + "b" * 32
    expected = change == "intact"
    if entrypoint == "http":
        from httpx import ASGITransport, AsyncClient

        from api.main import app

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/validate", json=data)
        assert response.status_code == 200
        report = response.json()
        assert report["conforms"] is expected
        assert report["model_valid"] is expected
        assert bool(report["violations"]) is (not expected)
    else:
        from folio_insights.storage import ShaclViolation
        from tests.storage.conftest import open_ctx

        ctx = await open_ctx(tmp_path / "storage")
        try:
            head = (await ctx.status()).journal_head
            payload = json.dumps(data).encode()
            if expected:
                ctx._check_shacl(payload)
            else:
                with pytest.raises(ShaclViolation):
                    ctx._check_shacl(payload)
            assert (await ctx.status()).journal_head == head
        finally:
            await ctx.close()


def test_atomic_core_imports_do_not_load_rdflib():
    result = subprocess.run(
        [sys.executable, "-c", "import sys; import folio_insights.shards.records; "
         "import folio_insights.models.knowledge_unit; "
         "import folio_insights.shapes.pydantic_to_shacl; "
         "assert 'rdflib' not in sys.modules; assert 'pyshacl' not in sys.modules"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
