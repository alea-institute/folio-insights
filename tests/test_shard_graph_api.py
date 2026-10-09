"""Drain U10 (R12, R14) — the shard dependency-graph and derivation API.

``GET /api/v1/corpus/{corpus}/shards/{iri}/graph`` and ``.../derivation``
over a disposable corpus: the Liber Sextus kernel seeded by a generated
corpus admin (the U3 fixtures), plus synthetic shards in the AE4 shape:

    S --elaborates--> H --depends_on_axioms--> K6 (VI 5.12.6)
    D --depends_on_shards--> S              (a dependent of S)
    F                                        (free-standing, no kernel)

Every identity is freshly generated and every shard is synthetic; nothing is
book-derived. The pure graph builder is also exercised directly for the
depth and node-cap bounds on larger synthetic webs.
"""
from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from api import auth
from api import main as api_main
from api.main import app
from api.routes import shard as shard_routes
from api.routes.shard import (
    GRAPH_FORMAT,
    LABEL_MAX_CHARS,
    build_graph,
    read_corpus_snapshot,
    shard_label,
)
from folio_insights.config import get_settings
from folio_insights.kernel.catalog import load_catalog
from folio_insights.kernel.seed import seed_kernel
from folio_insights.shards import HypothesisShard, ShardEnvelope, SimpleAssertionShard, Triple
from folio_insights.storage import CorpusStorageContext
from folio_insights.storage.journal import JOURNAL_FILENAME

from tests.kernel.conftest import bootstrap_corpus
from tests.shards.conftest import _sample_shard
from tests.storage.conftest import new_identity

CORPUS = "graph-corpus"
K6 = load_catalog().by_citation("VI 5.12.6").shard_iri  # Nemo potest ad impossibile obligari.
K6_URI = "urn:folio:kernel:liber-sextus:5.12.6"


def _iri(n: int) -> str:
    return f"urn:folio:shard/{n:032x}"


def _shard(n: int, cls: type[ShardEnvelope] = SimpleAssertionShard, **fields) -> ShardEnvelope:
    fields.setdefault("sense", f"synthetic shard {n}")
    return _sample_shard(cls, shard_iri=_iri(n), framework_id="us.common_law", **fields)


H = _shard(0xA1, HypothesisShard, epistemic_status="hypothesis", depends_on_axioms=[K6])
S = _shard(0xA2, elaborates=[H.shard_iri])
D = _shard(0xA3, depends_on_shards=[S.shard_iri])
F = _shard(0xA4)


@dataclass(frozen=True)
class GraphCorpus:
    root: Path


@pytest.fixture(scope="module")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> GraphCorpus:
    """One corpus: the Liber Sextus kernel, then H, S, D, F (shared per module)."""
    root = tmp_path_factory.mktemp("graph") / "storage"
    admin = new_identity()

    async def build() -> None:
        await bootstrap_corpus(root, CORPUS, admin)
        await seed_kernel(root, CORPUS, signing_key=admin.sk, collections=("liber_sextus",))
        ctx = await CorpusStorageContext.open(root, CORPUS)
        try:
            await ctx.ingest_shards([H, S], op_id="test:u10:chain")
            await ctx.ingest_shards([D, F], op_id="test:u10:dependents")
        finally:
            await ctx.close()

    asyncio.run(build())
    return GraphCorpus(root)


@pytest.fixture
def client(corpus: GraphCorpus, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(api_main, "_corpus_root", corpus.root)
    return TestClient(app)


def _graph_url(iri: str, corpus_name: str = CORPUS) -> str:
    return f"/api/v1/corpus/{corpus_name}/shards/{quote(iri, safe='')}/graph"


def _derivation_url(iri: str, corpus_name: str = CORPUS) -> str:
    return f"/api/v1/corpus/{corpus_name}/shards/{quote(iri, safe='')}/derivation"


def _by_iri(body: dict) -> dict[str, dict]:
    return {n["iri"]: n for n in body["nodes"]}


def _edges(body: dict) -> set[tuple[str, str, str]]:
    return {(e["from"], e["to"], e["field"]) for e in body["edges"]}


# ── /graph: the AE4 chain with its dependent ────────────────────────────────


def test_graph_shows_the_chain_to_the_kernel_and_the_dependents(client: TestClient) -> None:
    resp = client.get(_graph_url(S.shard_iri))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["format"] == GRAPH_FORMAT and body["corpus"] == CORPUS
    assert body["root"] == S.shard_iri and body["depth"] == 3
    assert body["truncated"] is False
    nodes = _by_iri(body)
    assert list(nodes) == [S.shard_iri, H.shard_iri, D.shard_iri, K6]  # BFS, root first

    assert (nodes[S.shard_iri]["direction"], nodes[S.shard_iri]["distance"]) == ("root", 0)
    assert (nodes[H.shard_iri]["direction"], nodes[H.shard_iri]["distance"]) == ("upstream", 1)
    assert (nodes[K6]["direction"], nodes[K6]["distance"]) == ("upstream", 2)
    assert (nodes[D.shard_iri]["direction"], nodes[D.shard_iri]["distance"]) == ("downstream", 1)

    kernel = nodes[K6]
    assert kernel["is_kernel"] is True and kernel["stored"] is True
    assert kernel["citation"] == "VI 5.12.6" and kernel["citation_uri"] == K6_URI
    assert kernel["epistemic_status"] == "authority_only"
    assert kernel["shard_type"] == "simple_assertion"
    assert kernel["label"].startswith("Nemo potest ad impossibile")

    hyp = nodes[H.shard_iri]
    assert hyp["is_kernel"] is False and hyp["citation"] is None
    assert hyp["shard_type"] == "hypothesis" and hyp["epistemic_status"] == "hypothesis"
    assert hyp["label"] == "synthetic shard 161"

    assert _edges(body) == {
        (S.shard_iri, H.shard_iri, "elaborates"),
        (H.shard_iri, K6, "depends_on_axioms"),
        (D.shard_iri, S.shard_iri, "depends_on_shards"),
    }


def test_graph_tractarian_paths_nest_under_the_kernel(client: TestClient) -> None:
    """R12 through the API: S's path sits under H's, H's under the kernel's;
    the kernel and a shard with no primary parent are top-level."""
    nodes = _by_iri(client.get(_graph_url(S.shard_iri)).json())
    k6, h, s, d = (nodes[i]["tractarian_path"] for i in (K6, H.shard_iri, S.shard_iri,
                                                           D.shard_iri))
    assert k6 is not None and "." not in k6  # kernel shards form the top level
    assert h.startswith(k6 + ".") and h.count(".") == 1
    assert s.startswith(h + ".") and s.count(".") == 2
    assert d is not None and "." not in d  # depends_on_shards is not a path parent


def test_graph_of_a_kernel_shard_lists_its_dependents(client: TestClient) -> None:
    body = client.get(_graph_url(K6)).json()
    nodes = _by_iri(body)
    assert list(nodes) == [K6, H.shard_iri, S.shard_iri, D.shard_iri]
    assert [nodes[i]["distance"] for i in nodes] == [0, 1, 2, 3]
    assert {nodes[i]["direction"] for i in list(nodes)[1:]} == {"downstream"}
    assert body["truncated"] is False


def test_graph_accepts_a_raw_unencoded_shard_urn(client: TestClient) -> None:
    resp = client.get(f"/api/v1/corpus/{CORPUS}/shards/{S.shard_iri}/graph")
    assert resp.status_code == 200 and resp.json()["root"] == S.shard_iri


# ── /graph: bounds ──────────────────────────────────────────────────────────


def test_graph_depth_bounds_the_walk_and_reports_truncation(client: TestClient) -> None:
    one = client.get(_graph_url(S.shard_iri), params={"depth": 1}).json()
    assert list(_by_iri(one)) == [S.shard_iri, H.shard_iri, D.shard_iri]
    assert one["truncated"] is True  # K6 lies beyond hop 1
    assert _edges(one) == {
        (S.shard_iri, H.shard_iri, "elaborates"),
        (D.shard_iri, S.shard_iri, "depends_on_shards"),
    }

    zero = client.get(_graph_url(S.shard_iri), params={"depth": 0}).json()
    assert [n["iri"] for n in zero["nodes"]] == [S.shard_iri]
    assert zero["edges"] == [] and zero["truncated"] is True

    assert client.get(_graph_url(F.shard_iri), params={"depth": 0}).json()["truncated"] is False


@pytest.mark.parametrize("depth", ["-1", "9", "three"])
def test_graph_depth_outside_0_to_8_is_refused(client: TestClient, depth: str) -> None:
    assert client.get(_graph_url(S.shard_iri), params={"depth": depth}).status_code == 422


def test_graph_maximum_depth_is_accepted(client: TestClient) -> None:
    body = client.get(_graph_url(S.shard_iri), params={"depth": 8}).json()
    assert len(body["nodes"]) == 4 and body["truncated"] is False


def test_graph_node_cap_truncates_the_response(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shard_routes, "GRAPH_NODE_CAP", 2)
    body = client.get(_graph_url(S.shard_iri)).json()
    assert [n["iri"] for n in body["nodes"]] == [S.shard_iri, H.shard_iri]
    assert body["truncated"] is True and body["node_cap"] == 2


def test_default_node_cap_is_500_and_holds_on_a_wide_web() -> None:
    hub = _shard(1)
    spokes = [_shard(10_000 + i, depends_on_shards=[hub.shard_iri]) for i in range(600)]
    entries = [(hub, 1)] + [(s, i + 2) for i, s in enumerate(spokes)]
    body = build_graph(entries, hub.shard_iri, depth=1)
    assert body["node_cap"] == 500 and len(body["nodes"]) == 500
    assert body["truncated"] is True
    assert len(body["edges"]) == 499
    # The farthest-first rule: nodes are the hub then spokes in commit order.
    assert [n["iri"] for n in body["nodes"][1:4]] == [s.shard_iri for s in spokes[:3]]


def test_cap_keeps_nearer_hops_before_farther_ones() -> None:
    """Level-synchronous BFS: every hop-1 node is placed before any hop-2 node."""
    root = _shard(1)
    near = [_shard(100 + i, depends_on_shards=[root.shard_iri]) for i in range(3)]
    far = [_shard(200 + i, depends_on_shards=[near[0].shard_iri]) for i in range(3)]
    entries = [(s, i) for i, s in enumerate([root, *far, *near])]  # far commits first
    body = build_graph(entries, root.shard_iri, depth=2, node_cap=5)
    assert [n["distance"] for n in body["nodes"]] == [0, 1, 1, 1, 2]
    assert body["truncated"] is True


def test_graph_is_cycle_safe_on_a_legacy_cycle() -> None:
    a_iri, b_iri = _iri(0xC1), _iri(0xC2)
    a = _shard(0xC1, depends_on_shards=[b_iri])
    b = _shard(0xC2, depends_on_shards=[a_iri])
    body = build_graph([(a, 1), (b, 2)], a_iri, depth=8)
    assert [n["iri"] for n in body["nodes"]] == [a_iri, b_iri]
    assert _edges(body) == {(a_iri, b_iri, "depends_on_shards"),
                            (b_iri, a_iri, "depends_on_shards")}
    assert body["truncated"] is False


def test_graph_reports_dangling_and_unseeded_kernel_targets() -> None:
    dangling = _iri(0xDEAD)
    k1 = load_catalog().by_citation("VI 5.12.1")
    x = _shard(0xD1, depends_on_axioms=[k1.shard_iri], depends_on_shards=[dangling])
    nodes = _by_iri(build_graph([(x, 1)], x.shard_iri))
    assert nodes[dangling]["stored"] is False and nodes[dangling]["is_kernel"] is False
    assert nodes[dangling]["tractarian_path"] is None and nodes[dangling]["label"] == ""
    unseeded = nodes[k1.shard_iri]
    assert unseeded["stored"] is False and unseeded["is_kernel"] is True
    assert unseeded["citation"] == "VI 5.12.1"
    assert unseeded["label"] == shard_label(None, k1.latin) and unseeded["label"]


def test_graph_is_deterministic(client: TestClient) -> None:
    first = client.get(_graph_url(D.shard_iri)).json()
    assert client.get(_graph_url(D.shard_iri)).json() == first


# ── /graph and /derivation: refusals ────────────────────────────────────────


@pytest.mark.parametrize("make_url", [_graph_url, _derivation_url])
def test_unknown_iri_is_404(client: TestClient, make_url) -> None:
    resp = client.get(make_url(_iri(0xFFFF)))
    assert resp.status_code == 404 and "no shard" in resp.json()["detail"]


@pytest.mark.parametrize("make_url", [_graph_url, _derivation_url])
def test_unknown_corpus_is_404(client: TestClient, make_url) -> None:
    resp = client.get(make_url(S.shard_iri, "no-such-corpus"))
    assert resp.status_code == 404 and resp.json()["detail"] == "no corpus 'no-such-corpus'"


@pytest.mark.parametrize("make_url", [_graph_url, _derivation_url])
@pytest.mark.parametrize("bad", [
    "urn:folio:shard/XYZ",
    "urn:folio:shard/" + "a" * 31,
    "urn:folio:shard/" + "A" * 32,
    "urn:other:thing",
    "ftp://example.org/x",
    "https://exa mple.org/x",
    "https://",
    "https://example.org/" + "a" * 2100,
])
def test_malformed_iri_is_422(client: TestClient, make_url, bad: str) -> None:
    assert client.get(make_url(bad)).status_code == 422


def test_http_iri_is_accepted_and_404_when_absent(client: TestClient) -> None:
    resp = client.get(_graph_url("https://folio.openlegalstandard.org/shards/x%20y/graph"))
    assert resp.status_code == 404
    assert "https://folio.openlegalstandard.org/shards/x%20y/graph" in resp.json()["detail"]


def test_malformed_corpus_id_is_422(client: TestClient) -> None:
    """The app-wide corpus-ID dependency (``api/corpus_ids.py``) refuses it first."""
    assert client.get(_graph_url(S.shard_iri, ".hidden")).status_code == 422
    assert client.get(_derivation_url(S.shard_iri, ".hidden")).status_code == 422


def test_absent_storage_root_is_404_and_never_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "never-created"
    monkeypatch.setattr(api_main, "_corpus_root", root)
    resp = TestClient(app).get(_graph_url(S.shard_iri))
    assert resp.status_code == 404
    assert not root.exists()


def test_unreadable_journal_is_503(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "broken"
    root.mkdir()
    (root / JOURNAL_FILENAME).write_bytes(b"this is not a sqlite database" * 100)
    monkeypatch.setattr(api_main, "_corpus_root", root)
    resp = TestClient(app).get(_graph_url(S.shard_iri))
    assert resp.status_code == 503 and "unavailable" in resp.json()["detail"]


# ── /derivation ─────────────────────────────────────────────────────────────


def test_derivation_exports_the_ae4_chain_with_paths(client: TestClient) -> None:
    resp = client.get(_derivation_url(S.shard_iri))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["format"] == "folio-insights/kernel-chain/v1"
    assert body["corpus"] == CORPUS and body["root"] == S.shard_iri
    assert body["kernel_reached"] is True and body["truncated"] is False
    [chain] = body["derivedFromKernel"]
    assert chain["kernel_iri"] == K6 and chain["citation"] == "VI 5.12.6"
    assert chain["path"] == [S.shard_iri, H.shard_iri, K6] and chain["depth"] == 2
    assert chain["edges"] == [
        {"from": S.shard_iri, "to": H.shard_iri, "field": "elaborates"},
        {"from": H.shard_iri, "to": K6, "field": "depends_on_axioms"},
    ]
    paths = {n["iri"]: n["tractarian_path"] for n in body["nodes"]}
    assert set(paths) == {S.shard_iri, H.shard_iri, K6}
    assert body["tractarian_path"] == paths[S.shard_iri]
    assert paths[S.shard_iri].startswith(paths[K6] + ".")


def test_derivation_through_a_dependency_and_bounded_depth(client: TestClient) -> None:
    [chain] = client.get(_derivation_url(D.shard_iri)).json()["derivedFromKernel"]
    assert chain["path"] == [D.shard_iri, S.shard_iri, H.shard_iri, K6]
    cut = client.get(_derivation_url(D.shard_iri), params={"max_depth": 2}).json()
    assert cut["derivedFromKernel"] == [] and cut["truncated"] is True
    assert client.get(_derivation_url(D.shard_iri), params={"max_depth": 65}).status_code == 422


def test_derivation_of_a_free_standing_shard_reaches_no_kernel(client: TestClient) -> None:
    body = client.get(_derivation_url(F.shard_iri)).json()
    assert body["kernel_reached"] is False and body["derivedFromKernel"] == []
    assert body["tractarian_path"] is not None


# ── read-only and open reads ────────────────────────────────────────────────


def _tree_digest(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*")) if p.is_file()
    }


def test_graph_reads_write_nothing(client: TestClient, corpus: GraphCorpus) -> None:
    before = _tree_digest(corpus.root)
    for iri in (S.shard_iri, H.shard_iri, K6, D.shard_iri):
        assert client.get(_graph_url(iri)).status_code == 200
        assert client.get(_derivation_url(iri)).status_code == 200
    assert _tree_digest(corpus.root) == before


def test_snapshot_matches_the_storage_context(corpus: GraphCorpus) -> None:
    async def via_context() -> list[tuple[str, int]]:
        ctx = await CorpusStorageContext.open(corpus.root, CORPUS)
        try:
            return [(s.shard_iri, pos) for s, pos in await ctx.shards_in_commit_order()]
        finally:
            await ctx.close()

    snapshot = read_corpus_snapshot(corpus.root / JOURNAL_FILENAME, CORPUS)
    assert [(s.shard_iri, pos) for s, pos in snapshot.entries] == asyncio.run(via_context())
    assert len(snapshot.entries) == 4 + sum(
        1 for m in load_catalog() if m.collection == "liber_sextus"
    )


def test_graph_reads_need_no_operator_token(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """U5 policy: reads stay open even in ``required`` mode, off loopback, tokenless."""
    tokens = tmp_path / "secrets" / "api-tokens"
    tokens.parent.mkdir(mode=0o700)
    tokens.write_text(auth.entry_line(auth.generate_token(), "alice", "operator") + "\n")
    tokens.chmod(0o600)
    monkeypatch.setenv(auth.AUTH_MODE_ENV, auth.MODE_REQUIRED)
    monkeypatch.setenv(auth.TOKENS_FILE_ENV, str(tokens))
    monkeypatch.setattr(auth, "is_local_request", lambda request: False)
    get_settings.cache_clear()
    auth.reset_cache()
    remote = TestClient(app, base_url="http://api.example.org", client=("203.0.113.7", 40000))
    assert remote.get(_graph_url(S.shard_iri)).status_code == 200
    assert remote.get(_derivation_url(S.shard_iri)).status_code == 200
    # ... while a write on the same app is still refused.
    assert remote.post("/api/v1/corpora", json={"name": "x"}).status_code == 401


def test_graph_routes_are_reads_in_the_route_table() -> None:
    """The routes are GET-only, so U5's mutating-route sweep never needs them."""
    from tests.api.test_auth import _api_routes

    graph_routes = {
        path: methods for path, methods, _ in _api_routes(app) if "/shards/" in path
    }
    assert graph_routes == {
        "/api/v1/corpus/{corpus}/shards/{iri:path}/graph": {"GET"},
        "/api/v1/corpus/{corpus}/shards/{iri:path}/derivation": {"GET"},
    }


def test_phase0_stub_routes_still_answer(client: TestClient) -> None:
    assert client.get("/api/shard/abc/core").json()["label"] == "Shard abc"
    assert len(client.get("/api/shard/abc/deps").json()["dependsOnAxiom"]) == 5
    assert len(client.get("/api/shard/abc/attests").json()["attestations"]) == 2


# ── labels ──────────────────────────────────────────────────────────────────


def test_labels_are_short_single_line_and_fall_back_to_the_triple() -> None:
    long = _shard(0xE1, sense="word " * 80)
    label = shard_label(long)
    assert len(label) == LABEL_MAX_CHARS and label.endswith("…") and "  " not in label
    assert shard_label(_shard(0xE2, sense="  a\n\tb  ")) == "a b"
    bare = _shard(0xE3, sense=" ", triple=Triple(subject="s1", predicate="p1", object="o1"))
    assert shard_label(bare) == "s1 p1 o1"
    assert shard_label(None, None) == ""


def test_iri_segment_that_is_not_utf8_is_422(client: TestClient) -> None:
    assert client.get(f"/api/v1/corpus/{CORPUS}/shards/https%3A%2F%2Fx.org%2F%FF/graph"
                      ).status_code == 422


# ── review fixes: canonical (sticky) paths, snapshot cache, caps ────────────

STICKY = "sticky-corpus"


def _sticky_corpus(root: Path) -> dict[str, str | None]:
    """A corpus whose canonical paths need the revision history: C is reparented
    under A after D's root ordinal was taken, X waits on a dangling parent P that
    arrives later. Returns ``TractarianIndex.from_context``'s path per shard."""
    from folio_insights.revision.tractarian import TractarianIndex

    from tests.storage.conftest import shard as plain

    a, c, x, d, p = (_iri(0x51), _iri(0x52), _iri(0x53), _iri(0x54), _iri(0x55))

    async def build() -> dict[str, str | None]:
        ctx = await CorpusStorageContext.open(root, STICKY)
        try:
            await ctx.ingest_shards([plain(0x51)])
            await ctx.ingest_shards([plain(0x52)])
            await ctx.ingest_shards([plain(0x53, elaborates=[p])])
            await ctx.shards.put(c, plain(0x52, elaborates=[a]), op_id="reparent-c")
            await ctx.ingest_shards([plain(0x54)])
            await ctx.ingest_shards([plain(0x55)])
            index = await TractarianIndex.from_context(ctx)
            return {iri: index.path_of(iri) for iri in (a, c, x, d, p)}
        finally:
            await ctx.close()

    return asyncio.run(build())


def test_graph_and_derivation_paths_equal_the_storage_context_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P1: the API replays the same revision history as ``from_context`` (sticky
    ordinals), so a reparent or a late parent never renumbers paths in the viewer."""
    from folio_insights.revision.tractarian import TractarianIndex

    root = tmp_path / "storage"
    canonical = _sticky_corpus(root)
    snapshot = read_corpus_snapshot(root / JOURNAL_FILENAME, STICKY)
    # The history matters on this corpus: a history-less index numbers differently.
    naive = TractarianIndex(snapshot.entries)
    assert {i: naive.path_of(i) for i in canonical} != canonical

    monkeypatch.setattr(api_main, "_corpus_root", root)
    client = TestClient(app)
    for iri, path in canonical.items():
        graph = client.get(_graph_url(iri, STICKY), params={"depth": 8}).json()
        shown = {n["iri"]: n["tractarian_path"] for n in graph["nodes"]}
        assert shown[iri] == path
        assert all(shown[i] == canonical[i] for i in shown if i in canonical), shown
        derivation = client.get(_derivation_url(iri, STICKY)).json()
        assert derivation["tractarian_path"] == path


def test_snapshot_history_matches_the_storage_context(tmp_path: Path) -> None:
    """The snapshot's revision rows are ``shard_revision_history``'s rows."""
    root = tmp_path / "storage"
    _sticky_corpus(root)

    async def via_context():
        ctx = await CorpusStorageContext.open(root, STICKY)
        try:
            return await ctx.shard_revision_history()
        finally:
            await ctx.close()

    entries, rows = asyncio.run(via_context())
    snapshot = read_corpus_snapshot(root / JOURNAL_FILENAME, STICKY)
    assert [(s.shard_iri, p) for s, p in snapshot.entries] == [
        (s.shard_iri, p) for s, p in entries
    ]
    assert [(r.position, r.iri, r.batch) for r in snapshot.revisions] == [
        (r.position, r.iri, r.batch) for r in rows
    ]


def test_snapshot_cache_serves_repeats_and_invalidates_on_a_new_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P2: repeated reads reuse one parsed snapshot until the journal head moves."""
    from tests.storage.conftest import shard as plain

    root = tmp_path / "storage"
    _sticky_corpus(root)
    journal = root / JOURNAL_FILENAME
    shard_routes.clear_snapshot_cache()
    first = shard_routes.cached_corpus_snapshot(journal, STICKY)
    assert shard_routes.cached_corpus_snapshot(journal, STICKY) is first

    monkeypatch.setattr(api_main, "_corpus_root", root)
    client = TestClient(app)
    late = _iri(0x56)
    assert client.get(_graph_url(late, STICKY)).status_code == 404

    async def commit() -> None:
        ctx = await CorpusStorageContext.open(root, STICKY)
        try:
            await ctx.ingest_shards([plain(0x56, elaborates=[_iri(0x51)])])
        finally:
            await ctx.close()

    asyncio.run(commit())
    fresh = shard_routes.cached_corpus_snapshot(journal, STICKY)
    assert fresh is not first and fresh.head > first.head
    assert late in fresh.shards()
    resp = client.get(_graph_url(late, STICKY))
    assert resp.status_code == 200 and _by_iri(resp.json())[late]["tractarian_path"] == "1.2"


def test_snapshot_cache_is_bounded() -> None:
    assert 1 <= shard_routes.SNAPSHOT_CACHE_SIZE <= 16


def test_cpu_work_runs_off_the_event_loop(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P2: snapshot parsing, the graph build and the derivation walk never run on
    the event loop thread."""
    seen: list[tuple[str, bool]] = []

    def on_loop() -> bool:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return False
        return True

    def spy(name, fn):
        def wrapper(*args, **kwargs):
            seen.append((name, on_loop()))
            return fn(*args, **kwargs)
        return wrapper

    shard_routes.clear_snapshot_cache()
    for name in ("cached_corpus_snapshot", "build_graph", "derivation_payload"):
        monkeypatch.setattr(shard_routes, name, spy(name, getattr(shard_routes, name)))
    assert client.get(_graph_url(S.shard_iri)).status_code == 200
    assert client.get(_derivation_url(S.shard_iri)).status_code == 200
    assert {name for name, _ in seen} == {
        "cached_corpus_snapshot", "build_graph", "derivation_payload"
    }
    assert not any(loop for _, loop in seen), seen


def _dense_web(n: int) -> list[tuple[ShardEnvelope, int]]:
    """``n`` shards, each depending on every earlier one: n(n-1)/2 edges."""
    shards: list[ShardEnvelope] = []
    for i in range(n):
        shards.append(_shard(0x7000 + i, depends_on_shards=[s.shard_iri for s in shards]))
    return [(s, i) for i, s in enumerate(shards)]


def test_edges_are_capped_and_every_placed_node_keeps_its_reaching_edge() -> None:
    """P2: the response carries at most ``GRAPH_EDGE_CAP`` edges, says so, and keeps
    the edge that placed each node so the drawn graph stays connected."""
    entries = _dense_web(80)  # 3,160 edges
    root = entries[0][0].shard_iri
    body = build_graph(entries, root, depth=1)
    assert len(body["nodes"]) == 80
    assert body["edge_cap"] == shard_routes.GRAPH_EDGE_CAP == 2000
    assert len(body["edges"]) == 2000
    assert body["truncated"] is True and body["truncated_reasons"] == ["edge_cap"]
    touched = {e["from"] for e in body["edges"]} | {e["to"] for e in body["edges"]}
    assert touched == {n["iri"] for n in body["nodes"]}
    # Every non-root node was placed by an edge to the root; all of them survive.
    assert {e["from"] for e in body["edges"] if e["to"] == root} == touched - {root}


def test_parallel_fields_do_not_displace_other_nodes_reaching_edges() -> None:
    root = _shard(1)
    neighbours = [
        _shard(100 + i, **{
            field: [root.shard_iri]
            for field in (shard_routes.EDGE_FIELDS if i < 401 else ("depends_on_shards",))
        })
        for i in range(499)
    ]
    body = build_graph([(s, i) for i, s in enumerate([root, *neighbours])],
                       root.shard_iri, depth=1)
    assert len(body["nodes"]) == 500
    assert len(body["edges"]) == 2000
    assert body["truncated_reasons"] == ["edge_cap"]
    assert {e["from"] for e in body["edges"] if e["to"] == root.shard_iri} == {
        s.shard_iri for s in neighbours
    }


def test_truncation_reasons_name_each_bound() -> None:
    root = _shard(1)
    near = [_shard(100 + i, depends_on_shards=[root.shard_iri]) for i in range(3)]
    far = [_shard(200 + i, depends_on_shards=[near[0].shard_iri]) for i in range(3)]
    entries = [(s, i) for i, s in enumerate([root, *near, *far])]
    assert build_graph(entries, root.shard_iri, depth=1)["truncated_reasons"] == ["depth"]
    capped = build_graph(entries, root.shard_iri, depth=2, node_cap=5)
    assert capped["truncated_reasons"] == ["node_cap"]
    whole = build_graph(entries, root.shard_iri, depth=2)
    assert whole["truncated"] is False and whole["truncated_reasons"] == []


def test_edge_field_order_puts_the_tractarian_parent_first() -> None:
    """A pair joined by two fields lists ``elaborates`` before ``depends_on_shards``."""
    parent = _shard(0x91)
    child = _shard(0x92, elaborates=[parent.shard_iri], depends_on_shards=[parent.shard_iri])
    body = build_graph([(parent, 0), (child, 1)], child.shard_iri)
    assert [e["field"] for e in body["edges"]] == ["elaborates", "depends_on_shards"]


def test_derivation_walk_is_capped_and_reports_it() -> None:
    """P3: /derivation bounds the nodes it walks, farthest first, and says so."""
    from api.routes.shard import CorpusSnapshot, derivation_payload

    fan = [_shard(0x8000 + i) for i in range(599)]
    last = _shard(0x8000 + 599, depends_on_axioms=[K6])
    root = _shard(0x9000, depends_on_shards=[s.shard_iri for s in [*fan, last]])
    entries = tuple((s, i) for i, s in enumerate([root, *fan, last]))
    snapshot = CorpusSnapshot("synthetic", entries)

    capped = derivation_payload(snapshot, root.shard_iri)
    assert capped["node_cap"] == shard_routes.GRAPH_NODE_CAP
    assert capped["truncated"] is True and capped["truncated_reasons"] == ["node_cap"]
    assert capped["derivedFromKernel"] == [] and capped["missing"] == []
    assert len(capped["nodes"]) <= shard_routes.GRAPH_NODE_CAP

    whole = derivation_payload(snapshot, root.shard_iri, node_cap=1000)
    assert whole["truncated"] is False and whole["truncated_reasons"] == []
    [chain] = whole["derivedFromKernel"]
    assert chain["path"] == [root.shard_iri, last.shard_iri, K6]


def test_derivation_depth_truncation_reason(client: TestClient) -> None:
    cut = client.get(_derivation_url(D.shard_iri), params={"max_depth": 2}).json()
    assert cut["truncated_reasons"] == ["depth"]
    assert cut["node_cap"] == shard_routes.GRAPH_NODE_CAP
