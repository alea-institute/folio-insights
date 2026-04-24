"""SPARQL-based axiom-disjointness check (OQ-1 per orchestrator lock).

Rule 1 authoritative signal: 'framework-conflicting axiom' at Phase 1 =
owl:disjointWith assertion in the TBox between framework-scoped classes
attached to shards carrying the same termOfArt.

If no such assertion exists (common case at Phase 1 — TBox is sparse / not
yet populated in fixtures), return False (treated as 'insufficient-evidence',
NOT as 'maybe polysemous'). Orchestrator OQ-1 lock: we DO NOT fall through
to embeddings for this signal in Phase 1; embeddings remain reporting-only
evidence scores (prototype_cluster.centroid_distance_signal).

SEC-01 discipline: all SPARQL goes through PyoxigraphStore.query_rdf12 (SERVICE
preflight) — raw pyoxigraph.Store access is forbidden per Phase 0 wrapper.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from pyoxigraph import NamedNode

if TYPE_CHECKING:
    from folio_insights.store.pyoxigraph_store import PyoxigraphStore

CONSIDERATION_NAMED_GRAPH = "urn:folio:corpus/consideration-spike"


# NOTE — T-01-07 disposition: .format() interpolation is acceptable here
# because:
#   - `graph` is a module-level constant or caller-supplied named-graph URN
#   - `term` comes from hand-curated ShardFixture JSON (not user input)
#   - `fw_a`, `fw_b` are drawn from the locked Framework Literal enum
#     (fixture_loader.Framework = CommonLaw | CivilLaw | Restatement | FRE | UCC)
# Phase 16 will parametrize this via pyoxigraph initBindings once we ship a
# public SPARQL surface.
_DISJOINT_ASK = """
PREFIX fi: <https://folio-insights.aleainstitute.ai/vocab/>
PREFIX owl: <http://www.w3.org/2002/07/owl#>

ASK {{
  GRAPH <{graph}> {{
    ?shard_a fi:termOfArt "{term}" ; fi:inFramework "{fw_a}" .
    ?shard_b fi:termOfArt "{term}" ; fi:inFramework "{fw_b}" .
    ?class_a owl:disjointWith ?class_b .
    FILTER (?shard_a != ?shard_b)
  }}
}}
"""


def has_framework_conflicting_axiom(
    store: "PyoxigraphStore",
    term: str,
    frameworks: list[str],
    named_graph: str = CONSIDERATION_NAMED_GRAPH,
) -> bool:
    """Return True iff ANY pair of frameworks has an owl:disjointWith TBox
    assertion between their term-scoped classes in `named_graph`.

    Queries via PyoxigraphStore.query_rdf12 so SEC-01 SERVICE preflight
    is inherited (raw pyoxigraph.Store is forbidden per Phase 0 wrapper
    and by T-01-10 in the threat register).

    At Phase 1 the TBox is typically empty → returns False → detector Rule 1
    short-circuits to 'coincidence' with matched_rules=['R1-no-conflict'].
    This is the intended default (OQ-1 orchestrator lock): absence of an
    explicit axiom-conflict assertion means we do NOT treat cosine distance
    as enough evidence.

    Iterates all ordered pairs (sorted for determinism) and short-circuits
    on first True. Each ASK is a cheap graph pattern; a handful of framework
    pairs is acceptable at Phase 1 (O(n^2) with n ≤ 5 Frameworks).
    """
    sorted_fw = sorted(frameworks)
    for i, fw_a in enumerate(sorted_fw):
        for fw_b in sorted_fw[i + 1:]:
            sparql = _DISJOINT_ASK.format(
                graph=named_graph, term=term, fw_a=fw_a, fw_b=fw_b,
            )
            result = store.query_rdf12(
                sparql, named_graphs=[NamedNode(named_graph)],
            )
            # pyoxigraph ASK returns a QueryBoolean (truthy). Normalize to
            # bool so the return type is a clean Python bool regardless of
            # pyoxigraph version.
            if bool(result):
                return True
    return False
