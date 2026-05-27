"""Phase 4 Plan 02 — global shard_iri_registry collision-detection tests.

Covers SHARD-08 (collision detector exercised at 100K, fail-closed halt+flag)
and the registry's idempotent re-mint contract (D-03/D-04/D-05).

Patterns:
  * ``asyncio_mode = "auto"`` (pyproject.toml) — ``async def`` tests need no decorator.
  * module-level ``pytestmark = pytest.mark.shards``; the 100K test is also ``slow``.
  * ``tmp_path`` SQLite DB so the registry self-bootstraps its own table.
"""
from __future__ import annotations

import pytest

from folio_insights.shards import ShardIRICollision, ShardIRIRegistry
from folio_insights.shards.minting import mint_shard_iri

pytestmark = pytest.mark.shards


async def test_register_is_idempotent(tmp_path) -> None:
    """Registering the SAME (uri, span) twice returns the SAME IRI; one row."""
    registry = ShardIRIRegistry(tmp_path / "shard_iri_registry.db")

    iri_first = await registry.register("urn:x:1", "alpha")
    iri_second = await registry.register("urn:x:1", "alpha")

    assert iri_first == iri_second
    expected_iri, _ = mint_shard_iri("urn:x:1", "alpha")
    assert iri_first == expected_iri

    records = await registry.all_records()
    assert len(records) == 1


async def test_collision_raises_and_does_not_overwrite(tmp_path) -> None:
    """Same hex32 body + DIFFERENT full hash → ShardIRICollision (fail closed).

    Seed a row for the body that ``("urn:x:1", "alpha")`` mints, but with a
    deliberately wrong full_hash. The next register() of that exact pair mints
    the real full hash, finds the body already stored under a different hash,
    and must raise without overwriting the seeded row.
    """
    db_path = tmp_path / "shard_iri_registry.db"
    registry = ShardIRIRegistry(db_path)

    iri, real_full_hash = mint_shard_iri("urn:x:1", "alpha")
    iri_body = iri.removeprefix("urn:folio:shard/")
    wrong_full_hash = "0" * 64
    assert wrong_full_hash != real_full_hash

    # Seed the body under the wrong full hash via the registry's own writer so
    # we don't reach into SQL from the test.
    await registry._seed_row(iri_body, wrong_full_hash, "urn:other:seed", "seed span")

    with pytest.raises(ShardIRICollision) as excinfo:
        await registry.register("urn:x:1", "alpha")

    # Both full hashes surfaced for human review (D-03 log payload).
    message = str(excinfo.value)
    assert wrong_full_hash in message
    assert real_full_hash in message

    # Fail closed: the seeded row is untouched (full_hash still the wrong one).
    records = await registry.all_records()
    assert len(records) == 1
    assert records[0]["full_hash"] == wrong_full_hash
    assert records[0]["source_uri"] == "urn:other:seed"


async def test_fresh_registry_self_bootstraps_table(tmp_path) -> None:
    """A fresh registry on a tmp DB creates its own table on first connect."""
    db_path = tmp_path / "does_not_exist_yet.db"
    assert not db_path.exists()

    registry = ShardIRIRegistry(db_path)
    # No externally-created schema — first call must work end to end.
    iri = await registry.register("urn:bootstrap:1", "first span")

    assert iri.startswith("urn:folio:shard/")
    assert db_path.exists()
    records = await registry.all_records()
    assert len(records) == 1


@pytest.mark.slow
def test_no_collision_at_100k() -> None:
    """SHARD-08: 100K synthetic shards mint with zero hex32-body collisions."""
    seen: dict[str, str] = {}  # iri_body -> full_hash
    for i in range(100_000):
        iri, full = mint_shard_iri(f"urn:synthetic:{i}", f"span body {i}")
        body = iri.removeprefix("urn:folio:shard/")
        assert body not in seen or seen[body] == full, "hex32 collision!"
        seen[body] = full
    assert len(seen) == 100_000
