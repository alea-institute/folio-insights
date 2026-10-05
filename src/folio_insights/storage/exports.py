"""Phase 13 export formats (U4; ROADMAP Phase 13 exit criterion 5, STORAGE-06).

Eight formats, each with a declared capability and a round-trip check:

=================  ============  ==============================================
format             named graphs  packaging / loss notes
=================  ============  ==============================================
``combined.ttl``   no            ABox + governance + TBox merged into one graph.
                                 Graph membership is NOT carried; refused when
                                 the caller requires named graphs.
``abox/*.ttl``     packaged      one Turtle file per corpus ABox graph; the
                                 manifest maps each file to its graph IRI.
``tbox.ttl``       packaged      the shared TBox graph (one file, one graph).
``governance.ttl`` packaged      the corpus governance graph.
JSON-LD            yes           ``dataset.jsonld``: every graph as a named
                                 ``@graph`` (expanded form, no framing).
SPARQL CONSTRUCT   no            ``construct.ttl``: the query result, one graph.
                                 A result that names a shard or governance
                                 event without its identity and signature
                                 triples is refused unless ``allow_partial``.
N-Quads            yes           ``dataset.nq``: the full dataset.
Neo4j CSV          packaged      ``neo4j/nodes.csv`` + ``neo4j/relationships.csv``
                                 (neo4j-admin import headers); every IRI, blank
                                 node and literal is a node (datatype and
                                 language kept), every quad a relationship
                                 carrying its predicate IRI and graph IRI.
=================  ============  ==============================================

Every whole-dataset format carries the **signed records**: for each current
shard, ``fi:signedRecord`` (the journal's original record bytes, the input
that was validated and signed), ``fi:signedRecordSha256`` and
``fi:recordSourceSchemaVersion``; for each governance event,
``fi:signedEvent`` (the journaled event JSON with its signature). The RDF
projection alone keeps only signer DIDs and counts, so without these an
export would silently drop signature material; with them a shard or event can
be reloaded and its signatures re-verified from any format.

RDF 1.2 triple terms: Turtle, N-Quads and CONSTRUCT output can carry them;
JSON-LD and the Neo4j CSV layout cannot, so a dataset containing one is
refused by those two formats instead of being flattened. (The projection
adapters emit none today; the check guards future adapters.)

Named graphs: a caller that requires graph membership
(``require_named_graphs=True``) is refused by the two formats that drop it
(``combined.ttl`` and CONSTRUCT). The per-graph Turtle files and the Neo4j
CSV carry membership by packaging, N-Quads and JSON-LD natively.

After writing, every format is parsed back (pyoxigraph, or the CSV reader)
and compared with its source under the documented packaging. A mismatch
raises ``ExportLossDetected`` and removes what was written: a lossy file is
never left behind as if it were an export.

TBox profile (Phase 9 U4, KTD5): every export that carries the TBox checks it
against OWL 2 EL first. By default (``tbox_profile="EL"``) an axiom outside EL
refuses the export (``TBoxProfileViolation``) and the message names the axiom
and the EL constraint it breaks; nothing is written. ``expressive=True`` (or
``tbox_profile="DL"``) adds the shipped OWL 2 DL layer (``vocab/expressive.ttl``)
and exports with a warning that lists every non-EL axiom. The manifest's
``tbox_profile`` entry records the profile, the reasoner for it (HermiT for both)
and the violations.

Writes and parses go through pyoxigraph only; rdflib is not used here.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from pyoxigraph import (
    BlankNode,
    CanonicalizationAlgorithm,
    Dataset,
    DefaultGraph,
    Literal,
    NamedNode,
    Quad,
    RdfFormat,
    Store,
    Triple,
    parse,
    serialize,
)

from folio_insights.reason.el_profile import check_el_profile, format_violations
from folio_insights.reason.reasoner import TBOX_PROFILES, TBoxProfile, reasoner_for_profile
from folio_insights.storage._paths import inside, inside_served_output
from folio_insights.storage.errors import StorageError
from folio_insights.storage.projection import (
    CORPUS_NS,
    TBOX_GRAPH,
    corpus_graph,
    fi,
    governance_event_iri,
    governance_graph,
)
from folio_insights.vocab._constants import FI_PREFIX

if TYPE_CHECKING:
    from folio_insights.storage.context import CorpusStorageContext

logger = logging.getLogger(__name__)

_XSD_INT = NamedNode("http://www.w3.org/2001/XMLSchema#integer")
_RDF_TYPE = NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")

PREFIXES: dict[str, str] = {
    "fi": FI_PREFIX,
    "corpus": CORPUS_NS,
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "owl": "http://www.w3.org/2002/07/owl#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "sh": "http://www.w3.org/ns/shacl#",
    "prov": "http://www.w3.org/ns/prov#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
}

# Triples a shard / governance event subject must keep in a partial export.
SHARD_IDENTITY_PREDICATES: tuple[str, ...] = (
    "provenanceHash",
    "sourceUri",
    "sourceSpan",
    "extractedAt",
    "firstExtractorDid",
    "contentHash",
    "signedRecord",
    "signedRecordSha256",
)
EVENT_IDENTITY_PREDICATES: tuple[str, ...] = (
    "signerDid",
    "signatureOverHash",
    "logPosition",
    "signedEvent",
)


class ExportFormat(StrEnum):
    COMBINED_TTL = "combined.ttl"
    ABOX_TTL = "abox"
    TBOX_TTL = "tbox.ttl"
    GOVERNANCE_TTL = "governance.ttl"
    JSON_LD = "jsonld"
    SPARQL_CONSTRUCT = "construct"
    N_QUADS = "nquads"
    NEO4J_CSV = "neo4j"


@dataclass(frozen=True)
class FormatCapability:
    """What a format can carry, and how a missing capability is packaged.

    ``named_graphs`` is ``"native"``, ``"packaged"`` (membership recoverable
    from the file layout / manifest or a property) or ``"none"``.
    """

    named_graphs: str
    graph_packaging: str
    triple_terms: bool
    signed_records: str
    round_trip: str


CAPABILITIES: dict[ExportFormat, FormatCapability] = {
    ExportFormat.COMBINED_TTL: FormatCapability(
        named_graphs="none",
        graph_packaging="merged: one default graph, membership not carried",
        triple_terms=True,
        signed_records="included",
        round_trip="triple set == union of ABox, governance and TBox triples",
    ),
    ExportFormat.ABOX_TTL: FormatCapability(
        named_graphs="packaged",
        graph_packaging="one file per ABox graph; manifest maps file -> graph IRI",
        triple_terms=True,
        signed_records="included (shards)",
        round_trip="each file's triples == its ABox graph",
    ),
    ExportFormat.TBOX_TTL: FormatCapability(
        named_graphs="packaged",
        graph_packaging="single graph file; manifest records the TBox graph IRI",
        triple_terms=True,
        signed_records="not applicable (no signed content)",
        round_trip="triples == TBox graph (blank nodes compared canonically)",
    ),
    ExportFormat.GOVERNANCE_TTL: FormatCapability(
        named_graphs="packaged",
        graph_packaging="single graph file; manifest records the governance graph IRI",
        triple_terms=True,
        signed_records="included (events)",
        round_trip="triples == governance graph",
    ),
    ExportFormat.JSON_LD: FormatCapability(
        named_graphs="native",
        graph_packaging="native (@graph per named graph)",
        triple_terms=False,
        signed_records="included",
        round_trip="quads == dataset",
    ),
    ExportFormat.SPARQL_CONSTRUCT: FormatCapability(
        named_graphs="none",
        graph_packaging="query result is one graph; membership not carried",
        triple_terms=True,
        signed_records="only what the query selects; partial results refused by default",
        round_trip="triples == CONSTRUCT result",
    ),
    ExportFormat.N_QUADS: FormatCapability(
        named_graphs="native",
        graph_packaging="native",
        triple_terms=True,
        signed_records="included",
        round_trip="quads == dataset",
    ),
    ExportFormat.NEO4J_CSV: FormatCapability(
        named_graphs="packaged",
        graph_packaging="graph IRI as a relationship property",
        triple_terms=False,
        signed_records="included (as literal nodes)",
        round_trip="quads rebuilt from nodes + relationships == dataset",
    ),
}

ALL_FORMATS: tuple[ExportFormat, ...] = tuple(
    f for f in ExportFormat if f is not ExportFormat.SPARQL_CONSTRUCT
)


class ExportRefused(ValueError):
    """The requested representation cannot carry what the caller requires
    (named graphs, triple terms, or a shard/event's identity and signature
    metadata); nothing was written."""


class ExportLossDetected(StorageError):
    """A written export did not round-trip to its source; it was removed."""


class TBoxProfileViolation(ExportRefused):
    """The exported TBox has axioms outside OWL 2 EL and the export was not
    marked expressive; the message names each axiom and its EL constraint."""

    def __init__(self, message: str, violations: list[Any]) -> None:
        super().__init__(message)
        self.violations = violations


# Formats whose output includes the shared TBox graph.
TBOX_CARRYING_FORMATS: frozenset[ExportFormat] = frozenset(
    {
        ExportFormat.COMBINED_TTL,
        ExportFormat.TBOX_TTL,
        ExportFormat.JSON_LD,
        ExportFormat.N_QUADS,
        ExportFormat.NEO4J_CSV,
    }
)


def expressive_tbox_quads() -> list[Quad]:
    """The shipped OWL 2 DL layer (``vocab/expressive.ttl``) as TBox-graph quads."""
    from folio_insights.vocab import expressive_ttl_bytes

    return [
        Quad(t.subject, t.predicate, t.object, TBOX_GRAPH)
        for t in parse(expressive_ttl_bytes(), format=RdfFormat.TURTLE)
    ]


def resolve_tbox_profile(tbox_profile: TBoxProfile | None, expressive: bool) -> TBoxProfile:
    """``expressive`` is shorthand for the DL profile; the default is EL."""
    if tbox_profile is not None and tbox_profile not in TBOX_PROFILES:
        raise ValueError(f"unknown TBox profile {tbox_profile!r}; expected one of {TBOX_PROFILES}")
    if expressive and tbox_profile == "EL":
        raise ValueError("expressive export conflicts with tbox_profile='EL'")
    return "DL" if expressive else (tbox_profile or "EL")


def apply_tbox_profile(
    dataset: ExportDataset, formats: Sequence[ExportFormat], profile: TBoxProfile
) -> dict[str, Any]:
    """Check the dataset's TBox against OWL 2 EL for ``profile`` (before writing).

    DL adds the expressive layer to the TBox graph and turns violations into
    warnings; EL refuses on any violation. Returns the manifest entry.
    """
    carries = any(f in TBOX_CARRYING_FORMATS for f in formats)
    if profile == "DL":
        tbox = dataset.graphs.setdefault(TBOX_GRAPH.value, [])
        present = set(map(str, tbox))
        tbox.extend(q for q in expressive_tbox_quads() if str(q) not in present)
    violations = check_el_profile(dataset.graph(TBOX_GRAPH)) if carries else []
    if violations and profile == "EL":
        raise TBoxProfileViolation(
            f"the TBox has {len(violations)} axiom(s) outside OWL 2 EL; nothing was "
            "written. Fix the axioms, or export with --expressive (OWL 2 DL):\n"
            + format_violations(violations),
            violations,
        )
    warnings = []
    if violations:
        warnings.append(
            f"TBox exported under the expressive (OWL 2 DL) profile with "
            f"{len(violations)} axiom(s) outside OWL 2 EL"
        )
        logger.warning("%s:\n%s", warnings[0], format_violations(violations))
    return {
        "profile": profile,
        "reasoner": reasoner_for_profile(profile).name,
        "checked": carries,
        "el_conformant": carries and not violations,
        "expressive_layer": profile == "DL",
        "el_violations": [v.as_dict() for v in violations],
        "warnings": warnings,
    }


# ── the export dataset ────────────────────────────────────────────────────


@dataclass
class ExportDataset:
    """A corpus's graphs at one watermark, plus the journal's signed records."""

    corpus: str
    watermark: int
    watermark_payload_sha256: str | None
    graphs: dict[str, list[Quad]] = field(default_factory=dict)
    # Phase 11 ``full_shacl`` state of the corpus at this watermark.
    full_shacl: str = "unvalidated"

    @property
    def abox(self) -> NamedNode:
        return corpus_graph(self.corpus)

    @property
    def governance(self) -> NamedNode:
        return governance_graph(self.corpus)

    def quads(self) -> list[Quad]:
        return [q for graph in self.graphs.values() for q in graph]

    def graph(self, name: NamedNode) -> list[Quad]:
        return self.graphs.get(name.value, [])


async def build_export_dataset(
    ctx: CorpusStorageContext, *, include_tbox: bool = True
) -> ExportDataset:
    """Read the corpus graphs and the matching journal rows at ONE watermark.

    The projection read and the journal read share the watermark the barrier
    returned, so the signed records describe exactly the projected revisions.
    """
    corpus = ctx.corpus
    graph_names = [corpus_graph(corpus), governance_graph(corpus)]
    if include_tbox:
        graph_names.append(TBOX_GRAPH)

    def read(handle: Any, watermark: int) -> tuple[dict[str, list[Quad]], str | None]:
        graphs = {g.value: handle.graph_quads(g) for g in graph_names}
        return graphs, handle.state(corpus).payload_sha256

    watermark, (graphs, sha) = await ctx._read_projection(read)
    dataset = ExportDataset(
        corpus=corpus,
        watermark=watermark,
        watermark_payload_sha256=sha,
        graphs=graphs,
        full_shacl=(await ctx._shacl_status(watermark)).state,
    )
    abox, gov = dataset.abox, dataset.governance
    for row in await ctx._current_shard_rows(watermark):
        original = row.original_bytes if row.original_bytes is not None else row.payload
        subject = NamedNode(row.subject)
        dataset.graphs.setdefault(abox.value, []).extend(
            [
                Quad(subject, fi("signedRecord"), Literal(original.decode("utf-8")), abox),
                Quad(
                    subject,
                    fi("signedRecordSha256"),
                    Literal(hashlib.sha256(original).hexdigest()),
                    abox,
                ),
                Quad(
                    subject,
                    fi("recordSourceSchemaVersion"),
                    Literal(
                        str(
                            row.source_schema_version
                            if row.source_schema_version is not None
                            else row.record_schema_version
                        ),
                        datatype=_XSD_INT,
                    ),
                    abox,
                ),
            ]
        )
    for row in await ctx._journal.governance_rows(corpus, upto=watermark):
        assert row.governance_position is not None
        event = governance_event_iri(corpus, row.governance_position)
        dataset.graphs.setdefault(gov.value, []).append(
            Quad(event, fi("signedEvent"), Literal(row.payload.decode("utf-8")), gov)
        )
    return dataset


# ── comparison helpers ────────────────────────────────────────────────────


def canonical_quads(quads: Iterable[Quad]) -> set[str]:
    """Quads as N-Quads lines with blank nodes canonically relabelled."""
    items = list(quads)
    if any(_is_blank(q) for q in items):
        ds = Dataset(items)
        ds.canonicalize(CanonicalizationAlgorithm.UNSTABLE)
        items = list(ds)
    return {str(q) for q in items}


def as_default_graph(quads: Iterable[Quad]) -> list[Quad]:
    return [Quad(q.subject, q.predicate, q.object, DefaultGraph()) for q in quads]


def _is_blank(q: Quad) -> bool:
    return isinstance(q.subject, BlankNode) or isinstance(q.object, BlankNode)


def round_trip_diff(expected: Iterable[Quad], actual: Iterable[Quad]) -> tuple[int, int]:
    """``(missing, unexpected)`` statement counts between two quad collections.

    Ground quads compare exactly. Quads with blank nodes compare exactly when
    the serializer kept the labels, else after canonical relabelling of the
    blank-node part alone (so one lost ground quad reports as one).
    """
    want_all, got_all = list(expected), list(actual)
    want_g = {str(q) for q in want_all if not _is_blank(q)}
    got_g = {str(q) for q in got_all if not _is_blank(q)}
    want_b = [q for q in want_all if _is_blank(q)]
    got_b = [q for q in got_all if _is_blank(q)]
    missing, unexpected = len(want_g - got_g), len(got_g - want_g)
    if {str(q) for q in want_b} != {str(q) for q in got_b}:
        cw, cg = canonical_quads(want_b), canonical_quads(got_b)
        missing += len(cw - cg)
        unexpected += len(cg - cw)
    return missing, unexpected


def _check(expected: Iterable[Quad], actual: Iterable[Quad], what: str) -> None:
    missing, unexpected = round_trip_diff(expected, actual)
    if missing or unexpected:
        raise ExportLossDetected(
            f"{what} did not round-trip: {missing} quad(s) missing, {unexpected} unexpected"
        )


def _has_triple_terms(quads: Iterable[Quad]) -> bool:
    return any(isinstance(q.subject, Triple) or isinstance(q.object, Triple) for q in quads)


# ── writers ───────────────────────────────────────────────────────────────


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _ttl(quads: Iterable[Quad]) -> bytes:
    triples = sorted(as_default_graph(quads), key=str)
    return serialize(
        [Triple(q.subject, q.predicate, q.object) for q in triples],
        format=RdfFormat.TURTLE,
        prefixes=PREFIXES,
    )


def _parse_ttl(path: Path) -> list[Quad]:
    return [
        Quad(t.subject, t.predicate, t.object, DefaultGraph())
        for t in parse(path=str(path), format=RdfFormat.TURTLE)
    ]


def abox_filename(corpus: str) -> str:
    """``abox/<percent-encoded corpus>.ttl`` (path-safe for any corpus name)."""
    return f"abox/{quote(corpus, safe='') or '_'}.ttl"


def _file_entry(root: Path, path: Path, *, graph: str | None, count: int) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": _sha(path),
        "graph": graph,
        "statements": count,
    }


def _graph_file(
    root: Path, rel: str, quads: list[Quad], graph: NamedNode, what: str
) -> dict[str, Any]:
    path = root / rel
    _write(path, _ttl(quads))
    _check(as_default_graph(quads), _parse_ttl(path), what)
    return _file_entry(root, path, graph=graph.value, count=len(quads))


def _neo4j(root: Path, quads: list[Quad]) -> list[dict[str, Any]]:
    ids: dict[str, str] = {}
    nodes = io.StringIO(newline="")
    rels = io.StringIO(newline="")
    node_w = csv.writer(nodes, lineterminator="\n")
    rel_w = csv.writer(rels, lineterminator="\n")
    node_w.writerow(["id:ID", "kind", "value", "datatype", "language", ":LABEL"])
    rel_w.writerow([":START_ID", ":END_ID", ":TYPE", "predicate", "graph"])

    def node(term: Any) -> str:
        key = str(term)
        if key in ids:
            return ids[key]
        node_id = f"n{len(ids)}"
        ids[key] = node_id
        if isinstance(term, NamedNode):
            node_w.writerow([node_id, "iri", term.value, "", "", "Resource"])
        elif isinstance(term, BlankNode):
            node_w.writerow([node_id, "bnode", term.value, "", "", "Resource"])
        else:
            node_w.writerow(
                [node_id, "literal", term.value, term.datatype.value, term.language or "",
                 "Literal"]
            )
        return node_id

    for q in sorted(quads, key=str):
        graph = "" if isinstance(q.graph_name, DefaultGraph) else q.graph_name.value
        rel_type = q.predicate.value.rstrip("/#").rsplit("/", 1)[-1].rsplit("#", 1)[-1]
        rel_w.writerow([node(q.subject), node(q.object), rel_type or "rel",
                        q.predicate.value, graph])
    out = []
    for name, buf in (("neo4j/nodes.csv", nodes), ("neo4j/relationships.csv", rels)):
        path = root / name
        _write(path, buf.getvalue().encode("utf-8"))
        out.append(_file_entry(root, path, graph=None, count=len(quads)))
    _check(quads, read_neo4j(root), "Neo4j CSV")
    return out


def read_neo4j(root: Path) -> list[Quad]:
    """Rebuild quads from a Neo4j CSV export (the round-trip reader)."""
    terms: dict[str, Any] = {}
    with open(root / "neo4j/nodes.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            kind, value = row["kind"], row["value"]
            if kind == "iri":
                terms[row["id:ID"]] = NamedNode(value)
            elif kind == "bnode":
                terms[row["id:ID"]] = BlankNode(value)
            elif row["language"]:
                terms[row["id:ID"]] = Literal(value, language=row["language"])
            else:
                terms[row["id:ID"]] = Literal(value, datatype=NamedNode(row["datatype"]))
    quads = []
    with open(root / "neo4j/relationships.csv", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            graph = NamedNode(row["graph"]) if row["graph"] else DefaultGraph()
            quads.append(
                Quad(terms[row[":START_ID"]], NamedNode(row["predicate"]),
                     terms[row[":END_ID"]], graph)
            )
    return quads


def _construct(dataset: ExportDataset, query: str, *, allow_partial: bool) -> list[Quad]:
    from folio_insights.storage.projection import _refuse_service

    _refuse_service(query)
    store = Store()
    store.extend(dataset.quads())
    result = store.query(query, use_default_graph_as_union=True)
    triples = [
        Quad(t.subject, t.predicate, t.object, DefaultGraph()) for t in result  # type: ignore[union-attr]
    ]
    if not allow_partial:
        _refuse_partial(dataset, triples)
    return triples


def _refuse_partial(dataset: ExportDataset, triples: list[Quad]) -> None:
    """A CONSTRUCT result that names a shard or governance event must keep its
    identity and signature triples; otherwise it is a lossy representation."""
    kinds: dict[str, str] = {}
    full: dict[str, set[tuple[str, str]]] = {}
    for q in dataset.quads():
        s = str(q.subject)
        if q.predicate == _RDF_TYPE and q.object in (fi("Shard"), fi("GovernanceEvent")):
            kinds[s] = "shard" if q.object == fi("Shard") else "event"
        full.setdefault(s, set()).add((str(q.predicate), str(q.object)))
    emitted: dict[str, set[tuple[str, str]]] = {}
    for q in triples:
        for term in (q.subject, q.object):
            if str(term) in kinds:
                emitted.setdefault(str(term), set())
        if str(q.subject) in kinds:
            emitted[str(q.subject)].add((str(q.predicate), str(q.object)))
    for subject, present in emitted.items():
        names = SHARD_IDENTITY_PREDICATES if kinds[subject] == "shard" else (
            EVENT_IDENTITY_PREDICATES
        )
        required = {
            (p, o)
            for p, o in full[subject]
            if p in {str(fi(n)) for n in names} or p == str(fi("signedBy"))
        }
        missing = required - present
        if missing:
            raise ExportRefused(
                f"CONSTRUCT result names {kinds[subject]} {subject} without "
                f"{len(missing)} identity/signature triple(s) "
                f"({sorted({p.rsplit('/', 1)[-1].rstrip('>') for p, _ in missing})}); "
                "pass allow_partial=True to export a deliberate subset"
            )


# ── public entry point ────────────────────────────────────────────────────


@dataclass(frozen=True)
class ExportResult:
    destination: Path
    manifest: dict[str, Any]


def _refuse_destination(destination: Path, ctx: CorpusStorageContext) -> None:
    dest = destination.resolve()
    if inside(dest, ctx.root):
        raise ExportRefused(f"export destination {destination} is inside the corpus storage root")
    served = inside_served_output(dest)
    if served is not None:
        raise ExportRefused(
            f"export destination {destination} is inside the served output directory "
            f"{served}; storage exports never expand the served boundary"
        )
    if dest.exists() and any(dest.iterdir()):
        raise ExportRefused(f"export destination {destination} exists and is not empty")


def check_capabilities(
    formats: Sequence[ExportFormat],
    dataset: ExportDataset,
    *,
    require_named_graphs: bool,
) -> None:
    """Refuse a format that cannot carry what is required, before writing."""
    triple_terms = _has_triple_terms(dataset.quads())
    for fmt in formats:
        cap = CAPABILITIES[fmt]
        if require_named_graphs and cap.named_graphs == "none":
            raise ExportRefused(
                f"{fmt.value} cannot carry named graphs ({cap.graph_packaging}); "
                "use nquads or jsonld, or a per-graph Turtle bundle"
            )
        if triple_terms and not cap.triple_terms:
            raise ExportRefused(
                f"{fmt.value} cannot represent RDF 1.2 triple terms present in the dataset"
            )


async def export_corpus(
    ctx: CorpusStorageContext,
    destination: str | os.PathLike[str],
    formats: Sequence[ExportFormat | str] = ALL_FORMATS,
    *,
    construct_query: str | None = None,
    allow_partial: bool = False,
    require_named_graphs: bool = False,
    tbox_profile: TBoxProfile | None = None,
    expressive: bool = False,
) -> ExportResult:
    """Write ``formats`` for this corpus into ``destination`` (new or empty).

    Every file is verified by parsing it back; on any refusal or loss the
    destination is removed again (if this call created it) or emptied of
    what this call wrote, and the error propagates.

    ``tbox_profile`` (default ``"EL"``) / ``expressive`` select the TBox
    profile (Phase 9 U4): see the module docstring. An EL violation refuses
    before anything is written.
    """
    chosen = [ExportFormat(f) for f in formats]
    if ExportFormat.SPARQL_CONSTRUCT in chosen and not construct_query:
        raise ExportRefused("the construct format needs construct_query")
    profile = resolve_tbox_profile(tbox_profile, expressive)
    dest = Path(destination)
    _refuse_destination(dest, ctx)
    dataset = await build_export_dataset(ctx)
    check_capabilities(chosen, dataset, require_named_graphs=require_named_graphs)
    profile_entry = apply_tbox_profile(dataset, chosen, profile)

    created = not dest.exists()
    dest.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    try:
        manifest = _write_formats(dest, dataset, chosen, construct_query, allow_partial, written)
        manifest["tbox_profile"] = profile_entry
        manifest_path = dest / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    except BaseException:
        if created:
            shutil.rmtree(dest, ignore_errors=True)
        else:
            for path in written:
                path.unlink(missing_ok=True)
        raise
    return ExportResult(destination=dest, manifest=manifest)


def _write_formats(
    dest: Path,
    dataset: ExportDataset,
    formats: Sequence[ExportFormat],
    construct_query: str | None,
    allow_partial: bool,
    written: list[Path],
) -> dict[str, Any]:
    files: dict[str, list[dict[str, Any]]] = {}
    abox = dataset.graph(dataset.abox)
    gov = dataset.graph(dataset.governance)
    tbox = dataset.graph(TBOX_GRAPH)

    for fmt in formats:
        if fmt is ExportFormat.COMBINED_TTL:
            merged = as_default_graph(abox + gov + tbox)
            path = dest / "combined.ttl"
            written.append(path)
            _write(path, _ttl(merged))
            _check(merged, _parse_ttl(path), "combined.ttl")
            count = len(set(map(str, merged)))
            files[fmt.value] = [_file_entry(dest, path, graph=None, count=count)]
        elif fmt is ExportFormat.ABOX_TTL:
            rel = abox_filename(dataset.corpus)
            written.append(dest / rel)
            files[fmt.value] = [_graph_file(dest, rel, abox, dataset.abox, "abox Turtle")]
        elif fmt is ExportFormat.TBOX_TTL:
            written.append(dest / "tbox.ttl")
            files[fmt.value] = [_graph_file(dest, "tbox.ttl", tbox, TBOX_GRAPH, "tbox.ttl")]
        elif fmt is ExportFormat.GOVERNANCE_TTL:
            written.append(dest / "governance.ttl")
            files[fmt.value] = [
                _graph_file(dest, "governance.ttl", gov, dataset.governance, "governance.ttl")
            ]
        elif fmt is ExportFormat.N_QUADS:
            quads = sorted(dataset.quads(), key=str)
            path = dest / "dataset.nq"
            written.append(path)
            _write(path, serialize(quads, format=RdfFormat.N_QUADS))
            _check(quads, list(parse(path=str(path), format=RdfFormat.N_QUADS)), "N-Quads")
            files[fmt.value] = [_file_entry(dest, path, graph=None, count=len(quads))]
        elif fmt is ExportFormat.JSON_LD:
            quads = sorted(dataset.quads(), key=str)
            path = dest / "dataset.jsonld"
            written.append(path)
            _write(path, serialize(quads, format=RdfFormat.JSON_LD, prefixes=PREFIXES))
            _check(quads, list(parse(path=str(path), format=RdfFormat.JSON_LD)), "JSON-LD")
            files[fmt.value] = [_file_entry(dest, path, graph=None, count=len(quads))]
        elif fmt is ExportFormat.NEO4J_CSV:
            written.extend([dest / "neo4j/nodes.csv", dest / "neo4j/relationships.csv"])
            files[fmt.value] = _neo4j(dest, dataset.quads())
        elif fmt is ExportFormat.SPARQL_CONSTRUCT:
            assert construct_query is not None
            triples = _construct(dataset, construct_query, allow_partial=allow_partial)
            path = dest / "construct.ttl"
            written.append(path)
            _write(path, _ttl(triples))
            _check(triples, _parse_ttl(path), "SPARQL CONSTRUCT")
            files[fmt.value] = [_file_entry(dest, path, graph=None, count=len(triples))]
    return {
        "corpus": dataset.corpus,
        "watermark": dataset.watermark,
        "watermark_payload_sha256": dataset.watermark_payload_sha256,
        "graphs": {
            "abox": dataset.abox.value,
            "governance": dataset.governance.value,
            "tbox": TBOX_GRAPH.value,
        },
        "formats": {
            name: {
                "files": entries,
                "capability": CAPABILITIES[ExportFormat(name)].__dict__,
            }
            for name, entries in files.items()
        },
        "partial": bool(allow_partial and ExportFormat.SPARQL_CONSTRUCT in formats),
        "full_shacl": dataset.full_shacl,
    }


__all__ = [
    "ALL_FORMATS",
    "CAPABILITIES",
    "ExportDataset",
    "ExportFormat",
    "ExportLossDetected",
    "ExportRefused",
    "ExportResult",
    "FormatCapability",
    "TBOX_CARRYING_FORMATS",
    "TBoxProfileViolation",
    "apply_tbox_profile",
    "expressive_tbox_quads",
    "resolve_tbox_profile",
    "abox_filename",
    "build_export_dataset",
    "canonical_quads",
    "check_capabilities",
    "export_corpus",
    "read_neo4j",
    "round_trip_diff",
]
