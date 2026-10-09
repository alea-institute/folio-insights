"""Shard endpoints: Phase 0 SSR stubs and the dependency-graph reads (drain U10).

Phase 0 stubs (D-09 SSR prototype, Gate 4 cold-page P95)
--------------------------------------------------------
Canned JSON that exercises the SSR critical-path contract, so Gate 4 measures
the SSR stack rather than store cost:

    GET /api/shard/{id}/core      → critical-path (awaited)
    GET /api/shard/{id}/deps      → streamed behind {#await}
    GET /api/shard/{id}/attests   → streamed behind {#await}

Dependency graph (drain U10; R12, R14)
--------------------------------------
Corpus-backed reads of a shard's place in the dependency web:

    GET /api/v1/corpus/{corpus}/shards/{iri}/graph?depth=N
        The shard, what it derives from (upstream, toward the kernel) and what
        derives from it (downstream, its dependents), up to ``N`` hops each way
        (default 3, at most 8). Every node carries its Tractarian path
        (``revision/tractarian.py``) beside its IRI, a short label, its type,
        epistemic status and kernel flag (with the kernel citation, such as
        ``VI 5.12.6``); every edge names the envelope field it comes from.
        Output is bounded: at most 500 nodes and 2000 edges; ``truncated``
        says when a bound cut anything off and ``truncated_reasons`` names
        which (``depth``, ``node_cap``, ``edge_cap``).
    GET /api/v1/corpus/{corpus}/shards/{iri}/derivation?max_depth=N
        The ``derivedFromKernel`` chains (``kernel/traversal.py``): every
        kernel shard the shard derives from with the shortest path to it, in
        the ``folio-insights/kernel-chain/v1`` format the ``kernel chain`` CLI
        exports, plus each chain node's Tractarian path. The walk visits at
        most 500 shards (the graph's node cap), nearest first; ``truncated``
        and ``truncated_reasons`` (``depth``, ``node_cap``) report a cut.

Every Tractarian path is the canonical one: the snapshot carries the corpus's
full shard revision history, replayed exactly as
``TractarianIndex.from_context`` replays it (sticky ordinals across a
reparent or a late-arriving parent), so the viewer, the CLI and the storage
context always agree.

Both reads take the IRI as one percent-encoded path segment (the viewer sends
``encodeURIComponent(iri)``), decoded exactly once from the raw request path,
and it must then be a shard URN (``urn:folio:shard/<32 hex>``) or an
``http(s)`` IRI, else 422 (an unencoded shard URN works too). An
IRI that is neither a shard of the corpus nor a packaged kernel IRI is 404; an
unknown corpus is 404.

Read-only by construction. Like the review API's proposal reads
(``api/services/proposals.load_registry_readonly``), the graph reads the
journal through a read-only SQLite connection and never opens a storage
context, the RDF projection or its lock, and never creates a storage root.
The current shards and the revision history are read inside one explicit
read transaction, so both come from one WAL snapshot. Reads stay open (drain
U5): the router carries ``WRITE_GUARD`` like every router, which passes GET.

Cost: a node's Tractarian path depends on the whole corpus's history, so the
parsed snapshot and its ``TractarianIndex`` are cached per corpus in a small
LRU keyed by the journal file and its head (position and op ID of the
corpus's last row); a request that finds the head unchanged costs one indexed
query. Every parse, graph build and derivation walk runs in a worker thread,
never on the event loop.
"""
from __future__ import annotations

import asyncio
import re
import sqlite3
import threading
from collections import OrderedDict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Query, Request

from api.auth import WRITE_GUARD

if TYPE_CHECKING:
    from folio_insights.kernel.catalog import KernelCatalog
    from folio_insights.revision.tractarian import TractarianIndex, TractarianRevision
    from folio_insights.shards import ShardEnvelope

router = APIRouter(dependencies=WRITE_GUARD)

# ---------------------------------------------------------------------------
# Phase 0 stubs (unchanged contract)
# ---------------------------------------------------------------------------

_PHASE0: list[str] = ["shard-phase0"]


@router.get("/api/shard/{shard_id}/core", tags=_PHASE0)
async def get_shard_core(shard_id: str) -> dict[str, Any]:
    """Critical-path payload — blocks SSR initial paint (Gate 4 budget <200ms)."""
    return {
        "iri": f"https://folio.openlegalstandard.org/shards/{shard_id}",
        "label": f"Shard {shard_id}",
        "confidence": 0.92,
        "corpus": "advocacy",
        "validFrom": "2022-01-01",
    }


@router.get("/api/shard/{shard_id}/deps", tags=_PHASE0)
async def get_shard_deps(shard_id: str) -> dict[str, Any]:
    """Dependencies payload — streams behind {#await} in SvelteKit."""
    return {
        "dependsOnAxiom": [
            f"https://folio.openlegalstandard.org/axioms/A{i:04d}"
            for i in range(5)
        ],
        "dependsOnDefinition": [
            f"https://folio.openlegalstandard.org/definitions/D{i:04d}"
            for i in range(3)
        ],
    }


@router.get("/api/shard/{shard_id}/attests", tags=_PHASE0)
async def get_shard_attests(shard_id: str) -> dict[str, Any]:
    """Attestations payload — streams."""
    return {
        "attestations": [
            {"signer": "did:example:abc", "validFrom": "2022-06-01"},
            {"signer": "did:example:def", "validFrom": "2023-01-01"},
        ],
    }


# ---------------------------------------------------------------------------
# Dependency graph: limits and IRI validation
# ---------------------------------------------------------------------------

GRAPH_FORMAT = "folio-insights/shard-graph/v1"
DEFAULT_GRAPH_DEPTH = 3
MAX_GRAPH_DEPTH = 8
#: Hard bound on the nodes one graph response carries (the root included), and on
#: the shards one derivation walk visits.
GRAPH_NODE_CAP = 500
#: Hard bound on the edges one graph response carries.
GRAPH_EDGE_CAP = 2000
#: Corpora whose parsed snapshot (and Tractarian index) stay cached.
SNAPSHOT_CACHE_SIZE = 4
#: Longest node label, in characters (an ellipsis included).
LABEL_MAX_CHARS = 140
DEFAULT_DERIVATION_DEPTH = 32  # kernel.traversal.DEFAULT_MAX_DEPTH
MAX_DERIVATION_DEPTH = 64
MAX_IRI_CHARS = 2048

SHARD_URN = re.compile(r"urn:folio:shard/[0-9a-f]{32}")
#: An absolute http(s) IRI: a host, then no whitespace or RFC 3987-excluded characters.
HTTP_IRI = re.compile(r"https?://[^\s/?#<>\"{}|\\^`]+(?:[/?#][^\s<>\"{}|\\^`]*)?")
#: Envelope fields that are dependency edges, in ``kernel.traversal``'s tie-break order.
EDGE_FIELDS: tuple[str, ...] = (
    "elaborates",
    "depends_on_axioms",
    "depends_on_definitions",
    "depends_on_precedents",
    "depends_on_shards",
)

Direction = Literal["root", "upstream", "downstream"]
_WALKS: tuple[Direction, Direction] = ("upstream", "downstream")


_RAW_IRI = re.compile(r"/corpus/[^/]+/shards/(.+)/(?:graph|derivation)$")


def request_iri(request: Request, routed: str) -> str:
    """The ``iri`` path segment percent-decoded exactly once.

    The IRI comes from the request's undecoded ``raw_path`` when the server
    provides it, so an http IRI that legitimately carries ``%xx`` escapes
    (sent as ``%25xx``) keeps them whatever the server's own path decoding
    does; ``routed`` (the router's already-decoded parameter) is the fallback.
    """
    raw = request.scope.get("raw_path")
    if isinstance(raw, bytes | bytearray):
        match = _RAW_IRI.search(bytes(raw).decode("latin-1"))
        if match is not None:
            return unquote(match.group(1), encoding="utf-8", errors="strict")
    return routed


def validate_shard_iri(raw: str) -> str:
    """``raw`` when it is a shard URN or an http(s) IRI, else a 422 refusal."""
    if (
        len(raw) <= MAX_IRI_CHARS
        and raw.isprintable()
        and (SHARD_URN.fullmatch(raw) or HTTP_IRI.fullmatch(raw))
    ):
        return raw
    raise HTTPException(
        status_code=422,
        detail="iri must be a shard URN (urn:folio:shard/<32 hex>) or an http(s) IRI",
    )


# ---------------------------------------------------------------------------
# Read-only corpus snapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CorpusSnapshot:
    """Every current shard of one corpus with its first commit position, in
    first-commit order (the input ``TractarianIndex`` takes), plus the
    corpus's shard revision history.

    ``revisions`` is every committed shard revision in commit order, batched
    as ``CorpusStorageContext.shard_revision_history`` batches them; ``None``
    stands for a history in which each shard was committed once, at its first
    position (a synthetic snapshot). ``head`` is the position of the corpus's
    last journal row when the snapshot was read (``-1`` when unknown)."""

    corpus: str
    entries: tuple[tuple[ShardEnvelope, int], ...]
    revisions: tuple[TractarianRevision, ...] | None = None
    head: int = -1
    _derived: dict[str, Any] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    def shards(self) -> dict[str, ShardEnvelope]:
        """The current shards by IRI (built once per snapshot)."""
        cached = self._derived.get("shards")
        if cached is None:
            cached = {shard.shard_iri: shard for shard, _ in self.entries}
            self._derived["shards"] = cached
        return cached

    @property
    def index(self) -> TractarianIndex:
        """The canonical ``TractarianIndex`` (built once per snapshot; call it
        off the event loop the first time)."""
        cached = self._derived.get("index")
        if cached is None:
            from folio_insights.revision.tractarian import TractarianIndex

            cached = TractarianIndex(self.entries, self.revisions)
            self._derived["index"] = cached
        return cached


class UnknownCorpus(LookupError):
    """The journal does not exist or holds no committed row for the corpus."""


@dataclass(frozen=True)
class _Head:
    """What a cached snapshot is valid for: the journal file's identity and the
    corpus's last row. The journal is append-only, so a corpus whose last
    position and op ID are unchanged holds exactly the rows it held."""

    journal: str
    device: int
    inode: int
    corpus: str
    position: int
    op_id: str


def _connect(journal: Path) -> sqlite3.Connection:
    # Autocommit mode: the transaction below is explicit, never implicit.
    return sqlite3.connect(
        f"{journal.resolve().as_uri()}?mode=ro", uri=True, isolation_level=None
    )


def _read_head(conn: sqlite3.Connection, journal: Path, corpus: str) -> _Head:
    """Check the schema version and read the corpus's head inside the open
    read transaction. Raises ``UnknownCorpus`` / ``UnsupportedStorageSchema``."""
    from folio_insights.storage.errors import UnsupportedStorageSchema
    from folio_insights.storage.journal import JOURNAL_SCHEMA_VERSION

    version = conn.execute(
        "SELECT value FROM storage_meta WHERE key = 'journal_schema_version'"
    ).fetchone()
    if version is not None and str(version[0]) != str(JOURNAL_SCHEMA_VERSION):
        raise UnsupportedStorageSchema("unsupported journal_schema_version")
    last = conn.execute(
        "SELECT position, op_id FROM journal WHERE corpus = ? ORDER BY position DESC LIMIT 1",
        (corpus,),
    ).fetchone()
    if last is None:
        raise UnknownCorpus(corpus)
    stat = journal.stat()
    return _Head(
        str(journal.resolve()), stat.st_dev, stat.st_ino, corpus, int(last[0]), str(last[1])
    )


def _read_rows(conn: sqlite3.Connection, corpus: str, head: int) -> CorpusSnapshot:
    """The current shards and every shard revision, inside the open read
    transaction (so both see the same committed rows)."""
    from folio_insights.revision.tractarian import TractarianRevision
    from folio_insights.shards.records import load_shard_record
    from folio_insights.storage.context import shard_revision_batch

    current = conn.execute(
        "SELECT j.payload, f.first FROM journal AS j JOIN ("
        " SELECT subject, MIN(position) AS first, MAX(position) AS last FROM journal"
        " WHERE corpus = ? AND kind = 'shard' GROUP BY subject"
        ") AS f ON j.subject = f.subject AND j.position = f.last "
        "WHERE j.corpus = ? AND j.kind = 'shard'",
        (corpus, corpus),
    ).fetchall()
    history = conn.execute(
        "SELECT position, subject, op_id, request_sha256, payload FROM journal "
        "WHERE corpus = ? AND kind = 'shard' ORDER BY position",
        (corpus,),
    ).fetchall()
    entries = [(load_shard_record(payload).shard, int(first)) for payload, first in current]
    entries.sort(key=lambda item: (item[1], item[0].shard_iri))
    revisions = tuple(
        TractarianRevision.from_payload(
            int(position), str(subject), bytes(payload), shard_revision_batch(op_id, request_sha)
        )
        for position, subject, op_id, request_sha, payload in history
    )
    return CorpusSnapshot(corpus, tuple(entries), revisions, head)


def _read(journal: Path, corpus: str, cached: Mapping[_Head, CorpusSnapshot] | None
          ) -> tuple[_Head, CorpusSnapshot]:
    if not journal.is_file():
        raise UnknownCorpus(corpus)
    conn = _connect(journal)
    try:
        # One read transaction: the head, the current shards and the history all
        # come from one WAL snapshot (two autocommit SELECTs could straddle a commit).
        conn.execute("BEGIN")
        try:
            head = _read_head(conn, journal, corpus)
            hit = cached.get(head) if cached is not None else None
            snapshot = hit if hit is not None else _read_rows(conn, corpus, head.position)
        finally:
            conn.execute("COMMIT")
    finally:
        conn.close()
    return head, snapshot


def read_corpus_snapshot(journal: Path, corpus: str) -> CorpusSnapshot:
    """``corpus``'s current shards in first-commit order and its full shard
    revision history, read-only and uncached.

    The same entries and revision rows ``CorpusStorageContext.
    shard_revision_history`` returns (tests pin the equality), read through a
    ``mode=ro`` SQLite connection inside one read transaction. Raises
    ``UnknownCorpus`` when the journal, or the corpus in it, does not exist,
    and ``UnsupportedStorageSchema`` for a journal schema version this code
    does not read. Blocking: call it from a worker thread.
    """
    return _read(journal, corpus, None)[1]


_cache: OrderedDict[_Head, CorpusSnapshot] = OrderedDict()
_cache_lock = threading.Lock()


def cached_corpus_snapshot(journal: Path, corpus: str) -> CorpusSnapshot:
    """``read_corpus_snapshot`` through a small LRU (``SNAPSHOT_CACHE_SIZE``
    corpora), with the snapshot's ``TractarianIndex`` built.

    Each call reads the corpus's head; an unchanged head (same journal file,
    same last position and op ID) returns the cached snapshot without reading
    a shard row, and a new commit replaces the entry. Blocking: call it from a
    worker thread.
    """
    with _cache_lock:
        view = dict(_cache)
    head, snapshot = _read(journal, corpus, view)
    snapshot.index  # noqa: B018 - build the Tractarian index here, off the event loop
    with _cache_lock:
        for stale in [k for k in _cache if k.corpus == corpus and k.journal == head.journal
                      and k != head]:
            del _cache[stale]
        _cache[head] = snapshot
        _cache.move_to_end(head)
        while len(_cache) > SNAPSHOT_CACHE_SIZE:
            _cache.popitem(last=False)
    return snapshot


def clear_snapshot_cache() -> None:
    """Drop every cached snapshot (tests, or after replacing a storage root)."""
    with _cache_lock:
        _cache.clear()


async def _snapshot(corpus: str) -> CorpusSnapshot:
    """The corpus snapshot, or an HTTP refusal: 404 unknown corpus, 503
    unreadable or misplaced storage (a malformed corpus ID is refused with 422
    by the app-wide dependency before the handler runs)."""
    from api.services import proposals as storage_svc
    from folio_insights.storage.journal import JOURNAL_FILENAME

    corpus = storage_svc.ledger_corpus(corpus)
    journal = storage_svc.storage_root() / JOURNAL_FILENAME
    try:
        return await asyncio.to_thread(cached_corpus_snapshot, journal, corpus)
    except UnknownCorpus:
        raise HTTPException(status_code=404, detail=f"no corpus {corpus!r}") from None
    except Exception as exc:  # noqa: BLE001 - an unreadable journal is "unavailable", never a 500
        raise HTTPException(
            status_code=503, detail=f"corpus storage unavailable ({type(exc).__name__})"
        ) from None


# ---------------------------------------------------------------------------
# Graph construction (pure)
# ---------------------------------------------------------------------------


def shard_label(shard: ShardEnvelope | None, latin: str | None = None) -> str:
    """A one-line label of at most ``LABEL_MAX_CHARS``: the shard's ``sense``,
    else its triple, else (an unseeded kernel maxim) the catalog's Latin."""
    if shard is not None:
        text = shard.sense.strip() or (
            f"{shard.triple.subject} {shard.triple.predicate} {shard.triple.object}"
        )
    else:
        text = latin or ""
    text = " ".join(text.split())
    if len(text) <= LABEL_MAX_CHARS:
        return text
    return text[: LABEL_MAX_CHARS - 1].rstrip() + "…"


def _out_edges(shard: ShardEnvelope) -> Iterable[tuple[str, str]]:
    """``(field, target)`` per dependency edge, in field order then list
    order; a target repeated within one field is reported once."""
    for name in EDGE_FIELDS:
        for target in dict.fromkeys(getattr(shard, name)):
            yield name, target


def _keep_edges(
    edges: list[dict[str, str]], tree: set[tuple[str, str]], cap: int
) -> list[dict[str, str]]:
    """At most ``cap`` of ``edges``, in their original order. The edges that
    placed a node (``tree``) each reserve one edge first, so parallel fields
    cannot crowd out another node's link to the walk. The rest follow in
    ``EDGE_FIELDS`` priority, then BFS order."""
    if len(edges) <= cap:
        return edges
    rank = {name: i for i, name in enumerate(EDGE_FIELDS)}
    order = sorted(
        range(len(edges)),
        key=lambda i: (rank[edges[i]["field"]], i),
    )
    reaching: dict[tuple[str, str], int] = {}
    for i in order:
        pair = (edges[i]["from"], edges[i]["to"])
        if pair in tree:
            reaching.setdefault(pair, i)
    reserved = set(reaching.values())
    keep = sorted((list(reaching.values()) + [i for i in order if i not in reserved])[:cap])
    return [edges[i] for i in keep]


def build_graph(
    entries: Sequence[tuple[ShardEnvelope, int]],
    root: str,
    *,
    depth: int = DEFAULT_GRAPH_DEPTH,
    node_cap: int = GRAPH_NODE_CAP,
    edge_cap: int = GRAPH_EDGE_CAP,
    catalog: KernelCatalog | None = None,
    index: TractarianIndex | None = None,
) -> dict[str, Any]:
    """The bounded dependency graph around ``root`` (see the module docstring).

    ``entries`` are a corpus's current shards with first commit positions;
    ``index`` is the corpus's canonical ``TractarianIndex`` (a route passes
    ``CorpusSnapshot.index``, built from the revision history). Without it the
    paths come from a history-less index over ``entries``, which is canonical
    only for a corpus in which every shard was committed once.

    The walk is breadth-first and level-synchronous in both directions: hop
    ``d`` upstream (the targets of a node's dependency fields) and then hop
    ``d`` downstream (shards whose dependency fields name a node) are placed
    before hop ``d + 1``, so the node cap drops the farthest nodes first. Each
    node is placed once, with the direction and distance that reached it
    first. A kernel node ends an upstream branch, as in ``kernel.traversal``.
    ``edges`` are the dependency edges between placed nodes (a dependent that
    also cites an ancestor shows both), in node then ``EDGE_FIELDS`` order, so
    a pair joined by two fields lists ``elaborates`` first; past ``edge_cap``
    the edges that placed a node are kept before the others. ``truncated``
    says a bound cut something off and ``truncated_reasons`` lists which, in
    the order ``depth``, ``node_cap``, ``edge_cap``.

    Raises ``KeyError`` when ``root`` is neither a shard in ``entries`` nor a
    kernel IRI, and ``ValueError`` for a negative depth or a cap below 1.
    """
    from folio_insights.kernel.catalog import load_catalog
    from folio_insights.revision.tractarian import TractarianIndex

    if depth < 0 or node_cap < 1 or edge_cap < 1:
        raise ValueError("depth must be >= 0 and node_cap, edge_cap >= 1")
    catalog = catalog or load_catalog()
    shards: dict[str, ShardEnvelope] = {s.shard_iri: s for s, _ in entries}
    kernel = catalog.manifest
    if root not in shards and root not in kernel:
        raise KeyError(root)

    dependents: dict[str, list[str]] = {}
    for shard, _ in entries:  # commit order => a deterministic dependent order
        for _name, target in _out_edges(shard):
            bucket = dependents.setdefault(target, [])
            if not bucket or bucket[-1] != shard.shard_iri:
                bucket.append(shard.shard_iri)

    def upstream(node: str) -> list[str]:
        shard = shards.get(node)
        if node in kernel or shard is None:
            return []  # a kernel ends a derivation; a dangling IRI has no fields
        return [target for _, target in _out_edges(shard)]

    def downstream(node: str) -> list[str]:
        return dependents.get(node, [])

    step = {"upstream": upstream, "downstream": downstream}
    placed: dict[str, tuple[Direction, int]] = {root: ("root", 0)}
    tree: set[tuple[str, str]] = set()  # (from, to) of the edge that placed a node
    frontier: dict[Direction, list[str]] = {"upstream": [root], "downstream": [root]}
    node_capped = False
    for hop in range(1, depth + 1):
        for direction in _WALKS:
            reached: list[str] = []
            for node in frontier[direction]:
                for neighbour in step[direction](node):
                    if neighbour in placed:
                        continue
                    if len(placed) >= node_cap:
                        node_capped = True
                        continue
                    placed[neighbour] = (direction, hop)
                    tree.add((node, neighbour) if direction == "upstream" else (neighbour, node))
                    reached.append(neighbour)
            frontier[direction] = reached
    # The depth bound cut something off iff a last frontier has an unplaced neighbour.
    depth_cut = any(
        neighbour not in placed
        for direction in _WALKS
        for node in frontier[direction]
        for neighbour in step[direction](node)
    )

    if index is None:
        index = TractarianIndex(entries)
    nodes: list[dict[str, Any]] = []
    for iri, (direction, distance) in placed.items():
        shard = shards.get(iri)
        maxim = catalog.by_iri(iri)
        nodes.append({
            "iri": iri,
            "tractarian_path": index.path_of(iri),
            "label": shard_label(shard, maxim.latin if maxim else None),
            "shard_type": shard.shard_type if shard else None,
            "epistemic_status": shard.epistemic_status if shard else None,
            "is_kernel": maxim is not None,
            "citation": maxim.citation if maxim else None,
            "citation_uri": maxim.citation_uri if maxim else None,
            "stored": shard is not None,
            "direction": direction,
            "distance": distance,
        })

    edges: list[dict[str, str]] = []
    for iri in placed:
        shard = shards.get(iri)
        if shard is None:
            continue
        for name, target in _out_edges(shard):
            if target in placed:
                edges.append({"from": iri, "to": target, "field": name})
    edge_capped = len(edges) > edge_cap
    edges = _keep_edges(edges, tree, edge_cap)

    reasons = [
        reason
        for reason, hit in (("depth", depth_cut), ("node_cap", node_capped),
                            ("edge_cap", edge_capped))
        if hit
    ]
    return {
        "format": GRAPH_FORMAT,
        "root": root,
        "depth": depth,
        "node_cap": node_cap,
        "edge_cap": edge_cap,
        "nodes": nodes,
        "edges": edges,
        "truncated": bool(reasons),
        "truncated_reasons": reasons,
    }


class _CappedShards(Mapping[str, "ShardEnvelope"]):
    """A by-IRI view of a corpus that lends the derivation walk at most ``cap``
    distinct shards. The walk is breadth-first, so the shards it is refused
    are the farthest; they are recorded in ``refused`` (not missing)."""

    def __init__(self, shards: Mapping[str, ShardEnvelope], cap: int) -> None:
        self._shards = shards
        self._cap = cap
        self.lent: set[str] = set()
        self.refused: set[str] = set()

    def get(self, iri: str, default: Any = None) -> Any:  # type: ignore[override]
        shard = self._shards.get(iri)
        if shard is None or iri in self.lent:
            return shard if shard is not None else default
        if len(self.lent) >= self._cap:
            self.refused.add(iri)
            return default
        self.lent.add(iri)
        return shard

    def __getitem__(self, iri: str) -> ShardEnvelope:
        shard = self.get(iri)
        if shard is None:
            raise KeyError(iri)
        return shard

    def __iter__(self) -> Iterator[str]:
        return iter(self._shards)

    def __len__(self) -> int:
        return len(self._shards)


def derivation_payload(
    snapshot: CorpusSnapshot,
    root: str,
    *,
    max_depth: int = DEFAULT_DERIVATION_DEPTH,
    node_cap: int = GRAPH_NODE_CAP,
    catalog: KernelCatalog | None = None,
) -> dict[str, Any]:
    """``root``'s kernel derivation chains (``kernel.export.chain_as_dict``),
    plus the corpus, the root's Tractarian path and every chain node's path
    (from ``snapshot.index``, the canonical index).

    The walk lends ``kernel.traversal`` at most ``node_cap`` distinct shards,
    nearest first; when it needed more, the chains through the farthest are
    missing, ``truncated`` is true and ``truncated_reasons`` holds
    ``node_cap`` (``depth`` when ``max_depth`` cut the walk). Blocking (it
    runs its own event loop for the walk): call it from a worker thread.

    Raises ``kernel.traversal.UnknownShard`` for an IRI that is neither a
    shard of the snapshot nor a kernel IRI.
    """
    from folio_insights.kernel.export import chain_as_dict
    from folio_insights.kernel.traversal import derivation_tree

    if node_cap < 1:
        raise ValueError("node_cap must be >= 1")
    source = _CappedShards(snapshot.shards(), node_cap)
    tree = asyncio.run(derivation_tree(source, root, max_depth=max_depth, catalog=catalog))
    depth_cut = tree.truncated
    if source.refused:
        tree = replace(
            tree,
            missing=tuple(m for m in tree.missing if m not in source.refused),
            truncated=True,
        )
    index = snapshot.index
    payload = chain_as_dict(tree, catalog=catalog)
    for node in payload["nodes"]:
        node["tractarian_path"] = index.path_of(node["iri"])
    payload["corpus"] = snapshot.corpus
    payload["tractarian_path"] = index.path_of(root)
    payload["node_cap"] = node_cap
    payload["truncated_reasons"] = [
        reason for reason, hit in (("depth", depth_cut), ("node_cap", bool(source.refused)))
        if hit
    ]
    return payload


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def _decoded(request: Request, routed: str) -> str:
    try:
        return request_iri(request, routed)
    except UnicodeDecodeError:
        raise HTTPException(status_code=422, detail="iri is not valid UTF-8") from None

_GRAPH: list[str] = ["shard-graph"]


@router.get("/api/v1/corpus/{corpus}/shards/{iri:path}/graph", tags=_GRAPH)
async def get_shard_graph(
    request: Request,
    corpus: str,
    iri: str,
    depth: int = Query(DEFAULT_GRAPH_DEPTH, ge=0, le=MAX_GRAPH_DEPTH),
) -> dict[str, Any]:
    """The bounded dependency graph around one shard, upstream and downstream."""
    root = validate_shard_iri(_decoded(request, iri))
    snapshot = await _snapshot(corpus)
    try:
        graph = await asyncio.to_thread(
            build_graph, snapshot.entries, root, depth=depth, node_cap=GRAPH_NODE_CAP,
            edge_cap=GRAPH_EDGE_CAP, index=snapshot.index,
        )
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"no shard {root!r} in corpus {snapshot.corpus!r}"
        ) from None
    return {"corpus": snapshot.corpus, **graph}


@router.get("/api/v1/corpus/{corpus}/shards/{iri:path}/derivation", tags=_GRAPH)
async def get_shard_derivation(
    request: Request,
    corpus: str,
    iri: str,
    max_depth: int = Query(DEFAULT_DERIVATION_DEPTH, ge=0, le=MAX_DERIVATION_DEPTH),
) -> dict[str, Any]:
    """Every kernel maxim the shard derives from, with the shortest chain to each."""
    from folio_insights.kernel.traversal import UnknownShard

    root = validate_shard_iri(_decoded(request, iri))
    snapshot = await _snapshot(corpus)
    try:
        return await asyncio.to_thread(
            derivation_payload, snapshot, root, max_depth=max_depth, node_cap=GRAPH_NODE_CAP
        )
    except UnknownShard:
        raise HTTPException(
            status_code=404, detail=f"no shard {root!r} in corpus {snapshot.corpus!r}"
        ) from None


__all__ = [
    "DEFAULT_DERIVATION_DEPTH",
    "DEFAULT_GRAPH_DEPTH",
    "EDGE_FIELDS",
    "GRAPH_EDGE_CAP",
    "GRAPH_FORMAT",
    "GRAPH_NODE_CAP",
    "LABEL_MAX_CHARS",
    "MAX_DERIVATION_DEPTH",
    "MAX_GRAPH_DEPTH",
    "SNAPSHOT_CACHE_SIZE",
    "CorpusSnapshot",
    "UnknownCorpus",
    "build_graph",
    "cached_corpus_snapshot",
    "clear_snapshot_cache",
    "derivation_payload",
    "read_corpus_snapshot",
    "request_iri",
    "router",
    "shard_label",
    "validate_shard_iri",
]
