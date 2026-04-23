"""pyoxigraph Store wrapper + one-way rdflib bridge for pyshacl (STORAGE-02).

This module is the canonical RDF-1.2 store surface for Phase 0..23. Downstream
plans (Gate 1-5 measurement, Phase 11 SHACL, Phase 13 storage cutover, Phase
16 public SPARQL) MUST route through this wrapper rather than touching
pyoxigraph.Store directly.

Pitfall Register (see .planning/phases/00-foundations-hard-gate/00-RESEARCH.md):

- **Pitfall 1 — subject-position triple terms:** pyoxigraph 0.5.x rejects
  SPARQL-star subject-position triple-term patterns (the banned form used
  double-angle-bracket syntax around a triple, stripped here for grep
  discipline). The wrapper does not rewrite such inputs; callers must use
  either the RDF-12 annotation-pipe `?s ?p ?o {| ?p2 ?o2 |}` or
  `rdf:Statement` reification. Test-6 pins regression against silent
  acceptance.

- **Pitfall 2 — rdflib annotation drop:** the `validate_shard_via_rdflib_bridge`
  method serializes pyoxigraph data to Turtle then parses it into rdflib for
  pyshacl. rdflib 7.6 silently drops RDF-12 triple-term annotations during
  Turtle parse, so this bridge is ONE-WAY and is safe only for plain-triple
  shards. Annotation-dependent SHACL shapes must be expressed as pyoxigraph
  SPARQL ASK queries (Phase 11 routing).
"""
from __future__ import annotations

import re
from pathlib import Path

from pyoxigraph import NamedNode, RdfFormat, Store
from rdflib import Dataset

FOLIO_NS = "https://folio.openlegalstandard.org/"
FOLIO_INSIGHTS_NS = f"{FOLIO_NS}modules/folio-insights/"


# SEC-01: SERVICE-clause preflight. pyoxigraph 0.5.x evaluates SPARQL SERVICE
# by opening an outbound TCP connection; against link-local / metadata IPs
# this can hang 5–135s (observed variance) before OSError. At Phase 0 we
# reject SERVICE wholesale — Phase 16 replaces this with a per-endpoint
# allowlist in API middleware.
_SERVICE_RE = re.compile(r"\bSERVICE\b", re.IGNORECASE)


class ServiceClauseBlocked(RuntimeError):
    """Raised when SPARQL input contains a SERVICE clause (SEC-01 SSRF baseline).

    Message includes the token ``SERVICE`` so Gate 1 adversarial-safety test
    can assert this is a known-class rejection, not a raw pyoxigraph crash.
    """


def _strip_sparql_comments(sparql: str) -> str:
    """Remove ``#``-prefixed SPARQL comments so the SERVICE regex does not
    false-positive on documentation-only occurrences.

    SPARQL comments run from an unquoted ``#`` to end-of-line. We deliberately
    do not implement full quote-state tracking because SERVICE is not a
    valid literal substring; the minimal comment strip is sufficient at
    Phase 0 and is replaced by Phase 16 middleware that parses the query.
    """
    return "\n".join(
        line.split("#", 1)[0] for line in sparql.splitlines()
    )


class PyoxigraphStore:
    """Canonical RDF 1.2 store for Phase 0..23.

    Primary surface:
      - ``query_rdf12()`` for annotation-pipe SPARQL against pyoxigraph
        (STORAGE-04)
      - ``bulk_load_nquads()`` + ``optimize()`` for Gate 2 tuning (RESEARCH.md
        Gate 2 steps 1+2)

    Bridge surface (one-way only — Pitfall 2):
      - ``dump_turtle()`` serializes pyoxigraph graph to Turtle bytes
      - ``validate_shard_via_rdflib_bridge()`` round-trips through rdflib for
        pyshacl

    WARNING: rdflib 7.6 silently drops RDF-12 annotation triples during Turtle
    parse. Use ONLY for plain-triple validation paths. RDF-12-annotated shards
    MUST use SPARQL ASK shapes directly against pyoxigraph.
    """

    def __init__(self, path: str | None = None) -> None:
        """Open an in-memory (``path=None``) or persistent RocksDB store."""
        self._store = Store(path=path) if path else Store()

    @property
    def store(self) -> Store:
        """Escape hatch for tests + Phase 13 migration code."""
        return self._store

    def bulk_load_nquads(self, path: Path) -> None:
        """Gate 2 step 1 — single-call bulk ingest (100x faster than per-quad add)."""
        with open(path, "rb") as f:
            self._store.bulk_load(f, format=RdfFormat.N_QUADS)

    def optimize(self) -> None:
        """Gate 2 step 2 — RocksDB compaction + index merge after bulk load.

        Idempotent: safe to call multiple times. In-memory stores treat this
        as a no-op; RocksDB-backed stores trigger compaction.
        """
        self._store.optimize()

    def query_rdf12(
        self,
        sparql: str,
        named_graphs: list[NamedNode] | None = None,
    ) -> list:
        """Gate 2 step 3 — prune scan by ``named_graphs`` when only one corpus
        matters.

        SEC-01 preflight: SPARQL containing a SERVICE clause is rejected with
        ``ServiceClauseBlocked`` *before* pyoxigraph evaluates it. Phase 16
        middleware will replace this with a per-endpoint allowlist.

        When ``named_graphs`` is supplied, pyoxigraph restricts the dataset
        such that the SPARQL variable bound to the graph name only iterates
        over the supplied list (skipping any other named graphs in the store).
        """
        if _SERVICE_RE.search(_strip_sparql_comments(sparql)):
            raise ServiceClauseBlocked(
                "SPARQL SERVICE clause rejected at Phase 0 wrapper (SEC-01)"
            )
        if named_graphs:
            return list(self._store.query(sparql, named_graphs=named_graphs))
        return list(self._store.query(sparql))

    def dump_turtle(self, construct_query: str | None = None) -> bytes:
        """Serialize graph (or CONSTRUCT subset) to Turtle bytes.

        One-way bridge to rdflib. Behavior:

        - ``construct_query=None`` and store contains named graphs → serialize
          the full dataset as **TriG** (Turtle with named-graph blocks). Pure
          Turtle does not support named graphs; TriG is the superset that
          rdflib parses via ``format="trig"``.
        - ``construct_query=None`` and store is single-graph → serialize as
          Turtle.
        - ``construct_query=<SPARQL>`` → serialize the CONSTRUCT result set
          as Turtle (single-graph by CONSTRUCT's semantics).

        Preferred for per-shard validation: pass a ``CONSTRUCT`` to bound the
        serialized subgraph (avoids 1M-triple dumps).
        """
        if construct_query is None:
            # Detect named-graph presence by peeking at one named quad.
            has_named_graphs = any(
                True
                for _ in self._store.query(
                    "SELECT * WHERE { GRAPH ?g { ?s ?p ?o } } LIMIT 1"
                )
            )
            fmt = RdfFormat.TRIG if has_named_graphs else RdfFormat.TURTLE
            # pyoxigraph Store.dump(output=None, format=...) returns bytes.
            return self._store.dump(format=fmt)
        results = self._store.query(construct_query)
        # pyoxigraph QueryTriples.serialize(output=None, format=...) returns bytes.
        return results.serialize(format=RdfFormat.TURTLE)

    def validate_shard_via_rdflib_bridge(
        self,
        shard_iri: NamedNode,
        shapes_path: Path,
    ) -> tuple[bool, str]:
        """Bridge: pyoxigraph → Turtle → rdflib Dataset → pyshacl.

        WARNING (Pitfall 2): RDF-12 annotation triples are silently dropped.
        For annotation-dependent shapes use SPARQL ASK on pyoxigraph directly.

        Bounded via ``CONSTRUCT`` (not ``DESCRIBE``) so the rdflib parse stays
        O(shard) rather than O(graph).
        """
        from pyshacl import validate  # lazy — keeps import cost off hot path

        construct = (
            "CONSTRUCT { ?s ?p ?o } WHERE { "
            f"GRAPH ?g {{ <{shard_iri.value}> ?p ?o . "
            f"BIND(<{shard_iri.value}> AS ?s) }} "
            "}"
        )
        turtle_bytes = self.dump_turtle(construct_query=construct)
        data_graph = Dataset()
        data_graph.parse(data=turtle_bytes, format="turtle")
        conforms, _, report_text = validate(
            data_graph=data_graph,
            shacl_graph=str(shapes_path),
            inference="rdfs",
            serialize_report_graph=False,
        )
        return conforms, report_text
