"""Exercise the roll-up's persisted P5 path without loading model backends."""
from __future__ import annotations

from folio_insights.bench.multiframework import MultiFrameworkCorpusGenerator, mint_shard, unit_iri
from folio_insights.bench.phase9_rollup import _Clock, _p5
from folio_insights.closure.declarations import load_declarations
from folio_insights.storage import CorpusStorageContext
from tests.storage.conftest import at, genesis, new_identity


async def test_rollup_p5_reads_persisted_and_reopened_closure(tmp_path):
    data = MultiFrameworkCorpusGenerator(seed=9, units_per_source=8).generate()
    source = data.source(data.planted.closed_source)
    iri_of = {unit.key: unit_iri(source.uri, unit.span) for unit in source.units}
    shards = [mint_shard(
        source, unit, framework_id=source.expected_framework,
        bfo_category="continuant_dependent", valid_time=None, iri_of=iri_of,
    ) for unit in source.units]
    admin = new_identity()
    async with await CorpusStorageContext.open(tmp_path, "p5-synthetic") as ctx:
        await ctx.governance.append(genesis(ctx.corpus, admin, at(0)))
        await ctx.ingest_shards(shards)
        principles = {}
        await _p5(ctx, data, _Clock(), principles, iri_of,
                  signing_key=admin.sk, did=admin.did)
        result = principles["P5"]
        assert result["membership_source"] == "persisted signed declaration"
        assert result["declared_scopes_in_store"] == []
        assert result["persisted_scopes"] == [result["scope"]]
        assert result["open_lacking"]["world_assumption"] == "open"
        assert result["open_lacking"]["count"] is None
        assert result["open_related"]["world_assumption"] == "open"
        assert result["closed_lacking"]["world_assumption"] == "closed"
        assert result["island_members"] == 10
        assert result["closed_lacking"]["count"] == 5
        assert result["closed_related"]["world_assumption"] == "closed"
        assert result["closed_related"]["count"] == 1
        assert result["reopened_lacking"] == result["closed_lacking"]
        assert len((await load_declarations(ctx)).active) == 1
