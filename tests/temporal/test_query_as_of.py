"""Phase 8 Plan 08-03 Task 1 — query_as_of timepoint tests (D-10 / VOCAB-05).

Five timepoint cases against the 10-link supersession chain fixture:
  (a) t before chain start                 → empty result
  (b) t inside link 1                       → link 1's (subject, "object1")
  (c) t inside link 5 (middle of chain)     → link 5's (subject, "object5")
  (d) t inside link 10 (open-ended current) → link 10's (subject, "object10")
  (e) t far in the future (still inside link 10's open-ended interval)
      → link 10 again — confirms the (!BOUND(?end) || ...) branch.

Discretion handle (CONTEXT.md D-10): signature accepts ``rdflib.Graph`` only
(V1 minimum). Phase 11 widens to ``Graph | Store`` polymorphic when the
persistent pyoxigraph store lands.

D-11 reminder: ``--as-of <date>`` CLI flag remains explicitly out of Phase 8
scope. Phase 11 (triplestore) or Phase 12 (UI) ship the user-facing surface;
this test pins only the library helper.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import XSD

from folio_insights.temporal.as_of import query_as_of


_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "supersession_chain.ttl"
_EXAMPLE_PREDICATE = URIRef("https://folio-insights.aleainstitute.ai/vocab/exampleProperty")


def _load_chain_graph() -> Graph:
    g = Graph()
    g.parse(str(_FIXTURE_PATH), format="turtle")
    return g


def _dt(year: int, month: int, day: int) -> datetime:
    """xsd:dateTime helper — UTC-aware so the SPARQL FILTER compares apples to apples."""
    return datetime(year, month, day, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Five timepoint tests (D-10)
# ---------------------------------------------------------------------------


def test_t_before_chain_start_returns_empty() -> None:
    """Case (a): 2025-12-15 is before link 1's start (2026-01-01) → no rows."""
    g = _load_chain_graph()
    rows = query_as_of(g, _EXAMPLE_PREDICATE, _dt(2025, 12, 15))
    assert rows == [], (
        f"Expected empty result before chain start; got {rows!r}"
    )


def test_t_inside_link_1_returns_link_1_binding() -> None:
    """Case (b): 2026-01-15 falls inside [2026-01-01, 2026-02-01) → link 1."""
    g = _load_chain_graph()
    rows = query_as_of(g, _EXAMPLE_PREDICATE, _dt(2026, 1, 15))
    assert len(rows) == 1, f"Expected exactly 1 row for link 1; got {rows!r}"
    subject, obj = rows[0]
    assert subject == URIRef("urn:test:shard/v1")
    assert str(obj) == "object1"


def test_t_inside_link_5_returns_link_5_binding() -> None:
    """Case (c): 2026-05-15 falls inside [2026-05-01, 2026-06-01) → link 5."""
    g = _load_chain_graph()
    rows = query_as_of(g, _EXAMPLE_PREDICATE, _dt(2026, 5, 15))
    assert len(rows) == 1, f"Expected exactly 1 row for link 5; got {rows!r}"
    subject, obj = rows[0]
    assert subject == URIRef("urn:test:shard/v5")
    assert str(obj) == "object5"


def test_t_inside_link_10_returns_link_10_binding() -> None:
    """Case (d): 2026-10-15 falls inside [2026-10-01, ∞) → link 10 (open-ended)."""
    g = _load_chain_graph()
    rows = query_as_of(g, _EXAMPLE_PREDICATE, _dt(2026, 10, 15))
    assert len(rows) == 1, f"Expected exactly 1 row for link 10; got {rows!r}"
    subject, obj = rows[0]
    assert subject == URIRef("urn:test:shard/v10")
    assert str(obj) == "object10"


def test_t_far_future_still_matches_open_ended_link_10() -> None:
    """Case (e): 2099-01-01 is well past every other link but still inside link
    10's open-ended interval ([2026-10-01, ∞)) → link 10. This pins the
    ``!BOUND(?end) || ?at < ?end`` FILTER branch (CONTEXT.md D-10).
    """
    g = _load_chain_graph()
    rows = query_as_of(g, _EXAMPLE_PREDICATE, _dt(2099, 1, 1))
    assert len(rows) == 1, f"Expected exactly 1 row from open-ended link; got {rows!r}"
    subject, obj = rows[0]
    assert subject == URIRef("urn:test:shard/v10")
    assert str(obj) == "object10"


# ---------------------------------------------------------------------------
# Bonus: closed-interval boundary semantics + SPARQL-injection guard
# ---------------------------------------------------------------------------


def test_t_exactly_at_boundary_falls_in_next_link() -> None:
    """Boundary semantics per PRD §21.9: interval is [start, end). At t equal
    to link 5's end (= link 6's start), the query must pick link 6, NOT link
    5 — half-open intervals.
    """
    g = _load_chain_graph()
    rows = query_as_of(g, _EXAMPLE_PREDICATE, _dt(2026, 6, 1))
    assert len(rows) == 1
    subject, _ = rows[0]
    assert subject == URIRef("urn:test:shard/v6"), (
        "Half-open interval [start, end) means t == end belongs to the NEXT "
        "link, not the current one (PRD §21.9 valid-time semantics)."
    )


def test_query_as_of_returns_empty_list_type_when_no_match() -> None:
    """Contract: the helper returns list (or compatible sequence) even when
    no row matches. Callers should not need to None-check.
    """
    g = _load_chain_graph()
    rows = query_as_of(g, _EXAMPLE_PREDICATE, _dt(1900, 1, 1))
    assert isinstance(rows, list)
    assert rows == []
