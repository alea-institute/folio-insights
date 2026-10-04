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
* ``urn:folio-insights:storage:projection`` — per-corpus watermark and adapter
  version (storage-internal; never in the corpus dataset a query sees).

Writes go through pyoxigraph only (never rdflib). RocksDB allows one open
handle per path per process, and readers cannot open it while another process
writes, so every open is guarded by an exclusive ``flock`` on
``<root>/projection.lock`` and the handle is dropped before the lock is
released. The adapter version is part of the stored state: a version change
rebuilds the corpus graphs from the journal.
"""
from __future__ import annotations

import fcntl
import json
import os
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from pyoxigraph import Literal, NamedNode, QueryBoolean, QuerySolutions, QueryTriples

from folio_insights.revision.content_edit import canonical_content_hash
from folio_insights.shards import ShardEnvelope, load_shard_record
from folio_insights.storage.errors import ProjectionLockTimeout, UnsupportedStorageSchema
from folio_insights.storage.journal import KIND_GOVERNANCE, KIND_SHARD, JournalRow
from folio_insights.store import PyoxigraphStore
from folio_insights.store.pyoxigraph_store import ServiceClauseBlocked
from folio_insights.vocab._constants import FI_PREFIX

PROJECTION_DIRNAME = "projection.oxigraph"
PROJECTION_LOCKNAME = "projection.lock"
PROJECTION_ADAPTER_VERSION = 1

CORPUS_NS = "https://folio-insights.aleainstitute.ai/corpus/"
META_GRAPH = NamedNode("urn:folio-insights:storage:projection")

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
        (s, fi("confidence"), Literal(repr(float(shard.confidence)), datatype=_XSD_DOUBLE)),
        (s, fi("contested"), Literal("true" if shard.contested else "false", datatype=_XSD_BOOL)),
        (s, fi("journalPosition"), Literal(str(journal_position), datatype=_XSD_INT)),
        (s, fi("signatureCount"), Literal(str(len(shard.signatures)), datatype=_XSD_INT)),
        (s, fi("contentEditCount"), Literal(str(len(shard.content_edits)), datatype=_XSD_INT)),
    ]
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
            out.append((e, fi(_camel(key)), obj))
    return out


# ── SPARQL text builders (terms serialize as N-Triples, valid in SPARQL) ──


def _triples_block(triples: Iterable[tuple[Any, Any, Any]]) -> str:
    return " ".join(f"{s} {p} {o} ." for s, p, o in triples)


def _apply_update(corpus: str, rows: Sequence[JournalRow], new_watermark: int) -> str:
    abox = corpus_graph(corpus)
    gov = governance_graph(corpus)
    ops: list[str] = []
    for row in rows:
        if row.kind == KIND_SHARD:
            shard = load_shard_record(row.payload).shard
            s = NamedNode(shard.shard_iri)
            ops.append(f"DELETE WHERE {{ GRAPH {abox} {{ {s} ?p ?o }} }}")
            block = _triples_block(shard_triples(shard, journal_position=row.position))
            ops.append(f"INSERT DATA {{ GRAPH {abox} {{ {block} }} }}")
        elif row.kind == KIND_GOVERNANCE:
            event_json = json.loads(row.payload)
            block = _triples_block(
                governance_triples(corpus, event_json, journal_position=row.position)
            )
            ops.append(f"INSERT DATA {{ GRAPH {gov} {{ {block} }} }}")
        else:  # pragma: no cover - the journal CHECK constraint forbids this
            raise UnsupportedStorageSchema(f"unknown journal row kind {row.kind!r}")
    ops.append(_watermark_update(abox, new_watermark))
    return " ;\n".join(ops)


def _watermark_update(node: NamedNode, watermark: int) -> str:
    wm = Literal(str(watermark), datatype=_XSD_INT)
    ver = Literal(str(PROJECTION_ADAPTER_VERSION), datatype=_XSD_INT)
    return (
        f"DELETE WHERE {{ GRAPH {META_GRAPH} {{ {node} {fi('appliedPosition')} ?w }} }} ;\n"
        f"DELETE WHERE {{ GRAPH {META_GRAPH} {{ {node} {fi('adapterVersion')} ?v }} }} ;\n"
        f"INSERT DATA {{ GRAPH {META_GRAPH} {{ {node} {fi('appliedPosition')} {wm} . "
        f"{node} {fi('adapterVersion')} {ver} . }} }}"
    )


# ── projection handle ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProjectionState:
    watermark: int
    adapter_version: int | None


class ProjectionHandle:
    """An open projection store. Use only while holding ``ProjectionLock``."""

    def __init__(self, root: Path) -> None:
        self._wrapper = PyoxigraphStore(path=str(root / PROJECTION_DIRNAME))

    def state(self, corpus: str) -> ProjectionState:
        node = corpus_graph(corpus)
        rows = [
            (sol["w"], sol["v"])
            for sol in self._wrapper.store.query(
                f"SELECT ?w ?v WHERE {{ GRAPH {META_GRAPH} {{ "
                f"{node} {fi('appliedPosition')} ?w . "
                f"OPTIONAL {{ {node} {fi('adapterVersion')} ?v }} }} }}"
            )
        ]
        if not rows:
            return ProjectionState(watermark=-1, adapter_version=None)
        w, v = rows[0]
        return ProjectionState(
            watermark=int(w.value), adapter_version=None if v is None else int(v.value)
        )

    def reset(self, corpus: str) -> None:
        """Drop the corpus graphs and watermark (adapter-version rebuild)."""
        node = corpus_graph(corpus)
        self._wrapper.store.update(
            f"DROP SILENT GRAPH {corpus_graph(corpus)} ;\n"
            f"DROP SILENT GRAPH {governance_graph(corpus)} ;\n"
            f"DELETE WHERE {{ GRAPH {META_GRAPH} {{ {node} ?p ?o }} }}"
        )

    def apply(self, corpus: str, rows: Sequence[JournalRow]) -> int:
        """Apply contiguous ``rows`` plus the watermark in one transaction."""
        if not rows:
            return self.state(corpus).watermark
        current = self.state(corpus).watermark
        if rows[0].position != current + 1:
            raise UnsupportedStorageSchema(
                f"projection replay for {corpus!r} expected position {current + 1}, "
                f"got {rows[0].position}"
            )
        for prev, nxt in zip(rows, rows[1:]):
            if nxt.position != prev.position + 1:
                raise UnsupportedStorageSchema("projection replay rows are not contiguous")
        self._wrapper.store.update(_apply_update(corpus, rows, rows[-1].position))
        return rows[-1].position

    def query(self, corpus: str, sparql: str) -> Any:
        """Read-only SPARQL over this corpus's graphs only; results materialized."""
        _refuse_service(sparql)
        graphs = [corpus_graph(corpus), governance_graph(corpus)]
        raw = self._wrapper.store.query(sparql, default_graph=graphs, named_graphs=graphs)
        if isinstance(raw, QueryBoolean):
            return bool(raw)
        if isinstance(raw, QuerySolutions):
            names = [v.value for v in raw.variables]
            return [{name: sol[name] for name in names} for sol in raw]
        if isinstance(raw, QueryTriples):
            return list(raw)
        return raw  # pragma: no cover

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

    def close(self) -> None:
        self._wrapper.store.flush()
        # Drop the only reference so RocksDB releases its process lock now.
        del self._wrapper


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
    "CORPUS_NS",
    "DEPENDENCY_PREDICATES",
    "META_GRAPH",
    "PROJECTION_ADAPTER_VERSION",
    "PROJECTION_DIRNAME",
    "PROJECTION_LOCKNAME",
    "ProjectionHandle",
    "ProjectionLock",
    "ProjectionState",
    "corpus_graph",
    "governance_event_iri",
    "governance_graph",
    "governance_triples",
    "iri_or_literal",
    "shard_triples",
]
