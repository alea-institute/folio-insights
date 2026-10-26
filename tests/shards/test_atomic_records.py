"""U34 atomic identity and opt-in schema-3 views; no live ingestion."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import pytest
from pydantic import ValidationError

from folio_insights.shards import (
    ATOMIC_ENVELOPE_SCHEMA_VERSION,
    AtomicIdentity,
    AtomicSimpleAssertionShard,
    ShardIRICollision,
    ShardIRIRegistry,
    UnsupportedEnvelopeVersion,
    atomic_proposition_key,
    dump_shard_record,
    load_shard_record,
    mint_atomic_shard_iri,
    mint_shard_iri,
)
from folio_insights.shards.records import (
    MIGRATIONS,
    EnvelopeMigration,
    MalformedEnvelopeRecord,
)
from tests.shards.conftest import _SUBTYPE_TABLE, _sample_shard
from tests.shards.test_envelope_records import _signed_shard

pytestmark = pytest.mark.shards


def _identity(
    text: str = "A plaintiff must prove formation.", start: int = 10
) -> AtomicIdentity:
    return AtomicIdentity(
        text=text, start=start, end=start + 80, source_snapshot_digest="a" * 64
    )


def _atomic(**overrides: Any) -> AtomicSimpleAssertionShard:
    identity = _identity()
    key = atomic_proposition_key(**identity.model_dump())
    iri, digest = mint_atomic_shard_iri("urn:x:fixture", "sample span", key)
    data = _sample_shard().model_dump()
    data.update(
        schema_version=3,
        identity_recipe="atomic-v1",
        proposition_key=key,
        atomic_identity=identity,
        shard_iri=iri,
        provenance_hash=digest,
    )
    data.update(overrides)
    return AtomicSimpleAssertionShard.model_validate(data)


def test_atomic_tags_links_round_trip_without_changing_identity() -> None:
    shard = _atomic()
    data = json.loads(dump_shard_record(shard))
    data["folio_tags"] = [
        {
            "iri": "https://example.org/Duty",
            "label": "Duty",
            "branch": "Deontic Specification",
            "confidence": 0.99,
            "extraction_path": "entity_ruler",
            "judge_status": None,
        },
        {
            "iri": "https://example.org/Contract",
            "label": "Contract Law",
            "branch": "Area of Law",
            "confidence": 0.95,
            "extraction_path": "semantic",
            "judge_status": "judged",
        },
    ]
    data["links"] = [
        {"relation": rel, "target_iri": "urn:folio:shard/" + "b" * 32}
        for rel in (
            "exception-to",
            "penalty-for",
            "condition-of",
            "cites",
            "contradicts",
        )
    ]
    data["links"].append(
        {"relation": "cites", "citation": "Example v. State, 1 U.S. 2"}
    )
    loaded = load_shard_record(data, target_schema_version=3)
    out = json.loads(dump_shard_record(loaded.shard))
    assert out["folio_tags"] == data["folio_tags"]
    assert len(out["links"]) == 6
    assert out["links"][-1]["citation"] == "Example v. State, 1 U.S. 2"
    assert loaded.shard.proposition_key == shard.proposition_key
    assert loaded.shard.shard_iri == shard.shard_iri
    assert "elaborates" not in out
    assert loaded.source_schema_version == ATOMIC_ENVELOPE_SCHEMA_VERSION
    assert not loaded.migrated


@pytest.mark.parametrize("tag,cls", _SUBTYPE_TABLE)
def test_v2_view_preserves_subtypes_and_archives_hierarchy(tag, cls):
    original = _sample_shard(cls, elaborates=["urn:folio:shard/" + "c" * 32])
    raw = dump_shard_record(original)
    loaded = load_shard_record(raw, target_schema_version=3)
    assert loaded.original_bytes == raw
    assert loaded.source_schema_version == 2
    assert loaded.steps == ((2, 3),)
    assert loaded.migrated and not loaded.content_preserved
    assert isinstance(loaded.shard, cls)
    assert loaded.shard.shard_type == tag
    assert loaded.shard.shard_iri == original.shard_iri
    assert loaded.shard.identity_recipe == "legacy-v1"
    assert loaded.shard.proposition_key is None
    assert loaded.shard.atomic_identity is None
    assert (
        loaded.shard.folio_tags == loaded.shard.links == loaded.shard.elaborates == []
    )
    assert loaded.shard.legacy_hierarchy.elaborates == tuple(original.elaborates)
    assert "elaborates" not in json.loads(dump_shard_record(loaded.shard))
    assert (
        mint_shard_iri(original.source_uri, original.source_span)[0]
        == loaded.shard.shard_iri
    )


async def test_migrated_view_cannot_inherit_signature_verification():
    from folio_insights.identity import verify_attestation
    from folio_insights.identity.cache import InMemoryDidDocCache

    shard, _ = _signed_shard()
    shard.signatures[0].verified = True
    raw = dump_shard_record(shard)
    loaded = load_shard_record(raw, target_schema_version=3)
    assert loaded.original_bytes == raw
    assert loaded.shard.signatures[0].verified is None
    assert not await verify_attestation(
        loaded.shard, loaded.shard.signatures[0], cache=InMemoryDidDocCache()
    )
    original = load_shard_record(loaded.original_bytes).shard
    assert await verify_attestation(
        original, original.signatures[0], cache=InMemoryDidDocCache()
    )


def test_live_default_stays_v2_and_rejects_atomic_records():
    assert (
        load_shard_record(dump_shard_record(_sample_shard())).shard.schema_version == 2
    )
    with pytest.raises(UnsupportedEnvelopeVersion):
        load_shard_record(dump_shard_record(_atomic()))


@pytest.mark.parametrize("bad", [4, 99, True, "3"])
def test_future_schema_rejected(bad):
    data = json.loads(dump_shard_record(_atomic()))
    data["schema_version"] = bad
    with pytest.raises(UnsupportedEnvelopeVersion):
        load_shard_record(data, target_schema_version=3)


@pytest.mark.parametrize(
    "field,value",
    [
        ("identity_recipe", "unknown"),
        ("proposition_key", "b" * 64),
        ("shard_iri", "urn:folio:shard/" + "b" * 32),
    ],
)
def test_altered_atomic_identity_refused(field, value):
    data = json.loads(dump_shard_record(_atomic()))
    data[field] = value
    with pytest.raises(ValidationError):
        load_shard_record(data, target_schema_version=3)


def test_frozen_identity_survives_content_revision():
    shard = _atomic()
    key = shard.proposition_key
    for field, value in [
        ("proposition_key", "b" * 64),
        ("identity_recipe", "legacy-v1"),
        ("atomic_identity", _identity("Another statement")),
    ]:
        with pytest.raises(ValidationError):
            setattr(shard, field, value)
    with pytest.raises(ValidationError):
        shard.atomic_identity.text = "Another statement"
    shard.sense = "A reviewed wording"
    reloaded = load_shard_record(
        dump_shard_record(shard), target_schema_version=3
    ).shard
    assert reloaded.proposition_key == key
    assert reloaded.sense == "A reviewed wording"


@pytest.mark.parametrize(
    "updates",
    [
        {"atomic_identity": None},
        {"proposition_key": None},
        {"identity_recipe": "legacy-v1"},
        {"elaborates": ["urn:folio:shard/" + "b" * 32]},
        {"links": [{"relation": "elaborates", "target_iri": "urn:x"}]},
        {"links": [{"relation": "condition-of"}]},
    ],
)
def test_atomic_contract_refuses_missing_basis_and_active_hierarchy(updates) -> None:
    data = json.loads(dump_shard_record(_atomic()))
    data.update(updates)
    with pytest.raises(ValidationError):
        load_shard_record(data, target_schema_version=3)


def test_migration_cannot_change_identity():
    def rewrite(data):
        data = MIGRATIONS[(2, 3)].apply(data)
        data["source_span"] = "changed"
        return data

    with pytest.raises(MalformedEnvelopeRecord, match="identity boundary"):
        load_shard_record(
            dump_shard_record(_sample_shard()),
            target_schema_version=3,
            migrations={(2, 3): EnvelopeMigration(2, 3, False, rewrite)},
        )


def test_unstamped_legacy_view_does_not_rewrite_input():
    data = _sample_shard().model_dump(mode="json")
    del data["schema_version"]
    raw = json.dumps(data, indent=3).encode()
    loaded = load_shard_record(raw, target_schema_version=3)
    assert loaded.steps == ((1, 2), (2, 3))
    assert loaded.original_bytes == raw
    assert loaded.source_schema_version == 1
    assert loaded.shard.shard_iri == data["shard_iri"]
    assert dump_shard_record(
        load_shard_record(
            dump_shard_record(loaded.shard), target_schema_version=3
        ).shard
    ) == dump_shard_record(loaded.shard)


def test_schema_two_cannot_smuggle_atomic_identity_through_migration():
    data = _sample_shard().model_dump(mode="json")
    data["proposition_key"] = "b" * 64
    with pytest.raises(ValidationError):
        load_shard_record(data, target_schema_version=3)


async def test_registry_upgrades_legacy_table_and_deduplicates_atomic(tmp_path):
    path = tmp_path / "registry.db"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE shard_iri_registry (iri_body TEXT NOT NULL UNIQUE, full_hash TEXT NOT NULL, "
            "source_uri TEXT NOT NULL, source_span TEXT NOT NULL, created_at TEXT)"
        )
        iri, digest = mint_shard_iri("urn:old", "old")
        db.execute(
            "INSERT INTO shard_iri_registry VALUES (?, ?, ?, ?, ?)",
            (iri.rsplit("/", 1)[1], digest, "urn:old", "old", "2026-01-01"),
        )
    registry = ShardIRIRegistry(path)
    assert await registry.register("urn:old", "old") == iri
    args = _identity().model_dump()
    first = await registry.register_atomic("urn:x", "same span", **args)
    assert await registry.register_atomic("urn:x", "same span", **args) == first
    second = await registry.register_atomic(
        "urn:x", "same span", **_identity("A second rule").model_dump()
    )
    assert second != first
    rows = await registry.all_records()
    assert len(rows) == 3
    assert {row["identity_recipe"] for row in rows} == {"legacy-v1", "atomic-v1"}


@pytest.mark.parametrize(
    "column,value",
    [
        ("identity_recipe", "legacy-v1"),
        ("proposition_key", "b" * 64),
        ("full_hash", "c" * 64),
    ],
)
async def test_registry_recipe_key_or_hash_collision_fails_closed(
    tmp_path, column, value
):
    path = tmp_path / "registry.db"
    registry = ShardIRIRegistry(path)
    args = _identity().model_dump()
    iri = await registry.register_atomic("urn:x", "span", **args)
    with sqlite3.connect(path) as db:
        db.execute(f"UPDATE shard_iri_registry SET {column} = ?", (value,))
    with pytest.raises(ShardIRICollision):
        await registry.register_atomic("urn:x", "span", **args)
    with sqlite3.connect(path) as db:
        assert (
            db.execute(f"SELECT {column} FROM shard_iri_registry").fetchone()[0]
            == value
        )
    assert iri.startswith("urn:folio:shard/")
