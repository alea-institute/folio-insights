"""Phase 9 U0 — every fi: term the storage projection writes is declared (R1).

The Phase 13 projection wrote ``fi:frameworkId``, ``fi:dependsOnPrecedent``,
``fi:dependsOnShard`` and many envelope/governance terms the vocabulary did
not declare, and wrote the framework as a literal although ``fi:framework`` is
an object property. These tests fail whenever the projection (or an export's
signed-record carriers) emits an undeclared ``fi:`` term, and pin the U0
projection changes: the framework IRI link, speech act, BFO category and the
mapped spine class.

Two views: the RDF adapters over every shard subtype and every governance
event class (complete by construction), and a real storage context's corpus
graphs and export dataset (what a query and an export actually see).
Synthetic fixtures only.
"""
from __future__ import annotations

import typing
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pyoxigraph import NamedNode
from rdflib import OWL, RDF, URIRef

from folio_insights.governance import events as gov_events
from folio_insights.shards import (
    AttestedSignature,
    ConflictingAuthoritiesShard,
    DisputedPropositionShard,
    GlossShard,
    HypothesisShard,
    SimpleAssertionShard,
)
from folio_insights.storage.projection import (
    governance_triples,
    shard_triples,
)
from folio_insights.vocab import FI_PREFIX, load_graph
from folio_insights.vocab._constants import (
    BFO_CATEGORY_SPINE_CLASS,
    FRAMEWORK_NS,
    framework_iri,
)

from tests.shards.conftest import _sample_shard

_DECLARING_TYPES = {
    OWL.ObjectProperty,
    OWL.DatatypeProperty,
    OWL.AnnotationProperty,
    OWL.Class,
}
_RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
T0 = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _declared_terms() -> set[str]:
    g = load_graph(include_bfo_mapping=True)
    return {
        str(s)
        for s, _, o in g.triples((None, RDF.type, None))
        if o in _DECLARING_TYPES and isinstance(s, URIRef) and str(s).startswith(FI_PREFIX)
    }


def _fi_terms(triples) -> set[str]:
    """The fi: predicates, plus fi: classes used as rdf:type objects."""
    out: set[str] = set()
    for _s, p, o in triples:
        pv = p.value
        if pv.startswith(FI_PREFIX):
            out.add(pv)
        if pv == _RDF_TYPE and isinstance(o, NamedNode) and o.value.startswith(FI_PREFIX):
            out.add(o.value)
    return out


def _shards():
    categories = list(BFO_CATEGORY_SPINE_CLASS)
    out = []
    for n, cls in enumerate(
        (
            SimpleAssertionShard,
            DisputedPropositionShard,
            ConflictingAuthoritiesShard,
            GlossShard,
            HypothesisShard,
        )
    ):
        out.append(
            _sample_shard(
                cls,
                shard_iri=f"urn:folio:shard/{n:032x}",
                bfo_category=categories[n % len(categories)],
                depends_on_axioms=["urn:folio:shard/" + "a" * 32],
                depends_on_definitions=["urn:folio:shard/" + "b" * 32],
                depends_on_precedents=["urn:folio:shard/" + "c" * 32],
                depends_on_shards=["urn:folio:shard/" + "d" * 32],
                supersedes="urn:folio:shard/" + "e" * 32,
                superseded_by="urn:folio:shard/" + "f" * 32,
                valid_time_start=T0,
                valid_time_end=T0.replace(year=2027),
                signatures=[
                    AttestedSignature(did="did:key:zSynthetic", action="extract", signed_at=T0)
                ],
            )
        )
    return out


def _event_payloads() -> list[dict]:
    """One JSON payload per GovernanceEvent class, every optional field set."""
    sig = AttestedSignature(
        did="did:key:zSynthetic", action="extract", signed_at=T0, over_content_hash="0" * 64
    )
    iri = "urn:folio:shard/" + "1" * 32
    values = {
        "subject_did": "did:key:zSubject",
        "role": "reviewer",
        "revoked_role": "reviewer",
        "shard_iri": iri,
        "extractor_model": "synthetic-model",
        "new_status": "demonstrable",
        "cited_iris": [iri],
        "voter_did": "did:key:zVoter",
        "position_text": "synthetic position",
        "resolution_path": "arbiter",
        "prime_analogate_iri": iri,
        "distinction_kind": "analogica",
        "old_shard_iri": iri,
        "new_shard_iri": "urn:folio:shard/" + "2" * 32,
        "cascade_preview_hash": "0" * 64,
        "field_path": "sense",
        "rationale": "synthetic rationale",
        "new_parent_iri": iri,
        "strategy": "sense_distinction",
        "policy": "prefer_latest",
    }
    union = typing.get_args(typing.get_args(gov_events.GovernanceEvent)[0])
    out = []
    for position, cls in enumerate(union):
        fields = {
            name: values[name]
            for name, info in cls.model_fields.items()
            if name not in {"corpus", "position", "signature", "action"}
            and name in values
            and (info.is_required() or info.default is None)  # keep pinned defaults
        }
        missing = [
            name
            for name, info in cls.model_fields.items()
            if info.is_required() and name not in fields and name not in {"corpus", "signature"}
        ]
        assert not missing, f"{cls.__name__}: no synthetic value for {missing}"
        event = cls(corpus="corpus-a", position=position, signature=sig, **fields)
        out.append(event.model_dump(mode="json"))
    assert len(out) == len(union) >= 13
    return out


def test_shard_adapter_emits_only_declared_terms() -> None:
    declared = _declared_terms()
    for shard in _shards():
        emitted = _fi_terms(shard_triples(shard, journal_position=0))
        undeclared = sorted(emitted - declared)
        assert not undeclared, f"{shard.shard_type}: undeclared fi: terms {undeclared}"


def test_governance_adapter_emits_only_declared_terms() -> None:
    declared = _declared_terms()
    for payload in _event_payloads():
        emitted = _fi_terms(governance_triples("corpus-a", payload, journal_position=0))
        undeclared = sorted(emitted - declared)
        assert not undeclared, f"{payload['action']}: undeclared fi: terms {undeclared}"


def test_dependency_predicates_are_declared_object_properties() -> None:
    g = load_graph()
    for local in ("dependsOnAxiom", "dependsOnDefinition", "dependsOnPrecedent", "dependsOnShard"):
        assert (URIRef(FI_PREFIX + local), RDF.type, OWL.ObjectProperty) in g, local


def test_framework_projects_as_iri_and_keeps_identifier_literal() -> None:
    shard = _sample_shard(SimpleAssertionShard, framework_id="us.federal.fre")
    triples = shard_triples(shard, journal_position=3)
    framework = [o for _s, p, o in triples if p.value == FI_PREFIX + "framework"]
    assert framework == [NamedNode(FRAMEWORK_NS + "us.federal.fre")]
    ident = [o for _s, p, o in triples if p.value == FI_PREFIX + "frameworkId"]
    assert [o.value for o in ident] == ["us.federal.fre"]


def test_framework_iri_is_valid_for_any_identifier() -> None:
    odd = "standin.with space/and#hash"
    iri = framework_iri(odd)
    NamedNode(iri)  # a valid IRI, never a fallback literal
    assert iri.startswith(FRAMEWORK_NS) and " " not in iri and "#" not in iri.removeprefix(FRAMEWORK_NS)


@pytest.mark.parametrize("category", sorted(BFO_CATEGORY_SPINE_CLASS))
def test_bfo_category_and_spine_class_are_projected(category: str) -> None:
    shard = _sample_shard(SimpleAssertionShard, bfo_category=category, speech_act="dictum")
    by_pred = {}
    for _s, p, o in shard_triples(shard, journal_position=0):
        by_pred.setdefault(p.value, []).append(o)
    assert [o.value for o in by_pred[FI_PREFIX + "bfoCategory"]] == [category]
    assert [o.value for o in by_pred[FI_PREFIX + "speechAct"]] == ["dictum"]
    assert by_pred[FI_PREFIX + "subjectBfoClass"] == [NamedNode(BFO_CATEGORY_SPINE_CLASS[category])]
    # the spine class is a declared spine class, and the shard is not retyped
    spine = load_graph()
    assert (URIRef(BFO_CATEGORY_SPINE_CLASS[category]), RDF.type, OWL.Class) in spine
    assert [o.value for o in by_pred[_RDF_TYPE]] == [FI_PREFIX + "Shard"]


def test_occurrent_event_follows_the_process_fold() -> None:
    assert BFO_CATEGORY_SPINE_CLASS["occurrent_event"] == FI_PREFIX + "Process"


def test_promotion_citations_use_the_declared_cited_iri_term() -> None:
    payload = next(p for p in _event_payloads() if p["action"] == "promote")
    preds = {p.value for _s, p, _o in governance_triples("c", payload, journal_position=0)}
    assert FI_PREFIX + "citedIri" in preds
    assert FI_PREFIX + "citedIris" not in preds


async def test_stored_corpus_and_export_use_only_declared_terms(tmp_path: Path) -> None:
    """A real context: every fi: predicate/class in the corpus graphs and in the
    export dataset (signed-record carriers included) is declared."""
    from folio_insights.storage import CorpusStorageContext
    from folio_insights.storage.exports import build_export_dataset
    from folio_insights.storage.projection import TBOX_GRAPH

    from tests.storage.conftest import genesis, new_identity

    declared = _declared_terms()
    ctx = await CorpusStorageContext.open(tmp_path / "storage", "corpus-a")
    try:
        await ctx.ingest_shards(_shards())
        # Signed now: governance appends check signed_at against server time (R17).
        await ctx.governance.append(genesis("corpus-a", new_identity(), datetime.now(UTC)))
        rows = await ctx.query(
            "SELECT DISTINCT ?p ?o WHERE { { ?s ?p ?o } UNION { GRAPH ?g { ?s ?p ?o } } }"
        )
        emitted = _fi_terms((None, r["p"], r["o"]) for r in rows)
        assert FI_PREFIX + "framework" in emitted
        assert not sorted(emitted - declared), sorted(emitted - declared)

        dataset = await build_export_dataset(ctx)
        quads = [q for q in dataset.quads() if q.graph_name != TBOX_GRAPH]
        exported = _fi_terms((q.subject, q.predicate, q.object) for q in quads)
        assert not sorted(exported - declared), sorted(exported - declared)
    finally:
        await ctx.close()
