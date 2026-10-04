"""STORAGE-02 / exit criterion 3: rdflib is adapter-only; every RDF store
write goes through pyoxigraph.

Two checks: a source scan (no rdflib or oxrdflib import anywhere in the
storage package or its CLI, and no rdflib graph backed by an Oxigraph store
anywhere in ``src``), and a runtime check over the whole storage life cycle
(writes, bulk load, queries, every export format, dump, snapshot, restore):
every rdflib graph constructed on the way is an in-memory adapter graph
(the governance SHACL subset validates through pyshacl, which needs one),
and none is backed by a persistent or Oxigraph store.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import folio_insights
import folio_insights.storage as storage_pkg
from folio_insights.storage import CorpusStorageContext

from tests.storage.conftest import genesis, shard

pytestmark = pytest.mark.storage

SRC = Path(folio_insights.__file__).parent
STORAGE_FILES = [*Path(storage_pkg.__file__).parent.rglob("*.py"), SRC / "storage_cli.py"]
RDFLIB_MODULES = ("rdflib", "oxrdflib")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


@pytest.mark.parametrize("path", STORAGE_FILES, ids=lambda p: p.name)
def test_storage_package_never_imports_rdflib(path: Path) -> None:
    assert not _imports(path) & set(RDFLIB_MODULES), path


def test_no_rdflib_graph_is_backed_by_an_oxigraph_store() -> None:
    """The only way rdflib could write into Oxigraph is the oxrdflib store
    plugin (``Graph(store="Oxigraph")``). Nothing in ``src`` imports it or
    passes a ``store=`` to an rdflib graph constructor."""
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        if "oxrdflib" in _imports(path):
            offenders.append(f"{path.relative_to(SRC)}: imports oxrdflib")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", getattr(node.func, "attr", None))
                in {"Graph", "Dataset", "ConjunctiveGraph"}
                and any(k.arg == "store" for k in node.keywords)
            ):
                offenders.append(f"{path.relative_to(SRC)}:{node.lineno}: rdflib store=")
    assert offenders == []


async def test_storage_life_cycle_uses_rdflib_only_as_in_memory_adapter(
    tmp_path: Path, admin, monkeypatch: pytest.MonkeyPatch
) -> None:
    import rdflib

    import folio_insights.storage._parallel as parallel
    from folio_insights.storage.backup import restore_storage, snapshot_storage
    from folio_insights.storage.dump import restore_ttl_dump, run_ttl_dump
    from folio_insights.storage.exports import ExportFormat, export_corpus

    stores: list[str] = []
    real_init = rdflib.Graph.__init__

    def recording_init(self, store="default", *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        stores.append(store if isinstance(store, str) else type(store).__name__)
        real_init(self, store, *args, **kwargs)

    monkeypatch.setattr(rdflib.Graph, "__init__", recording_init)
    monkeypatch.setattr(parallel, "_get_pool", lambda: None)  # keep every stage in-process

    root = tmp_path / "storage"
    ctx = await CorpusStorageContext.open(root, "corpus-a")
    try:
        await ctx.governance.append(genesis("corpus-a", admin))
        await ctx.shards.put(shard(1).shard_iri, shard(1))
        await ctx.bulk_load_shards([shard(n) for n in range(2, 2200)])
        await ctx.shards.put(shard(1).shard_iri, shard(1, sense="revised"))
        assert await ctx.query("ASK { ?s ?p ?o }", include_tbox=True)
        await ctx.rebuild_projection()
        await export_corpus(
            ctx, tmp_path / "export", list(ExportFormat),
            construct_query="CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }",
        )
    finally:
        await ctx.close()
    await run_ttl_dump(root, tmp_path / "repo", init=True)
    restore_ttl_dump(tmp_path / "repo", tmp_path / "rdf")
    snap = await snapshot_storage(root, tmp_path / "snap")
    await restore_storage(snap.path, tmp_path / "restored", rebuild_projection=True)

    # rdflib appeared only as the in-memory SHACL adapter (governance shape
    # validation inside the append path), never as a store.
    assert stores, "expected the governance SHACL adapter to run"
    assert set(stores) <= {"default", "Memory", "SimpleMemory"}, sorted(set(stores))
