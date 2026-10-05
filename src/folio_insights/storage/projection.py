"""Oxigraph named-graph projection of the journal (Phase 13 KTD1, KTD2, KTD5).

The projection is derived state. ``apply`` turns a contiguous batch of journal
rows into ONE SPARQL update that also moves the corpus watermark, and
pyoxigraph applies an update transactionally, so the projected quads and the
applied-position watermark can never disagree. Replaying a row is idempotent:
a shard revision replaces its subject's quads, and governance quads are set
semantics.

Named graphs per corpus (``<corpus-ns><quoted corpus>``):

* ``<corpus graph>``             — current shard state (ABox), the Gate-2 layout.
* ``<corpus graph>/governance``  — governance events.
* ``<TBOX_GRAPH>``                — the shared TBox (the ``folio_insights.vocab``
  TTL files), one graph for every corpus in the store. It is derived from
  code, not the journal: loaded with deterministic blank-node labels and
  reloaded when the vocabulary bytes change.
* ``urn:folio-insights:storage:projection`` — per-corpus watermark, the
  payload sha256 of the journal row at the watermark, and the adapter
  version (storage-internal; never in the corpus dataset a query sees).

Watermark integrity (U4): the watermark records the journal position, the
``payload_sha256`` of the row at that position, and a chain digest over every
applied row's (position, op_id, payload_sha256, committed_at). Recovery
recomputes the chain from the journal, so a journal restored with different
content anywhere in the applied prefix (not only at the watermark row) is
detected and the corpus graphs are rebuilt instead of trusted.

Apply paths. A normal batch is ONE SPARQL update (quads + watermark,
transactional). A large catch-up whose rows only add new subjects (a bulk
load into an empty or disjoint projection) uses ``Store.bulk_load`` for the
quads and then moves the watermark in a second, transactional update. That
pair is not atomic, and it does not need to be: the projection lock excludes
every reader and writer while it runs, and a crash between the two leaves
quads past the watermark that the next catch-up replays idempotently (a
shard row replaces its subject's quads; governance quads are sets).

Writes go through pyoxigraph only (never rdflib). RocksDB allows one open
handle per path per process, and readers cannot open it while another process
writes, so every open is guarded by an exclusive ``flock`` on
``<root>/projection.lock`` and the handle is dropped before the lock is
released. The adapter version is part of the stored state: a version change
rebuilds the corpus graphs from the journal.
"""
from __future__ import annotations

import dataclasses
import fcntl
import hashlib
import json
import os
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import quote

from pyoxigraph import (
    BlankNode,
    Literal,
    NamedNode,
    Quad,
    QueryBoolean,
    QuerySolutions,
    QueryTriples,
    RdfFormat,
)
from pyoxigraph import parse as rdf_parse

from folio_insights.revision.content_edit import canonical_content_hash
from folio_insights.shards import ShardEnvelope, load_shard_record
from folio_insights.storage.errors import ProjectionLockTimeout, UnsupportedStorageSchema
from folio_insights.storage.journal import KIND_GOVERNANCE, KIND_SHARD, JournalRow
from folio_insights.store import PyoxigraphStore
from folio_insights.store.pyoxigraph_store import ServiceClauseBlocked
from folio_insights.vocab._constants import BFO_CATEGORY_SPINE_CLASS, FI_PREFIX, framework_iri

PROJECTION_DIRNAME = "projection.oxigraph"
PROJECTION_LOCKNAME = "projection.lock"
# Adapter versions (a change rebuilds every corpus projection from the journal):
#   1 — Phase 13 layout.
#   2 — Phase 9 U0: fi:framework as an IRI (fi:frameworkId kept), fi:speechAct,
#       fi:bfoCategory and fi:subjectBfoClass on shards; promotion citations as
#       the declared fi:citedIri. Journal bytes and signatures are untouched.
PROJECTION_ADAPTER_VERSION = 2

CORPUS_NS = "https://folio-insights.aleainstitute.ai/corpus/"
META_GRAPH = NamedNode("urn:folio-insights:storage:projection")
TBOX_GRAPH = NamedNode("https://folio-insights.aleainstitute.ai/tbox")
_TBOX_META = NamedNode("urn:folio-insights:storage:projection#tbox")

_XSD = "http://www.w3.org/2001/XMLSchema#"
_RDF_TYPE = NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
_PROV_ACTIVITY = NamedNode("http://www.w3.org/ns/prov#Activity")
_XSD_INT = NamedNode(f"{_XSD}integer")
_XSD_DOUBLE = NamedNode(f"{_XSD}double")
_XSD_DT = NamedNode(f"{_XSD}dateTime")
_XSD_URI = NamedNode(f"{_XSD}anyURI")
_XSD_BOOL = NamedNode(f"{_XSD}boolean")

DEPENDENCY_PREDICATES: dict[str, str] = {
    "depends_on_axioms": "dependsOnAxiom",
    "depends_on_definitions": "dependsOnDefinition",
    "depends_on_precedents": "dependsOnPrecedent",
    "depends_on_shards": "dependsOnShard",
}


def fi(local: str) -> NamedNode:
    return NamedNode(f"{FI_PREFIX}{local}")


def corpus_graph(corpus: str) -> NamedNode:
    return NamedNode(f"{CORPUS_NS}{quote(corpus, safe='')}")


def governance_graph(corpus: str) -> NamedNode:
    return NamedNode(f"{corpus_graph(corpus).value}/governance")


def iri_or_literal(value: str) -> NamedNode | Literal:
    """A NamedNode when ``value`` is a valid IRI, else an ``xsd:anyURI`` literal."""
    try:
        return NamedNode(value)
    except ValueError:
        return Literal(value, datatype=_XSD_URI)


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in rest)


def _dt(value: datetime) -> Literal:
    return Literal(value.isoformat(), datatype=_XSD_DT)


# ── RDF adapters (versioned by PROJECTION_ADAPTER_VERSION) ────────────────


def shard_triples(
    shard: ShardEnvelope, *, journal_position: int
) -> list[tuple[NamedNode, NamedNode, Any]]:
    """Shard -> RDF. Subject-only triples so a revision can replace them all."""
    s = NamedNode(shard.shard_iri)
    out: list[tuple[NamedNode, NamedNode, Any]] = [
        (s, _RDF_TYPE, fi("Shard")),
        (s, fi("shardType"), Literal(shard.shard_type)),
        (s, fi("schemaVersion"), Literal(str(shard.schema_version), datatype=_XSD_INT)),
        (s, fi("vocabVersion"), Literal(shard.vocab_version)),
        (s, fi("provenanceHash"), Literal(shard.provenance_hash)),
        (s, fi("contentHash"), Literal(canonical_content_hash(shard))),
        (s, fi("sourceUri"), iri_or_literal(shard.source_uri)),
        (s, fi("sourceSpan"), Literal(shard.source_span)),
        (s, fi("extractedAt"), _dt(shard.extracted_at)),
        (s, fi("transactionTime"), _dt(shard.transaction_time)),
        (s, fi("firstExtractorDid"), Literal(shard.first_extractor_did)),
        (s, fi("sense"), Literal(shard.sense)),
        (s, fi("reference"), Literal(shard.reference)),
        (s, fi("tripleSubject"), Literal(shard.triple.subject)),
        (s, fi("triplePredicate"), Literal(shard.triple.predicate)),
        (s, fi("tripleObject"), Literal(shard.triple.object)),
        (s, fi("epistemicStatus"), Literal(shard.epistemic_status)),
        (s, fi("frameworkId"), Literal(shard.framework_id)),
        (s, fi("speechAct"), Literal(shard.speech_act)),
        (s, fi("bfoCategory"), Literal(shard.bfo_category)),
        (s, fi("subjectBfoClass"), NamedNode(BFO_CATEGORY_SPINE_CLASS[shard.bfo_category])),
        (s, fi("confidence"), Literal(repr(float(shard.confidence)), datatype=_XSD_DOUBLE)),
        (s, fi("contested"), Literal("true" if shard.contested else "false", datatype=_XSD_BOOL)),
        (s, fi("journalPosition"), Literal(str(journal_position), datatype=_XSD_INT)),
        (s, fi("signatureCount"), Literal(str(len(shard.signatures)), datatype=_XSD_INT)),
        (s, fi("contentEditCount"), Literal(str(len(shard.content_edits)), datatype=_XSD_INT)),
    ]
    if shard.framework_id:  # an empty identifier has no framework IRI
        out.append((s, fi("framework"), NamedNode(framework_iri(shard.framework_id))))
    if shard.valid_time_start is not None:
        out.append((s, fi("validTimeStart"), _dt(shard.valid_time_start)))
    if shard.valid_time_end is not None:
        out.append((s, fi("validTimeEnd"), _dt(shard.valid_time_end)))
    if shard.supersedes is not None:
        out.append((s, fi("supersedes"), iri_or_literal(shard.supersedes)))
    if shard.superseded_by is not None:
        out.append((s, fi("supersededBy"), iri_or_literal(shard.superseded_by)))
    strategy = getattr(shard, "reconciliation_strategy", None)
    if isinstance(strategy, str):
        out.append((s, fi("reconciliationStrategy"), Literal(strategy)))
    for field_name, predicate in DEPENDENCY_PREDICATES.items():
        for target in getattr(shard, field_name):
            out.append((s, fi(predicate), iri_or_literal(target)))
    for sig in shard.signatures:
        out.append((s, fi("signedBy"), Literal(sig.did)))
    return out


# Event keys whose camelCase name would be undeclared; they map to the term the
# vocabulary (and the Phase 7 promotion shape) already declares.
GOVERNANCE_PREDICATE_OVERRIDES: dict[str, str] = {
    "cited_iris": "citedIri",
    "policy": "cascadePolicy",
}


def governance_event_iri(corpus: str, governance_position: int) -> NamedNode:
    return NamedNode(f"{governance_graph(corpus).value}/event/{governance_position}")


def governance_triples(
    corpus: str, event_json: dict[str, Any], *, journal_position: int
) -> list[tuple[NamedNode, NamedNode, Any]]:
    """Governance event -> RDF (a ``prov:Activity`` with its event fields)."""
    position = int(event_json["position"])
    e = governance_event_iri(corpus, position)
    sig = event_json["signature"]
    out: list[tuple[NamedNode, NamedNode, Any]] = [
        (e, _RDF_TYPE, fi("GovernanceEvent")),
        (e, _RDF_TYPE, _PROV_ACTIVITY),
        (e, fi("action"), Literal(event_json["action"])),
        (e, fi("logPosition"), Literal(str(position), datatype=_XSD_INT)),
        (e, fi("journalPosition"), Literal(str(journal_position), datatype=_XSD_INT)),
        (e, fi("signerDid"), Literal(sig["did"])),
        (e, fi("signatureOverHash"), Literal(sig["over_content_hash"])),
    ]
    if sig.get("signed_at"):
        out.append((e, fi("signedAt"), Literal(sig["signed_at"], datatype=_XSD_DT)))
    for key, value in event_json.items():
        if key in {"corpus", "position", "signature", "action"} or value is None:
            continue
        values = value if isinstance(value, list) else [value]
        for item in values:
            if key.endswith("_iri") or key == "cited_iris":
                obj: Any = iri_or_literal(str(item))
            else:
                obj = Literal(str(item))
            out.append((e, fi(GOVERNANCE_PREDICATE_OVERRIDES.get(key) or _camel(key)), obj))
    return out


# ── SPARQL text builders (terms serialize as N-Triples, valid in SPARQL) ──


def _triples_block(triples: Iterable[tuple[Any, Any, Any]]) -> str:
    return " ".join(f"{s} {p} {o} ." for s, p, o in triples)


ShardLoader = Callable[[JournalRow], ShardEnvelope]


def load_row_shard(row: JournalRow) -> ShardEnvelope:
    """The validated shard of a journal shard row (full U17 adapter)."""
    return load_shard_record(row.payload).shard


def row_triples(
    corpus: str, row: JournalRow, *, load: ShardLoader = load_row_shard
) -> tuple[NamedNode, str | None, list[tuple[Any, Any, Any]]]:
    """``(graph, replaced subject IRI or None, triples)`` for one journal row."""
    if row.kind == KIND_SHARD:
        shard = load(row)
        return (
            corpus_graph(corpus),
            shard.shard_iri,
            shard_triples(shard, journal_position=row.position),
        )
    if row.kind == KIND_GOVERNANCE:
        event_json = json.loads(row.payload)
        return (
            governance_graph(corpus),
            None,
            governance_triples(corpus, event_json, journal_position=row.position),
        )
    raise UnsupportedStorageSchema(  # pragma: no cover - the journal CHECK forbids this
        f"unknown journal row kind {row.kind!r}"
    )


# Journal chain digest: d(-1) = CHAIN_GENESIS, d(i) = sha256(d(i-1) || JSON of
# [position, op_id, payload_sha256, committed_at]) for every row 0..i. The
# projection records d(watermark); recovery recomputes it from the journal, so
# ANY difference in the applied prefix (not just the watermark row) is found.
CHAIN_GENESIS = hashlib.sha256(b"folio-insights/journal-chain/v1").hexdigest()


def chain_step(previous: str, position: int, op_id: str, payload_sha256: str,
               committed_at: str) -> str:
    link = json.dumps([position, op_id, payload_sha256, committed_at], separators=(",", ":"))
    return hashlib.sha256(bytes.fromhex(previous) + link.encode("utf-8")).hexdigest()


def chain_over(previous: str, rows: Iterable[Any]) -> str:
    digest = previous
    for row in rows:
        digest = chain_step(digest, row.position, row.op_id, row.payload_sha256, row.committed_at)
    return digest


def _watermark_update(
    node: NamedNode, watermark: int, payload_sha256: str, chain_digest: str
) -> str:
    wm = Literal(str(watermark), datatype=_XSD_INT)
    ver = Literal(str(PROJECTION_ADAPTER_VERSION), datatype=_XSD_INT)
    sha = Literal(payload_sha256)
    chain = Literal(chain_digest)
    return (
        f"DELETE WHERE {{ GRAPH {META_GRAPH} {{ {node} {fi('appliedPosition')} ?w }} }} ;\n"
        f"DELETE WHERE {{ GRAPH {META_GRAPH} {{ {node} {fi('appliedPayloadSha256')} ?h }} }} ;\n"
        f"DELETE WHERE {{ GRAPH {META_GRAPH} {{ {node} {fi('appliedChainDigest')} ?c }} }} ;\n"
        f"DELETE WHERE {{ GRAPH {META_GRAPH} {{ {node} {fi('adapterVersion')} ?v }} }} ;\n"
        f"INSERT DATA {{ GRAPH {META_GRAPH} {{ {node} {fi('appliedPosition')} {wm} . "
        f"{node} {fi('appliedPayloadSha256')} {sha} . "
        f"{node} {fi('appliedChainDigest')} {chain} . "
        f"{node} {fi('adapterVersion')} {ver} . }} }}"
    )


# ── shared TBox (derived from the vocab package, not the journal) ─────────

_TBOX_FILES: tuple[str, ...] = (
    "predicates.ttl",
    "classes.ttl",
    "bfo_spine.ttl",
    "bfo_mapping.ttl",
    "shapes.ttl",
)


def tbox_sources() -> list[tuple[str, bytes]]:
    """The vocab TTL files that make up the shared TBox, in load order."""
    pkg = files("folio_insights.vocab")
    return [(name, (pkg / name).read_bytes()) for name in _TBOX_FILES]


def tbox_digest(sources: Sequence[tuple[str, bytes]] | None = None) -> str:
    h = hashlib.sha256()
    for name, data in sources if sources is not None else tbox_sources():
        h.update(name.encode("utf-8") + b"\0" + hashlib.sha256(data).digest())
    return h.hexdigest()


def tbox_quads(sources: Sequence[tuple[str, bytes]] | None = None) -> list[Quad]:
    """TBox quads in ``TBOX_GRAPH`` with deterministic blank-node labels.

    Blank nodes are relabelled ``<file stem>-<n>`` in document order, so the
    same vocabulary always yields byte-identical dumps (nightly diffs stay
    empty when nothing changed). Parsed with pyoxigraph, never rdflib.
    """
    out: list[Quad] = []
    for name, data in sources if sources is not None else tbox_sources():
        stem = name.removesuffix(".ttl").replace("_", "-")
        labels: dict[str, BlankNode] = {}

        def relabel(term: Any, _labels: dict[str, BlankNode] = labels, _stem: str = stem) -> Any:
            if isinstance(term, BlankNode):
                if term.value not in _labels:
                    _labels[term.value] = BlankNode(f"tbox-{_stem}-{len(_labels)}")
                return _labels[term.value]
            return term

        for triple in rdf_parse(data, format=RdfFormat.TURTLE):
            out.append(
                Quad(
                    relabel(triple.subject),
                    triple.predicate,
                    relabel(triple.object),
                    TBOX_GRAPH,
                )
            )
    return out


# ── projection handle ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProjectionState:
    watermark: int
    adapter_version: int | None
    payload_sha256: str | None = None
    chain_digest: str | None = None


# Rows applied per transactional update, and the size from which a catch-up
# of add-only rows uses ``Store.bulk_load`` (U4 bulk-load path).
BULK_LOAD_MIN_ROWS = 2048


class ProjectionHandle:
    """An open projection store. Use only while holding ``ProjectionLock``."""

    def __init__(self, root: Path) -> None:
        self._wrapper = PyoxigraphStore(path=str(root / PROJECTION_DIRNAME))

    @property
    def store(self) -> Any:
        """The pyoxigraph ``Store`` (storage-internal: exports and backups)."""
        return self._wrapper.store

    def state(self, corpus: str) -> ProjectionState:
        node = corpus_graph(corpus)
        rows = [
            (sol["w"], sol["v"], sol["h"], sol["c"])
            for sol in self._wrapper.store.query(
                f"SELECT ?w ?v ?h ?c WHERE {{ GRAPH {META_GRAPH} {{ "
                f"{node} {fi('appliedPosition')} ?w . "
                f"OPTIONAL {{ {node} {fi('adapterVersion')} ?v }} "
                f"OPTIONAL {{ {node} {fi('appliedPayloadSha256')} ?h }} "
                f"OPTIONAL {{ {node} {fi('appliedChainDigest')} ?c }} }} }}"
            )
        ]
        if not rows:
            return ProjectionState(watermark=-1, adapter_version=None)
        w, v, h, c = rows[0]
        return ProjectionState(
            watermark=int(w.value),
            adapter_version=None if v is None else int(v.value),
            payload_sha256=None if h is None else h.value,
            chain_digest=None if c is None else c.value,
        )

    def reset(self, corpus: str) -> None:
        """Drop the corpus graphs and watermark (adapter-version rebuild)."""
        node = corpus_graph(corpus)
        self._wrapper.store.update(
            f"DROP SILENT GRAPH {corpus_graph(corpus)} ;\n"
            f"DROP SILENT GRAPH {governance_graph(corpus)} ;\n"
            f"DELETE WHERE {{ GRAPH {META_GRAPH} {{ {node} ?p ?o }} }}"
        )

    # ── TBox ──────────────────────────────────────────────────────────────

    def tbox_digest(self) -> str | None:
        rows = list(
            self._wrapper.store.quads_for_pattern(
                _TBOX_META, fi("tboxDigest"), None, META_GRAPH
            )
        )
        return rows[0].object.value if rows else None

    def ensure_tbox(self) -> bool:
        """Load (or reload) the shared TBox graph when the vocab changed.

        Ordered so every crash point is safe: the digest is removed first and
        written last, so an interrupted load is redone on the next catch-up.
        Returns whether the graph was (re)loaded.
        """
        sources = tbox_sources()
        digest = tbox_digest(sources)
        if self.tbox_digest() == digest:
            return False
        store = self._wrapper.store
        store.update(
            f"DELETE WHERE {{ GRAPH {META_GRAPH} {{ {_TBOX_META} {fi('tboxDigest')} ?d }} }} ;\n"
            f"DROP SILENT GRAPH {TBOX_GRAPH}"
        )
        store.extend(tbox_quads(sources))
        store.update(
            f"INSERT DATA {{ GRAPH {META_GRAPH} {{ {_TBOX_META} {fi('tboxDigest')} "
            f"{Literal(digest)} }} }}"
        )
        return True

    # ── journal replay ────────────────────────────────────────────────────

    def apply(
        self,
        corpus: str,
        rows: Sequence[JournalRow],
        *,
        load: ShardLoader = load_row_shard,
        parallel: bool = False,
    ) -> int:
        """Apply contiguous ``rows`` and move the watermark to the last one.

        ``load`` turns a shard row into its validated envelope (the context
        passes a cache of the envelopes it just validated for this commit).
        """
        state = self.state(corpus)
        if not rows:
            return state.watermark
        current = state.watermark
        if current < 0:
            previous_chain = CHAIN_GENESIS
        elif state.chain_digest is None:
            raise UnsupportedStorageSchema(
                f"projection for {corpus!r} has no journal chain digest; rebuild it"
            )
        else:
            previous_chain = state.chain_digest
        if rows[0].position != current + 1:
            raise UnsupportedStorageSchema(
                f"projection replay for {corpus!r} expected position {current + 1}, "
                f"got {rows[0].position}"
            )
        for prev, nxt in zip(rows, rows[1:]):
            if nxt.position != prev.position + 1:
                raise UnsupportedStorageSchema("projection replay rows are not contiguous")

        store = self._wrapper.store
        # Each shard row replaces ALL of its subject's quads, so within one
        # batch only the last revision of a subject determines the result:
        # earlier revisions in the batch are skipped (their positions still
        # count toward the watermark). Deletes touch only quads that existed
        # before the batch and run before every insert. Besides being less
        # work, this never inserts and then deletes the same quad inside one
        # update, which pyoxigraph 0.5.7's RocksDB backend fails on ("Not able
        # to find the string ... in the string store").
        abox = corpus_graph(corpus)
        last_index: dict[str, int] = {}
        for index, row in enumerate(rows):
            if row.kind == KIND_SHARD:  # a shard row's journal subject is its IRI
                last_index[row.subject] = index
        effective = [
            row
            for index, row in enumerate(rows)
            if row.kind != KIND_SHARD or last_index[row.subject] == index
        ]
        # An empty ABox graph (a first load) has no subject to probe for.
        abox_empty = next(store.quads_for_pattern(None, None, None, abox), None) is None
        existing = (
            []
            if abox_empty
            else sorted(
                subject
                for subject in last_index
                if next(store.quads_for_pattern(NamedNode(subject), None, None, abox), None)
                is not None
            )
        )

        last = rows[-1]
        node = corpus_graph(corpus)
        chain = chain_over(previous_chain, rows)
        if not existing and len(rows) >= BULK_LOAD_MIN_ROWS:
            # Add-only catch-up: non-transactional bulk load, then the watermark
            # (see the module docstring for why the pair is crash-safe).
            from folio_insights.storage._parallel import (
                PARALLEL_MIN_ITEMS,
                map_chunks,
                render_chunk,
            )

            if parallel and len(effective) >= PARALLEL_MIN_ITEMS:
                slim = [
                    r if r.original_bytes is None else dataclasses.replace(r, original_bytes=None)
                    for r in effective
                ]
                nquads = b"".join(map_chunks(render_chunk, slim, corpus))
            else:
                nquads = "".join(
                    f"{s} {p} {o} {graph} .\n"
                    for graph, _, triples in (
                        row_triples(corpus, r, load=load) for r in effective
                    )
                    for s, p, o in triples
                ).encode("utf-8")
            store.bulk_load(nquads, format=RdfFormat.N_QUADS)
            store.update(_watermark_update(node, last.position, last.payload_sha256, chain))
            return last.position

        ops = [f"DELETE WHERE {{ GRAPH {abox} {{ <{subject}> ?p ?o }} }}" for subject in existing]
        by_graph: dict[str, list[str]] = {}
        for row in effective:
            graph, _, triples = row_triples(corpus, row, load=load)
            by_graph.setdefault(str(graph), []).append(_triples_block(triples))
        ops.extend(
            f"INSERT DATA {{ GRAPH {graph} {{ {' '.join(blocks)} }} }}"
            for graph, blocks in by_graph.items()
        )
        ops.append(_watermark_update(node, last.position, last.payload_sha256, chain))
        store.update(" ;\n".join(ops))
        return last.position

    def query(
        self, corpus: str, sparql: str, *, include_tbox: bool = False
    ) -> Any:
        """Read-only SPARQL over this corpus's graphs only; results materialized.

        ``include_tbox`` adds the shared TBox graph to both the default graph
        and the named graphs, so ``GRAPH ?g`` returns ABox, governance and
        TBox partitions.
        """
        _refuse_service(sparql)
        graphs = corpus_graphs(corpus, include_tbox=include_tbox)
        raw = self._wrapper.store.query(sparql, default_graph=graphs, named_graphs=graphs)
        if isinstance(raw, QueryBoolean):
            return bool(raw)
        if isinstance(raw, QuerySolutions):
            names = [v.value for v in raw.variables]
            return [{name: sol[name] for name in names} for sol in raw]
        if isinstance(raw, QueryTriples):
            return list(raw)
        return raw  # pragma: no cover

    def graph_quads(self, graph: NamedNode) -> list[Quad]:
        """Every quad of one named graph (materialized)."""
        return list(self._wrapper.store.quads_for_pattern(None, None, None, graph))

    def backup(self, target: Path) -> None:
        """RocksDB backup of the whole projection into a new ``target`` dir."""
        self._wrapper.store.flush()
        self._wrapper.store.backup(str(target))

    def dependents(self, corpus: str, shard_iri: str) -> list[str]:
        """Shard IRIs in ``corpus`` whose ``depends_on_*`` lists name ``shard_iri``."""
        target = iri_or_literal(shard_iri)
        alt = Literal(shard_iri, datatype=_XSD_URI)
        path = "|".join(str(fi(p)) for p in DEPENDENCY_PREDICATES.values())
        sparql = (
            f"SELECT DISTINCT ?s WHERE {{ GRAPH {corpus_graph(corpus)} {{ "
            f"VALUES ?t {{ {target} {alt} }} ?s {path} ?t }} }} ORDER BY ?s"
        )
        return [sol["s"].value for sol in self._wrapper.store.query(sparql)]

    def dependency_edges(self, corpus: str) -> tuple[list[str], list[tuple[str, str, str]]]:
        """One bulk adjacency read (Phase 9 U3): every current shard IRI in
        ``corpus`` and every ``(dependent, dependency, depends_on_* field)``
        edge, from a single query over the corpus ABox."""
        by_predicate = {str(fi(p)): field for field, p in DEPENDENCY_PREDICATES.items()}
        values = " ".join(by_predicate)
        sparql = (
            f"SELECT ?s ?p ?t WHERE {{ GRAPH {corpus_graph(corpus)} {{ "
            f"{{ ?s {_RDF_TYPE} {fi('Shard')} }} UNION "
            f"{{ VALUES ?p {{ {values} }} ?s ?p ?t }} }} }}"
        )
        nodes: set[str] = set()
        edges: list[tuple[str, str, str]] = []
        for sol in self._wrapper.store.query(sparql):
            subject = sol["s"].value
            nodes.add(subject)
            predicate = sol["p"]
            if predicate is not None:
                edges.append((subject, sol["t"].value, by_predicate[str(predicate)]))
        return sorted(nodes), sorted(edges)

    def close(self) -> None:
        self._wrapper.store.flush()
        # Drop the only reference so RocksDB releases its process lock now.
        del self._wrapper


def corpus_graphs(corpus: str, *, include_tbox: bool = False) -> list[NamedNode]:
    """The named graphs a corpus query sees (ABox, governance, optional TBox)."""
    graphs = [corpus_graph(corpus), governance_graph(corpus)]
    if include_tbox:
        graphs.append(TBOX_GRAPH)
    return graphs



def _refuse_service(sparql: str) -> None:
    from folio_insights.store.pyoxigraph_store import _SERVICE_RE, _strip_sparql_comments

    if _SERVICE_RE.search(_strip_sparql_comments(sparql)):
        raise ServiceClauseBlocked("SPARQL SERVICE clause rejected by the storage projection")


class ProjectionLock:
    """Exclusive cross-process (and cross-handle) lock on the projection.

    ``flock`` locks belong to an open file description, so two contexts in the
    same process exclude each other exactly like two processes do.
    """

    def __init__(self, root: Path, *, timeout_s: float) -> None:
        self._path = root / PROJECTION_LOCKNAME
        self._timeout_s = timeout_s
        self._fd: int | None = None

    def try_acquire(self) -> bool:
        fd = os.open(self._path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return False
        self._fd = fd
        return True

    def deadline(self) -> float:
        return time.monotonic() + self._timeout_s

    def timeout_error(self) -> ProjectionLockTimeout:
        return ProjectionLockTimeout(
            f"could not lock {self._path} within {self._timeout_s:.1f}s"
        )

    def release(self) -> None:
        if self._fd is not None:
            fd, self._fd = self._fd, None
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


__all__ = [
    "BULK_LOAD_MIN_ROWS",
    "CHAIN_GENESIS",
    "CORPUS_NS",
    "DEPENDENCY_PREDICATES",
    "GOVERNANCE_PREDICATE_OVERRIDES",
    "META_GRAPH",
    "TBOX_GRAPH",
    "PROJECTION_ADAPTER_VERSION",
    "PROJECTION_DIRNAME",
    "PROJECTION_LOCKNAME",
    "ProjectionHandle",
    "ProjectionLock",
    "ProjectionState",
    "chain_over",
    "chain_step",
    "corpus_graph",
    "corpus_graphs",
    "governance_event_iri",
    "governance_graph",
    "governance_triples",
    "iri_or_literal",
    "load_row_shard",
    "row_triples",
    "shard_triples",
    "tbox_digest",
    "tbox_quads",
    "tbox_sources",
]
