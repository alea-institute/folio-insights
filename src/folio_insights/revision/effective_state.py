"""Derived effective state of shards (Phase 9 U3, KTD2/KTD7; PRD §8 P3).

Revision never rewrites a shard. Supersession, retraction and contest are
signed governance events; what they mean for each shard is DERIVED here from
the current shard records plus the event history, and nothing is written
back:

* **Supersession** — the old shard reads ``superseded`` with
  ``superseded_by`` and an effective ``valid_time_end`` from the event: the
  successor's ``valid_time_start`` when it has one (the SHACL supersession
  alignment rule), else the time the event took effect: its server commit
  time where the log has one (R17 / KTD12), else its signing time. Both shards stay
  queryable; ``as_of_graph`` exposes the effective windows to
  ``temporal.query_as_of``.
* **Retraction** — the shard reads ``retracted``; its direct dependents get
  the outcome of the cascade policy recorded on the retraction event
  (``auto_rederive`` / ``aporetic`` / ``review_needed``; no recorded policy
  fails closed to ``review_needed``), and dependents two or more hops away
  read ``review_needed`` (flag-only; Decision Sheet q4).
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
    check_policy,
    classify_at_depth,
    resolve_successor,
    supersession_successors,
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
# Most conservative wins among equally close retractions (review P2-6).
_CONSERVATIVE: dict[str, int] = {"auto_rederive": 0, "aporetic": 1, "review_needed": 2}


@dataclass(frozen=True)
class EffectiveState:
    """A shard's derived state. ``events`` are the governance positions it
    rests on; ``cause`` names the retracted shard behind a cascade outcome."""

    shard_iri: str
    status: EffectiveStatus = "current"
    superseded_by: str | None = None
    valid_time_end: datetime | None = None
    cause: str | None = None
    causes: tuple[str, ...] = ()
    depth: int | None = None
    contest_resolution: str | None = None
    events: tuple[int, ...] = field(default_factory=tuple)


def _rank(status: str) -> int:
    return _RANK[status]


def derive_effective_states(
    shards: Iterable[ShardEnvelope],
    events: Iterable[Any],
    *,
    graph: DependencyGraph | None = None,
    event_times: Mapping[int, datetime | None] | None = None,
) -> dict[str, EffectiveState]:
    """The effective state of every shard, from records plus governance events.

    ``events`` are applied in log-position order. Each retraction re-applies
    the cascade policy recorded on ITS event; a retraction without one fails
    closed (every dependent reads ``review_needed``). The result does not
    depend on the order of retractions: a dependent takes its outcome from
    the closest retraction(s) reaching it, the most conservative bucket among
    those (review_needed > aporetic > auto_rederive), and lists every cause.
    ``graph`` defaults to the graph of ``shards``.

    ``event_times`` maps an event's log position to the time it took effect
    (the persistent log's server commit time). A supersession without a
    successor ``valid_time_start`` ends the old shard at that time, falling
    back to the signer-claimed ``signed_at`` only when none is supplied.
    """
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
            if successor is not None and successor.valid_time_start is not None:
                end = successor.valid_time_start
            else:
                committed = (event_times or {}).get(event.position)
                end = committed if committed is not None else event.signature.signed_at
            touch(
                event.old_shard_iri,
                event.position,
                status="superseded",
                superseded_by=event.new_shard_iri,
                valid_time_end=end,
            )

    successors = supersession_successors(ordered)

    def successor_of(iri: str) -> str | None:
        # Same resolution as the cascade preview (review P2-4).
        return resolve_successor(iri, by_iri.get(iri), successors)

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

    # 3. retractions and their graded cascade (order-independent)
    outcomes: dict[str, list[tuple[int, str, str, int]]] = {}
    for event in ordered:
        if not isinstance(event, RetractionEvent):
            continue
        target = event.shard_iri
        touch(target, event.position, status="retracted")
        policy = getattr(event, "policy", None)
        successor_iri = successor_of(target)
        successor = by_iri.get(successor_iri) if successor_iri else None
        for dep_iri, depth in sorted(graph.transitive_dependents(target).items()):
            dep = by_iri.get(dep_iri)
            if dep is None or dep_iri == target:
                continue
            if policy is None:
                bucket = "review_needed"  # no recorded policy: fail closed
            else:
                attrs = dependent_attrs(dep, successor_iri=successor_iri, successor=successor)
                if state[dep_iri].status == "contested":
                    attrs["epistemic_status"] = "contested"
                bucket = classify_at_depth(depth, attrs, policy=check_policy(policy))
            outcomes.setdefault(dep_iri, []).append((depth, bucket, target, event.position))
    for dep_iri, found in sorted(outcomes.items()):
        closest = min(d for d, *_ in found)
        at_closest = [o for o in found if o[0] == closest]
        bucket = max((b for _, b, _, _ in at_closest), key=_CONSERVATIVE.__getitem__)
        causes = tuple(sorted({c for _, _, c, _ in found}))
        positions = sorted({p for *_, p in found})
        for position in positions[:-1]:
            touch(dep_iri, position)
        touch(dep_iri, positions[-1], status=bucket, depth=closest,
              cause=min(c for d, b, c, _ in at_closest if b == bucket), causes=causes)
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
) -> dict[str, EffectiveState]:
    """``derive_effective_states`` over a store and its corpus governance log
    (the persistent store reads both at the committed watermark).

    Event times come from ``roles.timed_events``: each row's server commit
    time for the persistent log, ``signed_at`` for a log without a server
    clock."""
    from folio_insights.governance.roles import timed_events

    shards = [s async for s in store.iter_shards()]
    pairs = [pair async for pair in timed_events(store.corpus, log=log)]
    events = [event for event, _ in pairs]
    times = {event.position: at for event, at in pairs}
    graph = await DependencyGraph.from_store(store)
    return derive_effective_states(shards, events, graph=graph, event_times=times)


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
