"""Two corpora under one storage root never see each other's state."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from folio_insights.storage import CorpusIsolationError, CorpusStorageContext

from tests.storage.conftest import genesis, new_identity, shard

pytestmark = pytest.mark.storage


async def test_corpora_are_isolated(storage_root: Path, admin) -> None:
    other_admin = new_identity()
    a = await CorpusStorageContext.open(storage_root, "corpus-a")
    b = await CorpusStorageContext.open(storage_root, "corpus/b with spaces")
    try:
        await a.governance.append(genesis("corpus-a", admin))
        await b.governance.append(genesis("corpus/b with spaces", other_admin))
        sa, sb = shard(1), shard(2, depends_on_shards=[shard(1).shard_iri])
        await a.shards.put(sa.shard_iri, sa)
        await b.shards.put(sb.shard_iri, sb)

        # Positions are per corpus: each corpus has its own genesis row 0.
        assert await a.governance.latest_position("corpus-a") == 0
        assert await b.governance.latest_position("corpus/b with spaces") == 0
        assert (await a.status()).journal_head == 1
        assert (await b.status()).journal_head == 1

        assert await a.shards.get(sb.shard_iri) is None
        assert await b.shards.get(sa.shard_iri) is None
        assert [s.shard_iri async for s in a.shards.iter_shards()] == [sa.shard_iri]
        # B's dependent on A's IRI is invisible from A.
        assert await a.shards.dependents_of(sa.shard_iri) == []

        far = datetime(2100, 1, 1, tzinfo=UTC)
        assert set(await a.governance.query_active_roles_at("corpus-a", far)) == {admin.did}

        # SPARQL over A's dataset sees only A's graphs.
        rows = await a.query("SELECT DISTINCT ?s WHERE { ?s a <https://folio-insights.aleainstitute.ai/vocab/Shard> }")
        assert [r["s"].value for r in rows] == [sa.shard_iri]
        graphs = await a.query("SELECT DISTINCT ?g WHERE { GRAPH ?g { ?s ?p ?o } }")
        assert all("corpus%2Fb" not in r["g"].value for r in graphs)

        # A context bound to A refuses to read or write corpus B.
        with pytest.raises(CorpusIsolationError):
            await a.governance.latest_position("corpus/b with spaces")
        with pytest.raises(CorpusIsolationError):
            await a.governance.append(genesis("corpus/b with spaces", admin))
    finally:
        await a.close()
        await b.close()
