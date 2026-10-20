"""Polysemy candidates from P1 clusters and P2 frameworks (Phase 9 U6).

PRD §8 P6: "when the cluster validator detects same-IRI shards with
incompatible axioms across frameworks, the system proposes forking the IRI".
This module finds the "same IRI across frameworks" part:

* it reads the P1 ``ClusterSet`` (``validation.clusters``) — by default its
  doctrinal clusters, the shards that share a FOLIO neighbourhood — and, inside
  each cluster, groups member shards by concept IRI (``shard_concepts``);
* it resolves each shard's ``framework_id`` through the P2 corpus
  ``FrameworkRegistry``; a shard whose framework is unregistered is reported,
  never guessed into a framework;
* a concept used by shards in two or more registered frameworks is a
  candidate, returned as ``ShardFixture`` rows keyed by framework ID, ready for
  ``prototype_cluster.build_prototype_cluster`` and ``detector.detect_polysemy``.

A candidate's axiom proxy is the shard's ``logical_form_imputed`` (Pitfall 1:
axioms, never surface text); its term is the concept IRI, so Rule 1's
term-scoped classes are ``tbox.term_class_iri(concept_iri, framework_id)``.
Deterministic: candidates sort by term, shards by IRI.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from folio_insights.polysemy.fixture_loader import ShardFixture
from folio_insights.validation.clusters import is_folio_concept, shard_concepts

if TYPE_CHECKING:
    from folio_insights.models.framework import FrameworkRegistry
    from folio_insights.shards import ShardEnvelope
    from folio_insights.validation.clusters import ClusterAxis, ClusterSet


@dataclass(frozen=True)
class PolysemyCandidate:
    """One concept IRI used in two or more registered frameworks."""

    term: str
    shards: tuple[ShardFixture, ...]
    clusters: tuple[str, ...]  # the P1 cluster IDs the candidate came from

    @property
    def frameworks(self) -> tuple[str, ...]:
        return tuple(sorted({s.framework for s in self.shards}))


@dataclass
class CandidateSet:
    candidates: list[PolysemyCandidate]
    # framework_id -> shard IRIs whose framework the registry does not know.
    unregistered_frameworks: dict[str, list[str]] = field(default_factory=dict)


def _fixture(shard: ShardEnvelope, term: str) -> ShardFixture:
    return ShardFixture(
        iri=shard.shard_iri,
        framework=shard.framework_id,
        source_doc=shard.source_uri,
        extracted_text=shard.sense or shard.logical_form_imputed,
        axiom_summary=shard.logical_form_imputed,
        term=term,
    )


def polysemy_candidates(
    shards: Iterable[ShardEnvelope],
    clusters: ClusterSet,
    registry: FrameworkRegistry,
    *,
    axes: tuple[ClusterAxis, ...] = ("doctrinal",),
    concept_filter: Callable[[str], bool] = is_folio_concept,
) -> CandidateSet:
    """Concepts that span registered frameworks inside the P1 clusters on ``axes``."""
    by_iri = {s.shard_iri: s for s in shards}
    unregistered: dict[str, set[str]] = defaultdict(set)
    # term -> framework_id -> shard IRIs; term -> cluster IDs
    grouped: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    sources: dict[str, set[str]] = defaultdict(set)
    for cluster in clusters.clusters:
        if cluster.axis not in axes:
            continue
        for iri in cluster.members:
            shard = by_iri.get(iri)
            if shard is None:
                continue
            if shard.framework_id not in registry:
                unregistered[shard.framework_id].add(iri)
                continue
            for concept in shard_concepts(shard, concept_filter):
                grouped[concept][shard.framework_id].add(iri)
                sources[concept].add(cluster.id)
    candidates = []
    for term in sorted(grouped):
        per_framework = grouped[term]
        if len(per_framework) < 2:
            continue
        rows = tuple(
            _fixture(by_iri[iri], term)
            for framework_id in sorted(per_framework)
            for iri in sorted(per_framework[framework_id])
        )
        candidates.append(PolysemyCandidate(term, rows, tuple(sorted(sources[term]))))
    return CandidateSet(
        candidates=candidates,
        unregistered_frameworks={k: sorted(v) for k, v in sorted(unregistered.items())},
    )


__all__ = ["CandidateSet", "PolysemyCandidate", "polysemy_candidates"]
