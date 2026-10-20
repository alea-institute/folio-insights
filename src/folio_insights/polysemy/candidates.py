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
axioms, never surface text). Its term is the concept's label, normalized
(``tbox.normalize_term``): from ``concept_label`` when the caller supplies one
(FOLIO's ``rdfs:label``), else from the IRI's local name (``concept_term``:
"GoodFaith" -> "good faith"). So Rule 1's term-scoped classes,
``tbox.term_class_iri(term, framework_id)``, are the ones the shipped seeds
name, and the seeds fire on this path. The concept IRI is kept on the
candidate. Deterministic: candidates sort by term then concept, shards by IRI.
"""
from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import unquote

from folio_insights.polysemy.fixture_loader import ShardFixture
from folio_insights.polysemy.tbox import normalize_term
from folio_insights.validation.clusters import is_folio_concept, shard_concepts

if TYPE_CHECKING:
    from folio_insights.models.framework import FrameworkRegistry
    from folio_insights.shards import ShardEnvelope
    from folio_insights.validation.clusters import ClusterAxis, ClusterSet


_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def concept_term(concept_iri: str) -> str:
    """A term key from a concept IRI's local name: the part after the last
    ``#`` or ``/``, CamelCase and ``_``/``-`` split into words, normalized."""
    local = unquote(re.split(r"[#/]", concept_iri.rstrip("/#"))[-1])
    return normalize_term(_CAMEL.sub(" ", local).replace("_", " ").replace("-", " "))


@dataclass(frozen=True)
class PolysemyCandidate:
    """One concept IRI used in two or more registered frameworks."""

    term: str  # the normalized term key Rule 1 and the seeds use
    shards: tuple[ShardFixture, ...]
    clusters: tuple[str, ...]  # the P1 cluster IDs the candidate came from
    concept: str = ""          # the concept IRI the shards are about

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
    concept_label: Callable[[str], str | None] | None = None,
) -> CandidateSet:
    """Concepts that span registered frameworks inside the P1 clusters on ``axes``.

    ``concept_label`` maps a concept IRI to its label (None: unknown); the
    term key falls back to the IRI's local name (``concept_term``).
    """

    def term_of(concept: str) -> str:
        label = concept_label(concept) if concept_label is not None else None
        return normalize_term(label) if label and label.strip() else concept_term(concept)

    by_iri = {s.shard_iri: s for s in shards}
    unregistered: dict[str, set[str]] = defaultdict(set)
    # concept -> framework_id -> shard IRIs; concept -> cluster IDs
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
    for concept in sorted(grouped):
        per_framework = grouped[concept]
        if len(per_framework) < 2:
            continue
        term = term_of(concept)
        rows = tuple(
            _fixture(by_iri[iri], term)
            for framework_id in sorted(per_framework)
            for iri in sorted(per_framework[framework_id])
        )
        candidates.append(
            PolysemyCandidate(term, rows, tuple(sorted(sources[concept])), concept=concept)
        )
    candidates.sort(key=lambda c: (c.term, c.concept))
    return CandidateSet(
        candidates=candidates,
        unregistered_frameworks={k: sorted(v) for k, v in sorted(unregistered.items())},
    )


__all__ = ["CandidateSet", "PolysemyCandidate", "concept_term", "polysemy_candidates"]
