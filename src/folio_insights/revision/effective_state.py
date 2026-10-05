"""Derived effective state of shards (Phase 9 U3, KTD2/KTD7; PRD §8 P3).

Revision never rewrites a shard. Supersession, retraction and contest are
signed governance events; what they mean for each shard is DERIVED here from
the current shard records plus the event history, and nothing is written
back:

* **Supersession** — the old shard reads ``superseded`` with
  ``superseded_by`` and an effective ``valid_time_end`` from the event: the
  successor's ``valid_time_start`` when it has one (the SHACL supersession
  alignment rule), else the event's signing time. Both shards stay
  queryable; ``as_of_graph`` exposes the effective windows to
  ``temporal.query_as_of``.
* **Retraction** — the shard reads ``retracted``; its direct dependents get
  the cascade policy outcome (``auto_rederive`` / ``aporetic`` /
  ``review_needed``), and dependents two or more hops away read
  ``review_needed`` (flag-only; Decision Sheet q4).
* **Contest** — the shard reads ``contested`` until a resolution event; a
  resolution by arbiter or distinguo reads ``resolved``, an aporetic one
  ``aporetic``.

Precedence when several apply: ``retracted`` > ``superseded`` > a cascade
outcome > contest state > ``current``.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from folio_insights.governance.events import (
    ContestEvent,
    ContestResolutionEvent,
    RetractionEvent,
    SupersessionEvent,
)
from folio_insights.revision.dependency_graph import DependencyGraph
from folio_insights.revision.policies import (
    DEFAULT_CASCADE_POLICY,
    CascadePolicy,
    check_policy,
    classify_at_depth,
)

if TYPE_CHECKING:
    from rdflib import Graph

    from folio_insights.governance.log import GovernanceLog
    from folio_insights.revision.store import ShardStore
    from folio_insights.shards import ShardEnvelope

EffectiveStatus = Literal[
    "current",
    "superseded",
    "retracted",
    "auto_rederive",
    "aporetic",
    "review_needed",
    "contested",
    "resolved",
]

_RANK: dict[str, int] = {
    "current": 0,
    "contested": 1,
    "resolved": 1,
    "aporetic": 2,
    "auto_rederive": 2,
    "review_needed": 2,
    "superseded": 3,
    "retracted": 4,
}
_CASCADE = frozenset({"auto_rederive", "aporetic", "review_needed"})


@dataclass(frozen=True)
class EffectiveState:
    """A shard's derived state. ``events`` are the governance positions it
    rests on; ``cause`` names the retracted shard behind a cascade outcome."""

    shard_iri: str
    status: EffectiveStatus = "current"
    superseded_by: str | None = None
    valid_time_end: datetime | None = None
    cause: str | None = None
    depth: int | None = None
    contest_resolution: str | None = None
    events: tuple[int, ...] = field(default_factory=tuple)


def _rank(status: str) -> int:
    return _RANK[status]


def derive_effective_states(
    shards: Iterable[ShardEnvelope],
    events: Iterable[Any],
    *,
    policy: CascadePolicy = DEFAULT_CASCADE_POLICY,
    graph: DependencyGraph | None = None,
) -> dict[str, EffectiveState]:
    """The effective state of every shard, from records plus governance events.

    ``events`` are applied in log-position order. ``policy`` is the cascade
    policy the retractions were committed under (a retraction's saved preview
    records it). ``graph`` defaults to the graph of ``shards``.
    """
    policy = check_policy(policy)
    by_iri = {s.shard_iri: s for s in shards}
    graph = graph if graph is not None else DependencyGraph.from_shards(by_iri.values())
    state = {iri: EffectiveState(iri) for iri in sorted(by_iri)}
    ordered = sorted(events, key=lambda e: e.position)

    def put(iri: str, new: EffectiveState) -> None:
        if iri in state:
            state[iri] = new

    def touch(iri: str, position: int, **changes: Any) -> None:
        if iri not in state:
            return
        old = state[iri]
        status = changes.get("status", old.status)
        if _rank(status) < _rank(old.status):
            changes = {}  # a weaker effect never overrides a stronger state
        put(iri, replace(old, events=old.events + (position,), **changes))

    # 1. supersession (needed first: a retraction re-derives against successors)
    for event in ordered:
        if isinstance(event, SupersessionEvent):
            successor = by_iri.get(event.new_shard_iri)
            end = (
                successor.valid_time_start
                if successor is not None and successor.valid_time_start is not None
                else event.signature.signed_at
            )
            touch(
                event.old_shard_iri,
                event.position,
                status="superseded",
                superseded_by=event.new_shard_iri,
                valid_time_end=end,
            )

    def successor_of(iri: str) -> str | None:
        derived = state.get(iri)
        if derived is not None and derived.superseded_by is not None:
            return derived.superseded_by
        record = by_iri.get(iri)
        return None if record is None else record.superseded_by

    # 2. contests and resolutions, in order
    for event in ordered:
        if isinstance(event, ContestEvent):
            touch(event.shard_iri, event.position, status="contested", contest_resolution=None)
        elif isinstance(event, ContestResolutionEvent):
            current = state.get(event.shard_iri)
            if current is not None and current.status in {"contested", "resolved", "aporetic"}:
                put(
                    event.shard_iri,
                    replace(
                        current,
                        status="aporetic" if event.resolution_path == "aporetic" else "resolved",
                        contest_resolution=event.resolution_path,
                        events=current.events + (event.position,),
                    ),
                )

    # 3. retractions and their graded cascade
    for event in ordered:
        if not isinstance(event, RetractionEvent):
            continue
        target = event.shard_iri
        touch(target, event.position, status="retracted")
        successor_iri = successor_of(target)
        successor = by_iri.get(successor_iri) if successor_iri else None
        for dep_iri, depth in sorted(graph.transitive_dependents(target).items()):
            dep = by_iri.get(dep_iri)
            if dep is None or dep_iri == target:
                continue
            attrs = dependent_attrs(dep, successor_iri=successor_iri, successor=successor)
            current = state[dep_iri]
            if current.status == "contested":
                attrs["epistemic_status"] = "contested"
            bucket = classify_at_depth(depth, attrs, policy=policy)
            if current.status in _CASCADE and current.depth is not None and current.depth < depth:
                continue  # an earlier, closer retraction already decided it
            touch(dep_iri, event.position, status=bucket, cause=target, depth=depth)
    return state


def dependent_attrs(
    dep: ShardEnvelope, *, successor_iri: str | None, successor: ShardEnvelope | None
) -> dict[str, Any]:
    """The classifier inputs of one dependent (``revision.policies``)."""
    votes = len(dep.contest_votes or {}) if dep.contested else 0
    return {
        "supersession_available": successor_iri is not None,
        "reconciliation_strategy": getattr(dep, "reconciliation_strategy", None),
        "epistemic_status": dep.epistemic_status,
        "unresolved_contest_count": votes,
        "successor_epistemic_status": None if successor is None else successor.epistemic_status,
        "successor_framework_id": None if successor is None else successor.framework_id,
        "dependent_framework_id": dep.framework_id,
    }


async def effective_states(
    store: ShardStore,
    log: GovernanceLog,
    *,
    policy: CascadePolicy = DEFAULT_CASCADE_POLICY,
) -> dict[str, EffectiveState]:
    """``derive_effective_states`` over a store and its corpus governance log
    (the persistent store reads both at the committed watermark)."""
    shards = [s async for s in store.iter_shards()]
    events = [e async for e in log.iter_events(store.corpus)]
    graph = await DependencyGraph.from_store(store)
    return derive_effective_states(shards, events, policy=policy, graph=graph)


def as_of_graph(
    shards: Iterable[ShardEnvelope],
    states: Mapping[str, EffectiveState],
    *,
    fields: Iterable[str] = ("sense", "reference", "framework_id"),
) -> Graph:
    """An rdflib graph of each shard's ``fields`` plus its EFFECTIVE valid-time
    window, for ``temporal.query_as_of`` (fi:<camelCase(field)> predicates).

    A superseded shard's window ends at its effective ``valid_time_end``; a
    retracted shard is left out (it holds at no time).
    """
    from rdflib import Graph, Literal, URIRef
    from rdflib.namespace import XSD

    from folio_insights.vocab._constants import FI_PREFIX

    def pred(name: str) -> URIRef:
        head, *rest = name.split("_")
        return URIRef(FI_PREFIX + head + "".join(p[:1].upper() + p[1:] for p in rest))

    g = Graph()
    for shard in shards:
        derived = states.get(shard.shard_iri, EffectiveState(shard.shard_iri))
        if derived.status == "retracted" or shard.valid_time_start is None:
            continue
        s = URIRef(shard.shard_iri)
        for name in fields:
            g.add((s, pred(name), Literal(getattr(shard, name))))
        g.add((s, pred("valid_time_start"),
               Literal(shard.valid_time_start.isoformat(), datatype=XSD.dateTime)))
        end = derived.valid_time_end or shard.valid_time_end
        if end is not None:
            g.add((s, pred("valid_time_end"), Literal(end.isoformat(), datatype=XSD.dateTime)))
        if shard.supersedes:
            g.add((s, URIRef(FI_PREFIX + "supersedes"), URIRef(shard.supersedes)))
    return g


__all__ = [
    "EffectiveState",
    "EffectiveStatus",
    "as_of_graph",
    "dependent_attrs",
    "derive_effective_states",
    "effective_states",
]
