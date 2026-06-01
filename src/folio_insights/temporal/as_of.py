"""Phase 8 Plan 08-03 — query_as_of: walk fi:supersedes / validTime intervals
to surface a predicate's binding as it was on at_date.

# DEFERRED (D-11): ``--as-of <date>`` CLI flag ships in Phase 11 (triplestore)
# or Phase 12 (UI). docs/query-as-of.md is the cross-reference.

D-10 / D-04 dep-leak discipline (mirrors Phase 7 governance — see
``governance/shape_validation.py``): this module imports rdflib + stdlib
ONLY. NO pyoxigraph, oxrdflib, pyshacl; NO cross-coupling to
``folio_insights.{vocab, revision, store, governance}``. The dep-leak
guard at ``tests/temporal/test_dep_leak_guard.py`` enforces this.

Discretion handle (CONTEXT.md D-10): the signature accepts ``rdflib.Graph``
only (V1 minimum). Phase 11 widens to ``Graph | Store`` polymorphic when
the persistent pyoxigraph store lands.

PRD §21.9 valid-time semantics: a shard's valid-time interval is
[fi:validTimeStart, fi:validTimeEnd). When fi:validTimeEnd is absent the
interval is open-ended ([start, ∞)). When shard A fi:supersedes shard B,
B.fi:validTimeEnd == A.fi:validTimeStart (the SHACL
fi:SupersessionAlignmentShape in vocab/shapes.ttl enforces this at the
storage layer; this helper queries against the storage and trusts that the
shape held).

The supersession-chain walk is implicit in the SPARQL pattern: every shard
in the chain carries its own fi:validTimeStart / fi:validTimeEnd, so the
FILTER ``?start <= ?at && (!BOUND(?end) || ?at < ?end)`` naturally selects
the one whose interval contains ``at_date`` without a recursive Python walk.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import XSD

# D-01: canonical Phase 8 prefix. NOT the ``https://folio-insights.example/``
# placeholder used by Phase 7 governance (those shapes are quarantined per
# 08-CONTEXT.md and the drift audit lands in Plan 08-04).
FI = Namespace("https://folio-insights.aleainstitute.ai/vocab/")


# SPARQL SELECT with parameterized predicate + at-date. Uses initBindings
# to inject ``?predicate`` and ``?at`` (PITFALLS Q3 / T-08-10 mitigation —
# NO f-string interpolation of caller-supplied values into the query text).
#
# Pattern walks the supersession chain implicitly: each shard carries its
# own validTimeStart / validTimeEnd, so the half-open-interval FILTER
# selects the shard whose interval [start, end) contains ?at. When the
# end is absent (open-ended current shard) the !BOUND(?end) branch keeps
# the row.
_AS_OF_SELECT = """
PREFIX fi: <https://folio-insights.aleainstitute.ai/vocab/>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

SELECT ?subject ?object WHERE {
    ?subject ?predicate ?object .
    ?subject fi:validTimeStart ?start .
    OPTIONAL { ?subject fi:validTimeEnd ?end . }
    FILTER (?start <= ?at && (!BOUND(?end) || ?at < ?end))
}
"""


@dataclass(frozen=True)
class Row:
    """Optional NamedTuple-style alias for the (subject, object) tuple
    returned by ``query_as_of``. Kept as a dataclass for ergonomics; the
    function still returns plain ``list[tuple[URIRef, URIRef | Literal | BNode]]``
    so callers can pattern-match or unpack as they prefer.

    WR-04: ``object`` may resolve to a ``BNode`` when the underlying triple's
    object is a blank node (e.g. an embedded reification). Callers MUST
    guard for all three rdflib term types.
    """

    subject: URIRef
    object: URIRef | Literal | BNode


def _coerce_at(at_date: date | datetime) -> Literal:
    """Convert ``at_date`` into an xsd:dateTime Literal so the SPARQL FILTER
    compares against the validTimeStart/End triples (which are xsd:dateTime
    per Phase 8 predicates.ttl).
    """
    if isinstance(at_date, datetime):
        dt = at_date
    else:
        # ``date`` → midnight UTC. Half-open interval semantics (PRD §21.9)
        # mean t == start belongs to this link; t == end belongs to the next.
        dt = datetime(at_date.year, at_date.month, at_date.day, tzinfo=timezone.utc)
    if dt.tzinfo is None:
        # Naive datetimes are interpreted as UTC for cross-system determinism.
        dt = dt.replace(tzinfo=timezone.utc)
    return Literal(dt.isoformat(), datatype=XSD.dateTime)


def query_as_of(
    graph: Graph,
    predicate: URIRef,
    at_date: date | datetime,
) -> list[tuple[URIRef, URIRef | Literal | BNode]]:
    """Return the binding of ``predicate`` on every subject whose valid-time
    interval contains ``at_date``.

    Walks the supersession chain implicitly via the per-shard validTime
    triples (PRD §21.9 / D-10): each shard in the chain carries its own
    validTimeStart/End, so the half-open-interval FILTER selects the one
    whose [start, end) interval contains ``at_date`` without a recursive
    Python walk.

    Parameters
    ----------
    graph
        An rdflib.Graph containing the supersession chain. Discretion handle
        per D-10: Phase 11 widens to ``Graph | Store`` polymorphic when the
        persistent pyoxigraph store lands.
    predicate
        The fi:* predicate whose binding is being queried.
    at_date
        The point-in-time to query against. ``date`` is coerced to midnight
        UTC for half-open interval comparison.

    Returns
    -------
    list[tuple[URIRef, URIRef | Literal | BNode]]
        ``(subject, object)`` rows where ``subject`` is the shard IRI whose
        interval contains ``at_date`` and ``object`` is the predicate's
        value on that shard. Empty list when no shard's interval contains
        ``at_date``. ``object`` may be a ``BNode`` when the underlying
        triple's object is a blank node (e.g. an embedded reification —
        WR-04).

    Notes
    -----
    - PITFALLS Q3 / T-08-10: ``predicate`` and ``at_date`` flow through
      ``initBindings``, never via f-string interpolation. Caller-supplied
      values cannot inject SPARQL syntax.
    - The input graph is NOT mutated; this is a pure read.
    """
    at_literal = _coerce_at(at_date)
    qres = graph.query(
        _AS_OF_SELECT,
        initBindings={
            "predicate": predicate,
            "at": at_literal,
        },
    )
    return [(row.subject, row.object) for row in qres]


__all__ = ["query_as_of", "Row", "FI"]
