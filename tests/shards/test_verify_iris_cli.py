"""Phase 4 Plan 02 — `folio-insights verify-iris` CLI tests (SHARD-07, D-06/D-07).

verify-iris re-mints each stored shard IRI from its stored source_uri/source_span
and compares to the stored hex32 body. Any mismatch → non-zero exit + report
(D-07: surface for human review, NEVER auto-quarantine). All-match → exit 0.

Patterns: ``CliRunner`` (tests/test_cli.py), ``asyncio_mode = "auto"`` so the
seeding coroutine runs via ``asyncio.run`` from a sync test body.
"""
from __future__ import annotations

import asyncio

import pytest
from click.testing import CliRunner

from folio_insights.cli import cli
from folio_insights.shards.iri_registry import ShardIRIRegistry
from folio_insights.shards.minting import mint_shard_iri

pytestmark = pytest.mark.shards


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_verify_iris_mismatch_exits_nonzero(runner, tmp_path) -> None:
    """A stored row whose iri_body does NOT re-mint → non-zero exit + named IRI."""
    db_path = tmp_path / "shard_iri_registry.db"
    registry = ShardIRIRegistry(db_path)

    source_uri, source_span = "urn:drift:1", "the original span"
    correct_iri, correct_full = mint_shard_iri(source_uri, source_span)
    correct_body = correct_iri.removeprefix("urn:folio:shard/")
    # Seed a DELIBERATELY WRONG stored body for this source pair (simulates
    # source drift / a hash-logic regression): re-mint will not match.
    wrong_body = ("f" * 32) if correct_body != "f" * 32 else "e" * 32
    asyncio.run(
        registry._seed_row(wrong_body, correct_full, source_uri, source_span)
    )

    result = runner.invoke(cli, ["verify-iris", "--db", str(db_path)])

    assert result.exit_code != 0
    combined = result.output + (result.stderr if result.stderr_bytes else "")
    assert wrong_body in combined  # the mismatching stored IRI is named


def test_verify_iris_all_match_exits_zero(runner, tmp_path) -> None:
    """Every stored row re-mints to its stored body → exit 0."""
    db_path = tmp_path / "shard_iri_registry.db"
    registry = ShardIRIRegistry(db_path)

    async def _seed_clean() -> None:
        await registry.register("urn:clean:1", "span one")
        await registry.register("urn:clean:2", "span two")

    asyncio.run(_seed_clean())

    result = runner.invoke(cli, ["verify-iris", "--db", str(db_path)])

    assert result.exit_code == 0, result.output


def test_verify_iris_empty_registry_exits_nonzero(runner, tmp_path) -> None:
    """WR-02: an existing-but-empty registry must fail loud, not report success.

    ``all_records()`` self-bootstraps an empty table on any path, so a misdirected
    ``--db`` (or a genuinely empty registry) would otherwise re-hash zero rows and
    exit 0 — a silent pass that verifies nothing. A drift guard with no records to
    check must exit non-zero.
    """
    db_path = tmp_path / "empty_registry.db"
    # Materialize the file (and its empty table) without registering any IRI,
    # so the CLI's path-exists check passes and we hit the no-records branch.
    asyncio.run(ShardIRIRegistry(db_path).all_records())
    assert db_path.exists()

    result = runner.invoke(cli, ["verify-iris", "--db", str(db_path)])

    assert result.exit_code != 0, result.output


def test_help_exits_zero(runner) -> None:
    """Lazy-import discipline: heavy deps stay off `folio-insights --help`."""
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
