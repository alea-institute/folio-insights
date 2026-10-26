"""U36: flat references, historical hierarchy and audited identity protection."""
from __future__ import annotations

import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from folio_insights.identity import did_key_from_public, sign_attestation, verify_attestation
from folio_insights.identity.cache import InMemoryDidDocCache
from folio_insights.revision import (
    InMemoryShardStore, canonical_content_hash, edit_shard_content, get_shard_at,
)
from folio_insights.revision.acyclicity import (
    DependencyCycle, check_new_edges, record_out_edges, shard_out_edges,
)
from folio_insights.revision.dependency_graph import DependencyGraph
from folio_insights.revision.tractarian import TractarianIndex, TractarianRevision
from folio_insights.shards import (
    PropositionLink, ShardTag, dump_shard_record, load_shard_record, mint_shard_iri,
)
from tests.shards.test_atomic_records import _atomic
from tests.shards.conftest import _sample_shard


def test_legacy_hierarchy_is_history_without_navigation_or_inferred_links() -> None:
    iri, digest = mint_shard_iri("urn:parent", "parent span")
    parent = _sample_shard(source_uri="urn:parent", source_span="parent span",
                           shard_iri=iri, provenance_hash=digest)
    old = _sample_shard(elaborates=[parent.shard_iri])
    raw = dump_shard_record(old)
    view = load_shard_record(raw, target_schema_version=3)
    assert view.original_bytes == raw
    assert view.shard.legacy_hierarchy.elaborates == (parent.shard_iri,)
    assert view.shard.links == []
    assert shard_out_edges(old) == shard_out_edges(view.shard) == ()
    assert record_out_edges(json.loads(raw)) == ()
    assert record_out_edges(json.loads(dump_shard_record(view.shard))) == ()
    assert DependencyGraph.from_shards([parent, old]).edge_count == 0
    index = TractarianIndex([(parent, 0), (old, 1)])
    assert index.path_of(old.shard_iri) == old.shard_iri
    assert index.children(old.shard_iri) == []
    revision = TractarianRevision.from_payload(1, old.shard_iri, raw)
    assert revision.elaborates == (parent.shard_iri,)


def test_flat_reference_survives_revisions_and_new_arrivals() -> None:
    a, b = _atomic(), _sample_shard()
    before = TractarianIndex([(a, 9)])
    revised = a.model_copy(update={"depends_on_axioms": [b.shard_iri]})
    after = TractarianIndex([(b, 2), (revised, 9)])
    assert before.path_of(a.shard_iri) == after.path_of(a.shard_iri) == a.shard_iri
    assert after.iri_of(a.shard_iri) == a.shard_iri
    assert all(n.parent_iri is None and n.parent_field is None and n.depth == 1
               for n in after.nodes())


@pytest.mark.parametrize("relation", ["cites", "contradicts"])
def test_reciprocal_links_are_not_logical_dependencies(relation: str) -> None:
    a, b = _atomic(), _sample_shard()
    # Both are schema-3 records with distinct, deterministic identities.
    b = load_shard_record(dump_shard_record(b), target_schema_version=3).shard
    a.links = [PropositionLink(relation=relation, target_iri=b.shard_iri)]
    b.links = [PropositionLink(relation=relation, target_iri=a.shard_iri)]
    a = type(a).model_validate(a.model_dump())
    b = type(b).model_validate(b.model_dump())
    check_new_edges(DependencyGraph(), [a, b])
    assert DependencyGraph.from_shards([a, b]).is_acyclic()
    a.depends_on_shards = [b.shard_iri]
    b.depends_on_shards = [a.shard_iri]
    with pytest.raises(DependencyCycle):
        check_new_edges(DependencyGraph(), [a, b])


@pytest.mark.parametrize("path", [
    "identity_recipe", "proposition_key", "atomic_identity", "atomic_identity.text",
    "triple.subject", "triple.predicate", "triple", "legacy_hierarchy", "elaborates",
])
async def test_protected_edits_refused_before_mutation(path: str) -> None:
    shard = _atomic()
    store = InMemoryShardStore()
    await store.put(shard.shard_iri, shard)
    before = dump_shard_record(shard)
    with pytest.raises(ValueError, match="immutable"):
        await edit_shard_content(shard.shard_iri, path, "changed", "did:key:zEditor",
                                 "identity cannot change", None, store)
    assert dump_shard_record(await store.get(shard.shard_iri)) == before


async def test_audited_tags_keep_identity_and_verifiable_signature_history() -> None:
    shard = _atomic()
    key = Ed25519PrivateKey.generate()
    did = did_key_from_public(key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    ))
    shard.signatures.append(sign_attestation(
        canonical_content_hash(shard), key, did, "extract",
        signing_key_id=f"{did}#{did.removeprefix('did:key:')}", did_doc_snapshot_at=None,
    ))
    original = dump_shard_record(shard)
    signature = shard.signatures[0]
    store = InMemoryShardStore()
    await store.put(shard.shard_iri, shard)
    tags = [ShardTag(iri="https://example.org/Duty", label="Duty", confidence=0.99,
                     extraction_path="entity_ruler", branch="Deontic Specification")]
    edit = await edit_shard_content(shard.shard_iri, "folio_tags", tags, did,
                                    "confirmed applicable duty", key, store)
    current = await store.get(shard.shard_iri)
    assert current.proposition_key == shard.proposition_key
    assert current.identity_recipe == shard.identity_recipe
    assert current.signatures == [signature]
    assert current.folio_tags[0].label == "Duty"
    assert edit.old_value == [] and edit.rationale == "confirmed applicable duty"
    assert edit.signature.over_content_hash == canonical_content_hash(shard)
    cache = InMemoryDidDocCache()
    assert not await verify_attestation(current, signature, cache=cache)
    historical = await get_shard_at(shard.shard_iri, shard.extracted_at, store)
    assert dump_shard_record(historical) == original
    assert await verify_attestation(historical, signature, cache=cache)
