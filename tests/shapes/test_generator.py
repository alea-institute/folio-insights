"""SHACL-02 / SHACL-04: the Pydantic-to-SHACL generator.

* Generation is byte-deterministic and the committed TTL is current
  (``scripts/generate_shapes.py --check``).
* Round trip, as a property test over every subtype and its optional-field
  variants: Pydantic instance -> rendering -> validate against the generated
  shapes conforms, under pyshacl and under the compiled engine.
* Seeded mutations of a valid record are reported by both engines.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from pydantic import BaseModel
from pyoxigraph import RdfFormat
from pyoxigraph import parse as ox_parse
from rdflib import Graph

from folio_insights.shapes import pyshacl_adapter
from folio_insights.shapes.compiled import CompiledSuite
from folio_insights.shapes.fields import (
    FI,
    UnsupportedFieldType,
    model_spec,
)
from folio_insights.shapes.pydantic_to_shacl import (
    GENERATED_PATH,
    check_generated,
    generate_ttl,
)
from folio_insights.shapes.rendering import SHARD_MODELS, render_shard
from folio_insights.storage.projection import DEPENDENCY_PREDICATES
from tests.shapes.cases import dumped, mutate
from tests.shapes.strategies import SUBTYPE_STRATEGIES
from tests.shards.conftest import _SUBTYPE_TABLE

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATED_ONLY = CompiledSuite([GENERATED_PATH])


def test_generation_is_deterministic_and_committed() -> None:
    assert generate_ttl() == generate_ttl()
    assert check_generated(), "run scripts/generate_shapes.py and commit the result"


def test_check_script_passes_and_detects_drift(tmp_path: Path) -> None:
    ok = subprocess.run(
        [sys.executable, "scripts/generate_shapes.py", "--check"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=False,
    )
    assert ok.returncode == 0, ok.stderr
    stale = tmp_path / "stale.ttl"
    stale.write_text(GENERATED_PATH.read_text() + "\n# drift\n")
    assert not check_generated(stale)
    assert not check_generated(tmp_path / "missing.ttl")


def test_generated_ttl_parses_in_both_rdf_libraries() -> None:
    rdflib_graph = Graph().parse(str(GENERATED_PATH), format="turtle")
    with open(GENERATED_PATH, "rb") as handle:
        ox_triples = list(ox_parse(handle, format=RdfFormat.TURTLE))
    assert len(rdflib_graph) == len(ox_triples) > 0


@pytest.mark.parametrize("model", SHARD_MODELS, ids=lambda m: m.__name__)
def test_every_field_has_one_property_shape(model: type[BaseModel]) -> None:
    graph = Graph().parse(str(GENERATED_PATH), format="turtle")
    rows = graph.query(
        """
        PREFIX sh: <http://www.w3.org/ns/shacl#>
        SELECT ?name WHERE { ?shape sh:targetClass ?cls ; sh:property ?p . ?p sh:name ?name }
        """,
        initBindings={"cls": __import__("rdflib").URIRef(model_spec(model).class_iri)},
    )
    names = sorted(str(r.name) for r in rows)
    assert names == sorted(model.model_fields)


def test_dependency_predicates_match_the_projection() -> None:
    spec = model_spec(SHARD_MODELS[0])
    for field_name, local in DEPENDENCY_PREDICATES.items():
        assert spec.field(field_name).predicate == f"{FI}{local}"


def test_unsupported_annotation_fails_generation() -> None:
    class Odd(BaseModel):
        tags: set[str]

    model_spec.cache_clear()
    with pytest.raises(UnsupportedFieldType):
        model_spec(Odd)
    model_spec.cache_clear()


@pytest.mark.parametrize("tag", list(SUBTYPE_STRATEGIES))
def test_round_trip_property(tag: str) -> None:
    """Pydantic -> SHACL -> validate(instance) conforms, for every variant."""

    @settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(SUBTYPE_STRATEGIES[tag])
    def run(instance: BaseModel) -> None:
        graph, _ = render_shard(instance)
        assert GENERATED_ONLY.validate(graph) == []
        report = pyshacl_adapter.validate(graph, [GENERATED_PATH])
        assert report.conforms, report.text

    run()


MUTATIONS = {
    "drop_required": (lambda d: {k: v for k, v in d.items() if k != "sense"}, "MinCountConstraintComponent", "sense"),
    "enum_out_of_set": (lambda d: mutate(d, layer="L9"), "InConstraintComponent", "layer"),
    "out_of_range": (lambda d: mutate(d, confidence=1.5), "MaxInclusiveConstraintComponent", "confidence"),
    "wrong_datatype": (lambda d: mutate(d, confidence="high"), "DatatypeConstraintComponent", "confidence"),
    "ill_formed_datetime": (lambda d: mutate(d, extracted_at="not-a-time"), "DatatypeConstraintComponent", "extractedAt"),
    "two_values": (lambda d: mutate(d, sense=["a", "b"]), "MaxCountConstraintComponent", "sense"),
    "unknown_field": (lambda d: mutate(d, smuggled=1), "ClosedConstraintComponent", "smuggled"),
    "nested_missing": (
        lambda d: mutate(d, triple={"predicate": "p", "object": "o"}),
        "NodeConstraintComponent", "triple",
    ),
    "nested_bad_map": (
        lambda d: mutate(d, contest_votes={"did:key:zA": 3}),
        "NodeConstraintComponent", "contestVotes",
    ),
}


@pytest.mark.parametrize("tag,cls", _SUBTYPE_TABLE)
@pytest.mark.parametrize("mutation", list(MUTATIONS))
def test_seeded_mutations_are_reported_by_both_engines(tag: str, cls: type, mutation: str) -> None:
    fn, component, local = MUTATIONS[mutation]
    graph, _ = render_shard(fn(dumped(cls)))
    compiled = {(r.component, r.path) for r in GENERATED_ONLY.validate(graph)}
    assert (component, f"{FI}{local}") in compiled
    report = pyshacl_adapter.validate(graph, [GENERATED_PATH])
    assert not report.conforms
    assert (f"http://www.w3.org/ns/shacl#{component}", f"{FI}{local}") in {
        (r["component"], r["path"]) for r in report.results
    }
