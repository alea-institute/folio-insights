"""Cluster-level validation of stored shards (Phase 9 U1, 9.P1, PRINCIPLE-01).

The shard is the unit of representation, never the unit of verification
(PHILOSOPHY.md P1, after Quine's confirmation holism): a shard that passes
every unit-level check can still contradict the shards around it. This
package groups a corpus's shards into clusters and checks each cluster as a
corporate body.

* ``clusters`` — ``ClusterBuilder`` groups shards on four axes: source
  document, Tractarian subtree (``elaborates``), doctrinal neighbourhood
  (shared FOLIO ancestor at a configurable depth) and jurisdiction (through
  the framework registry).
* ``consistency`` — ``ConsistencyChecker`` (worker tier): HermiT over each
  cluster's formal content, plus the NLI textual screen; every finding names
  the checker that produced it, and a cluster with no formal axioms falls
  back to NLI and says so (KTD4).
* ``coverage`` — ``CoverageChecker``: task-tree leaves without an authority
  shard.
* ``crossref`` — ``CrossReferenceChecker``: shards that cite shards in an
  incompatible framework.
* ``proposals`` — reconciliation proposals drawn from the eight
  ``ReconciliationStrategy`` values. Proposals are report data only; nothing
  in this package writes to a store.
* ``report`` — the structured report (JSON and human-readable).
* ``validator`` — ``ClusterValidator`` / ``validate_corpus`` (worker tier).
* ``cli`` — ``folio-insights validate clusters``.

Tiering (KTD4, RISK-1): ``consistency``, ``hermit`` and ``validator`` are
worker-tier modules. The web tier never imports them at module level, and
nothing here imports owlready2 except, lazily, ``validation.hermit`` through
``reason.hermit_harness`` (``tests/validation/test_dep_leak_guard.py``). This
``__init__`` re-exports only the web-safe modules.
"""
from __future__ import annotations

from folio_insights.validation.clusters import (
    CLUSTER_AXES,
    ClusterAxis,
    ClusterBuilder,
    ClusterSet,
    ShardCluster,
)
from folio_insights.validation.coverage import (
    AUTHORITY_SPEECH_ACTS,
    CoverageChecker,
    TaskNode,
    load_task_nodes,
    task_nodes_from_hierarchy,
)
from folio_insights.validation.crossref import CrossReferenceChecker
from folio_insights.validation.proposals import Proposal
from folio_insights.validation.report import Finding, ValidationReport

# Worker-tier modules, by dotted name. The dependency-leak guard reads this
# list: no web-tier module may import one of these at module level.
WORKER_TIER_MODULES: tuple[str, ...] = (
    "folio_insights.validation.consistency",
    "folio_insights.validation.hermit",
    "folio_insights.validation.validator",
)

__all__ = [
    "AUTHORITY_SPEECH_ACTS",
    "CLUSTER_AXES",
    "ClusterAxis",
    "ClusterBuilder",
    "ClusterSet",
    "CoverageChecker",
    "CrossReferenceChecker",
    "Finding",
    "Proposal",
    "ShardCluster",
    "TaskNode",
    "ValidationReport",
    "WORKER_TIER_MODULES",
    "load_task_nodes",
    "task_nodes_from_hierarchy",
]
