"""Closed-world islands (Phase 9 U5, PRD §8 P5, R8, KTD8).

The corpus is open-world: absence of a triple means *unknown*, not *false*.
Negation-as-failure (``FILTER NOT EXISTS``) is therefore only sound inside a
declared island. This module answers count questions in one of two modes and
says which, as data, on every result (``world_assumption``):

* ``"closed"``: the subject carries ``fi:closedUnder <scope>`` in the corpus
  projection AND the caller registered a :class:`ClosedWorldScope` for that IRI
  whose closed classes and properties cover the question. Only then does
  ``ClosedWorldQuery`` issue ``FILTER NOT EXISTS``, and the answer is complete.
* ``"open"``: anything else. No negation-as-failure runs; the result carries
  only what is asserted, plus an incompleteness note (it "may be incomplete").

How a scope is declared. No existing writer emits ``fi:closedUnder`` yet (the
shard projection has no field for it), so a scope has two halves, both
required for a closed answer: the *membership* is read from
``?s fi:closedUnder ?scope`` triples present in the corpus projection, and the
*closure contract* (which classes and properties are complete) is data the
caller passes as :class:`ClosedWorldScope`. A caller-supplied scope alone never
closes the world, and a bare triple alone never does either.

Injection safety. ``CorpusStorageContext.query`` takes SPARQL text with no
binding API, so every caller-supplied IRI is validated against a strict IRI
grammar (no whitespace, angle brackets, quotes, braces, ``|``, ``^``, backtick,
backslash) before it is written as a ``VALUES`` term; the query text itself is
a fixed template. This module imports the standard library only, so it can run
against any object with an async ``query`` method.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

FI = "https://folio-insights.aleainstitute.ai/vocab/"
CLOSED_UNDER = FI + "closedUnder"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

WorldAssumption = Literal["closed", "open"]

_IRI_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:[^\x00-\x20<>\"{}|\\^`]+$")

OPEN_NOTE = (
    "Open-world answer: only asserted facts are counted, and absence is not "
    "negation. The result may be incomplete."
)


class InvalidIri(ValueError):
    """A caller-supplied value is not an IRI safe to place in a query."""


class SparqlRunner(Protocol):
    """What ``CorpusStorageContext`` offers: read-only SPARQL, solutions as
    ``{variable: term}`` mappings whose terms expose ``.value``."""

    async def query(self, sparql: str, *, include_tbox: bool = False) -> Any: ...


def _iri(value: str) -> str:
    """Validate ``value`` as an IRI and return its ``<...>`` SPARQL form."""
    if not isinstance(value, str) or not _IRI_RE.match(value):
        raise InvalidIri(f"not a safe IRI: {value!r}")
    return f"<{value}>"


@dataclass(frozen=True)
class ClosedWorldScope:
    """A declared closed-world island: the scope IRI plus the classes and
    properties that are complete inside it."""

    scope_iri: str
    closed_classes: frozenset[str] = frozenset()
    closed_properties: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        _iri(self.scope_iri)
        object.__setattr__(self, "closed_classes", frozenset(self.closed_classes))
        object.__setattr__(self, "closed_properties", frozenset(self.closed_properties))
        for value in (*self.closed_classes, *self.closed_properties):
            _iri(value)

    def covers(self, *, cls: str | None = None, prop: str | None = None) -> bool:
        """True when every named class/property is closed in this scope."""
        return (cls is None or cls in self.closed_classes) and (
            prop is None or prop in self.closed_properties
        )


@dataclass(frozen=True)
class CountResult:
    """Base of every count API result: the answer always carries its world
    assumption. ``count`` is ``None`` when an open world cannot give one."""

    world_assumption: WorldAssumption
    count: int | None
    scope_iri: str | None = None
    incompleteness_note: str | None = None

    @property
    def is_complete(self) -> bool:
        return self.world_assumption == "closed"


@dataclass(frozen=True)
class RelatedCount(CountResult):
    """Objects related to a subject by a property (e.g. a contract's parties)."""

    items: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class LackingCount(CountResult):
    """Instances of a class lacking a property. Closed: the NAF count. Open:
    ``count`` is ``None`` and the positive evidence is reported instead."""

    total_instances: int = 0
    asserted_with_property: int = 0


def _rows(result: Any) -> list[dict[str, Any]]:
    return list(result) if result is not None else []


def _n(row: dict[str, Any], name: str = "n") -> int:
    return int(row[name].value)


class ClosedWorldQuery:
    """Count queries that apply negation-as-failure only inside bound scopes.

    ``runner`` is a ``CorpusStorageContext`` (or anything with its ``query``);
    ``scopes`` are the caller's closure contracts, keyed by scope IRI.
    """

    def __init__(self, runner: SparqlRunner, scopes: Iterable[ClosedWorldScope] = ()) -> None:
        self._runner = runner
        self._scopes = {s.scope_iri: s for s in scopes}

    @property
    def scopes(self) -> dict[str, ClosedWorldScope]:
        return dict(self._scopes)

    async def declared_scope_iris(self) -> list[str]:
        """Scope IRIs that at least one subject joins with ``fi:closedUnder``."""
        rows = _rows(await self._runner.query(
            f"SELECT DISTINCT ?scope WHERE {{ ?s <{CLOSED_UNDER}> ?scope }} ORDER BY ?scope"
        ))
        return [r["scope"].value for r in rows]

    async def _bound_scope(
        self, subject: str, *, cls: str | None, prop: str
    ) -> ClosedWorldScope | None:
        """The registered scope that ``subject`` is closed under and that covers
        the question, or ``None``."""
        rows = _rows(await self._runner.query(
            f"SELECT DISTINCT ?scope WHERE {{ VALUES ?s {{ {_iri(subject)} }} "
            f"?s <{CLOSED_UNDER}> ?scope }} ORDER BY ?scope"
        ))
        for row in rows:
            scope = self._scopes.get(row["scope"].value)
            if scope is not None and scope.covers(cls=cls, prop=prop):
                return scope
        return None

    async def count_related(self, subject: str, prop: str) -> RelatedCount:
        """Count the objects of ``subject prop ?o`` ("all parties to a contract").

        Closed only when ``subject`` is ``fi:closedUnder`` a registered scope
        whose closed properties include ``prop``: the asserted set is then the
        whole set. Otherwise the same asserted set is returned as open.
        """
        subj, pred = _iri(subject), _iri(prop)
        scope = await self._bound_scope(subject, cls=None, prop=prop)
        rows = _rows(await self._runner.query(
            f"SELECT DISTINCT ?o WHERE {{ VALUES ?s {{ {subj} }} VALUES ?p {{ {pred} }} "
            f"?s ?p ?o }} ORDER BY ?o"
        ))
        items = tuple(r["o"].value for r in rows)
        if scope is not None:
            return RelatedCount("closed", len(items), scope.scope_iri, None, items)
        return RelatedCount("open", len(items), None, OPEN_NOTE, items)

    async def count_lacking(self, cls: str, prop: str, scope_iri: str) -> LackingCount:
        """Count instances of ``cls`` that have no ``prop``.

        Closed (``FILTER NOT EXISTS`` runs) only when ``scope_iri`` is
        registered, closes both ``cls`` and ``prop``, and instances join it with
        ``fi:closedUnder``; the count is over those members. Otherwise no
        negation runs: ``count`` is ``None`` and the positive evidence (instances
        of the class, and those with an asserted ``prop``) is returned.
        """
        klass, pred, scope_ref = _iri(cls), _iri(prop), _iri(scope_iri)
        scope = self._scopes.get(scope_iri)
        members = (
            f"VALUES ?c {{ {klass} }} VALUES ?p {{ {pred} }} VALUES ?scope {{ {scope_ref} }} "
            f"?s <{RDF_TYPE}> ?c . ?s <{CLOSED_UNDER}> ?scope ."
        )
        if scope is not None and scope.covers(cls=cls, prop=prop):
            bound = _rows(await self._runner.query(
                f"SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {{ {members} }}"
            ))
            if bound and _n(bound[0]) > 0:
                lacking = _rows(await self._runner.query(
                    f"SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {{ {members} "
                    f"FILTER NOT EXISTS {{ ?s ?p ?o }} }}"
                ))
                total = _n(bound[0])
                n = _n(lacking[0]) if lacking else 0
                return LackingCount("closed", n, scope_iri, None, total, total - n)
        total_rows = _rows(await self._runner.query(
            f"SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {{ VALUES ?c {{ {klass} }} "
            f"?s <{RDF_TYPE}> ?c }}"
        ))
        with_rows = _rows(await self._runner.query(
            f"SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE {{ VALUES ?c {{ {klass} }} "
            f"VALUES ?p {{ {pred} }} ?s <{RDF_TYPE}> ?c . ?s ?p ?o }}"
        ))
        return LackingCount(
            "open", None, None, OPEN_NOTE,
            _n(total_rows[0]) if total_rows else 0,
            _n(with_rows[0]) if with_rows else 0,
        )


#: Public count APIs; the introspection test requires each to return a
#: ``CountResult`` subtype (so each declares its world assumption).
COUNT_APIS: tuple[str, ...] = ("count_related", "count_lacking")

__all__ = [
    "CLOSED_UNDER", "COUNT_APIS", "ClosedWorldQuery", "ClosedWorldScope", "CountResult",
    "InvalidIri", "LackingCount", "OPEN_NOTE", "RelatedCount", "SparqlRunner",
    "WorldAssumption",
]
