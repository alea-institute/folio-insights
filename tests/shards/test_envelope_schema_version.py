"""U17 envelope schema-version stamp (R18 identity boundary).

Every in-memory envelope carries the current integer ``schema_version``. It is
frozen, refused by the ``edit_shard_content`` gate, excluded from the content
hash (representation, not content), and only the current version constructs.
Legacy records migrate through ``shards.records.load_shard_record``.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from folio_insights.revision import (
    IMMUTABLE_FIELD_PATHS,
    InMemoryShardStore,
    canonical_content_hash,
    edit_shard_content,
)
from folio_insights.shards import (
    ENVELOPE_SCHEMA_VERSION,
    ShardEnvelope,
    SimpleAssertionShard,
)

from tests.shards.conftest import _SUBTYPE_TABLE, _sample_shard

pytestmark = pytest.mark.shards


def test_current_version_is_two() -> None:
    assert ENVELOPE_SCHEMA_VERSION == 2


@pytest.mark.parametrize("tag,cls", _SUBTYPE_TABLE)
def test_default_construction_carries_current_version(
    tag: str, cls: type[ShardEnvelope]
) -> None:
    shard = _sample_shard(cls)
    assert shard.schema_version == ENVELOPE_SCHEMA_VERSION
    dumped = shard.model_dump(mode="json")
    assert dumped["schema_version"] == ENVELOPE_SCHEMA_VERSION
    assert cls.model_validate(dumped) == shard


@pytest.mark.parametrize("bad", [0, 1, 3, -1, 99, True, False, "2", 2.0, None])
def test_non_current_versions_refused_in_memory(bad: object) -> None:
    with pytest.raises(ValidationError, match="schema_version"):
        _sample_shard(SimpleAssertionShard, schema_version=bad)


def test_schema_version_is_frozen() -> None:
    shard = _sample_shard(SimpleAssertionShard)
    with pytest.raises(ValidationError) as excinfo:
        shard.schema_version = 3  # type: ignore[misc]
    assert excinfo.value.errors()[0]["type"] == "frozen_field"


def test_schema_version_in_immutable_gate() -> None:
    assert "schema_version" in IMMUTABLE_FIELD_PATHS


async def test_edit_path_refuses_schema_version() -> None:
    store = InMemoryShardStore()
    shard = _sample_shard(SimpleAssertionShard)
    await store.put(shard.shard_iri, shard)
    with pytest.raises(ValueError, match="immutable"):
        await edit_shard_content(
            shard.shard_iri, "schema_version", 3, "did:key:zX", "r", None, store
        )
    after = await store.get(shard.shard_iri)
    assert after.schema_version == ENVELOPE_SCHEMA_VERSION
    assert after.content_edits == []


def test_schema_version_excluded_from_content_hash() -> None:
    """The stamp is representation metadata: the hash ignores it (U17 KTD2)."""
    import hashlib

    from folio_insights.revision.content_edit import _jcs_canonical_bytes

    shard = _sample_shard(SimpleAssertionShard)
    payload = shard.model_dump(
        mode="json",
        exclude={
            "transaction_time",
            "valid_time_start",
            "valid_time_end",
            "content_edits",
            "signatures",
        },
    )
    assert "schema_version" in payload
    without_stamp = {k: v for k, v in payload.items() if k != "schema_version"}
    expected = hashlib.sha256(_jcs_canonical_bytes(without_stamp)).hexdigest()
    assert canonical_content_hash(shard) == expected
