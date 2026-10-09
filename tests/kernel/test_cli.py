"""Drain U3 (R9-R11) — ``folio-insights kernel list|seed|chain`` via CliRunner.

Generated keyfiles in temp dirs; disposable corpus roots.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from click.testing import CliRunner
from pyoxigraph import RdfFormat, parse

from folio_insights.cli import cli
from folio_insights.identity.keys import generate_keypair, load_signing_key
from folio_insights.kernel.catalog import load_catalog
from folio_insights.storage import CorpusStorageContext

from tests.kernel.conftest import bootstrap_corpus
from tests.kernel.test_traversal import _ae4_shards
from tests.storage.conftest import Identity

FI = "https://folio-insights.aleainstitute.ai/vocab/"


def _admin(tmp_path: Path) -> tuple[Path, Identity]:
    key = tmp_path / "admin.jwk"
    did = generate_keypair(key)
    return key, Identity(load_signing_key(key), did)


def test_list_text_and_json() -> None:
    runner = CliRunner()
    text = runner.invoke(cli, ["kernel", "list", "--collection", "liber_sextus"])
    assert text.exit_code == 0, text.output
    lines = [line for line in text.stdout.splitlines() if line.startswith("VI 5.12.")]
    assert len(lines) == 88
    assert any(line.startswith("VI 5.12.6\t") and "Nemo potest ad impossibile obligari."
               in line for line in lines)
    assert sum("[single source]" in line for line in lines) == 4

    as_json = runner.invoke(cli, ["kernel", "list", "--json"])
    assert as_json.exit_code == 0, as_json.output
    data = json.loads(as_json.stdout)
    assert data["counts"]["liber_sextus"]["verified"] == 88
    assert data["counts"]["digest"]["verified"] == 211
    assert len(data["maxims"]) == 299 and data["excluded"] == []
    first = data["maxims"][0]
    assert first["shard_iri"] == load_catalog().maxims[0].shard_iri
    assert set(first["provenance"]) == {
        "source_url", "edition", "retrieved_at", "sha256", "verified_substring", "cross_checked",
    }

    digest = json.loads(runner.invoke(cli, ["kernel", "list", "--collection", "digest",
                                            "--json"]).stdout)
    assert list(digest["counts"]) == ["digest"] and len(digest["maxims"]) == 211


def test_seed_then_chain_end_to_end(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    key, admin = _admin(tmp_path)
    asyncio.run(bootstrap_corpus(root, "c", admin))
    runner = CliRunner()

    first = runner.invoke(cli, ["kernel", "seed", "c", "--signing-key", str(key),
                                "--corpus-root", str(root)])
    assert first.exit_code == 0, first.output
    report = json.loads(first.stdout)
    assert report["written"] == 299 and report["seeder_did"] == admin.did
    again = runner.invoke(cli, ["kernel", "seed", "c", "--signing-key", str(key),
                                "--root", str(root)])  # the --root alias
    assert again.exit_code == 0, again.output
    assert json.loads(again.stdout)["written"] == 0

    h, s = _ae4_shards()

    async def add() -> None:
        ctx = await CorpusStorageContext.open(root, "c")
        try:
            await ctx.ingest_shards([h, s], op_id="test:cli-ae4")
        finally:
            await ctx.close()

    asyncio.run(add())
    k6 = load_catalog().by_citation("VI 5.12.6").shard_iri

    as_json = runner.invoke(cli, ["kernel", "chain", "c", s.shard_iri, "--root", str(root)])
    assert as_json.exit_code == 0, as_json.output
    chain = json.loads(as_json.stdout)
    assert [d["path"] for d in chain["derivedFromKernel"]] == [[s.shard_iri, h.shard_iri, k6]]

    out = tmp_path / "chain.ttl"
    as_ttl = runner.invoke(cli, ["kernel", "chain", "c", s.shard_iri, "--format", "ttl",
                                 "--out", str(out), "--corpus-root", str(root)])
    assert as_ttl.exit_code == 0, as_ttl.output
    triples = {(t.subject.value, t.predicate.value, t.object.value)
               for t in parse(out.read_text("utf-8"), format=RdfFormat.TURTLE)}
    assert (s.shard_iri, FI + "elaborates", h.shard_iri) in triples
    assert (h.shard_iri, FI + "dependsOnAxiom", k6) in triples

    shallow = runner.invoke(cli, ["kernel", "chain", "c", s.shard_iri, "--max-depth", "1",
                                  "--root", str(root)])
    assert shallow.exit_code == 0
    assert json.loads(shallow.stdout)["kernel_reached"] is False

    unknown = runner.invoke(cli, ["kernel", "chain", "c", "urn:folio:shard/" + "f" * 32,
                                  "--root", str(root)])
    assert unknown.exit_code == 1 and "not a kernel IRI" in unknown.output


def test_seed_refusals(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    key, admin = _admin(tmp_path)
    asyncio.run(bootstrap_corpus(root, "c", admin))
    other = tmp_path / "other.jwk"
    generate_keypair(other)
    runner = CliRunner()

    stranger = runner.invoke(cli, ["kernel", "seed", "c", "--signing-key", str(other),
                                   "--root", str(root)])
    assert stranger.exit_code == 1 and "corpus_admin" in stranger.output

    no_key = runner.invoke(cli, ["kernel", "seed", "c", "--signing-key",
                                 str(tmp_path / "missing.jwk"), "--root", str(root)])
    assert no_key.exit_code == 1 and "no signing key" in no_key.output

    no_corpus = runner.invoke(cli, ["kernel", "seed", "nope", "--signing-key", str(key),
                                    "--root", str(root)])
    assert no_corpus.exit_code == 1 and "no corpus 'nope'" in no_corpus.output

    no_corpus_chain = runner.invoke(cli, ["kernel", "chain", "nope", "x", "--root", str(root)])
    assert no_corpus_chain.exit_code == 1


def test_seed_one_collection(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    key, admin = _admin(tmp_path)
    asyncio.run(bootstrap_corpus(root, "c", admin))
    result = CliRunner().invoke(cli, ["kernel", "seed", "c", "--signing-key", str(key),
                                      "--collection", "digest", "--root", str(root)])
    assert result.exit_code == 0, result.output
    report = json.loads(result.stdout)
    assert report["written"] == 211
    assert [c["collection"] for c in report["collections"]] == ["digest"]
