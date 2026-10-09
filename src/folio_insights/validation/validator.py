"""The cluster validator: clusters, checkers, one report (Phase 9 U1, R4).
WORKER TIER ONLY (it drives ``validation.consistency``).

``ClusterValidator.validate`` builds the clusters, runs the consistency check
on each, runs the corpus-level coverage and cross-reference checks, attaches
cluster context to every finding (each cluster that holds all of its shards)
and returns a ``ValidationReport``. ``validate_corpus`` does the same for a
``CorpusStorageContext``: it reads the current shards and the corpus
framework registry and nothing else.

Nothing here writes. The store is read through ``iter_shards`` and
``load_registry`` only, and the report's proposals are never applied
(``ValidationReport.applied`` is always ``False``).
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from folio_insights.validation.clusters import (
    CLUSTER_AXES,
    DEFAULT_DOCTRINAL_DEPTH,
    ClusterAxis,
    ClusterBuilder,
)
from folio_insights.validation.consistency import (
    DEFAULT_NLI_THRESHOLD,
    ClusterConsistency,
    ConsistencyChecker,
)
from folio_insights.validation.coverage import CoverageChecker, TaskNode
from folio_insights.validation.crossref import CrossReferenceChecker
from folio_insights.validation.report import (
    CheckerStatus,
    ClusterResult,
    Finding,
    ValidationReport,
)

if TYPE_CHECKING:
    from folio_insights.bfo.spine import BranchResolver
    from folio_insights.models.framework import FrameworkRegistry
    from folio_insights.shards import ShardEnvelope
    from folio_insights.storage.context import CorpusStorageContext
    from folio_insights.validation.formal import FormalReasoner, Triple3
    from folio_insights.validation.nli import NliScorer

_KIND_ORDER = {
    "contradiction": 0,
    "unsatisfiable_class": 1,
    "tbox_inconsistent": 2,
    "cross_framework_citation": 3,
    "coverage_gap": 4,
}


@dataclass
class ClusterValidator:
    """Clusters plus the three checkers. A checker left ``None`` is reported
    as not requested, never as passed."""

    builder: ClusterBuilder
    consistency: ConsistencyChecker | None = None
    coverage: CoverageChecker | None = None
    crossref: CrossReferenceChecker | None = None

    def validate(
        self,
        shards: Iterable[ShardEnvelope],
        *,
        tasks: Iterable[TaskNode] | None = None,
        corpus: str = "",
    ) -> ValidationReport:
        by_iri: dict[str, ShardEnvelope] = {}
        for shard in shards:
            by_iri[shard.shard_iri] = shard
        current = [by_iri[k] for k in sorted(by_iri)]
        cluster_set = self.builder.build(current)
        findings: dict[str, Finding] = {}
        results: list[ClusterResult] = []
        for cluster in cluster_set.clusters:
            if self.consistency is not None:
                checked = self.consistency.check_cluster(cluster, by_iri)
            else:
                checked = ClusterConsistency(mode="unchecked", notes=["consistency check not requested"])
            for finding in checked.findings:
                findings.setdefault(finding.id, finding.model_copy(deep=True))
            results.append(ClusterResult(
                id=cluster.id,
                axis=cluster.axis,
                key=cluster.key,
                size=cluster.size,
                members=list(cluster.members),
                mode=checked.mode,
                checkers=list(checked.checkers),
                notes=list(checked.notes),
                formal_axiom_count=checked.formal_axiom_count,
                finding_ids=sorted({f.id for f in checked.findings}),
            ))
        status = CheckerStatus()
        if self.consistency is not None:
            status.hermit = self.consistency.reasoner_status
            status.nli = self.consistency.nli_status
        if self.coverage is not None:
            if tasks is None:
                status.coverage = "skipped: no task tree supplied"
            else:
                status.coverage = "ran"
                for finding in self.coverage.check(tasks, current):
                    findings.setdefault(finding.id, finding)
        if self.crossref is not None:
            status.crossref = "ran"
            for finding in self.crossref.check(current):
                findings.setdefault(finding.id, finding)
        for finding in findings.values():
            finding.clusters = [c.id for c in cluster_set.containing(finding.shards)]
        ordered = sorted(
            findings.values(),
            key=lambda f: (_KIND_ORDER.get(f.kind, 9), f.severity != "warning", f.shards, f.id),
        )
        return ValidationReport(
            corpus=corpus,
            shard_count=len(current),
            axes=list(self.builder.axes),
            checkers=status,
            clusters=results,
            findings=ordered,
            diagnostics=cluster_set.diagnostics(),
        )


def build_validator(
    registry: FrameworkRegistry | None,
    *,
    folio_resolver: BranchResolver | None = None,
    doctrinal_depth: int = DEFAULT_DOCTRINAL_DEPTH,
    axes: Sequence[ClusterAxis] = CLUSTER_AXES,
    min_size: int = 2,
    consistency: bool = True,
    reasoner: FormalReasoner | Literal["auto"] | None = "auto",
    nli: NliScorer | None = None,
    nli_threshold: float = DEFAULT_NLI_THRESHOLD,
    tbox: Iterable[Triple3] = (),
    disjoint_seeds: Iterable[tuple[str, str]] = (),
    coverage: bool = True,
    crossref: bool = True,
    allowed_framework_pairs: Iterable[tuple[str, str]] = (),
    **consistency_options: Any,
) -> ClusterValidator:
    """A ``ClusterValidator`` wired from plain options (the CLI's builder)."""
    builder = ClusterBuilder(
        registry=registry,
        folio_resolver=folio_resolver,
        doctrinal_depth=doctrinal_depth,
        axes=axes,
        min_size=min_size,
    )
    checker = None
    if consistency:
        checker = ConsistencyChecker(
            reasoner=reasoner,
            nli=nli,
            tbox=tbox,
            disjoint_seeds=disjoint_seeds,
            nli_threshold=nli_threshold,
            jurisdiction_of=builder.jurisdiction_of,
            **consistency_options,
        )
    return ClusterValidator(
        builder=builder,
        consistency=checker,
        coverage=CoverageChecker(folio_resolver=folio_resolver) if coverage else None,
        crossref=(
            CrossReferenceChecker(registry, allowed_pairs=allowed_framework_pairs)
            if crossref else None
        ),
    )


async def load_corpus_inputs(
    ctx: CorpusStorageContext,
) -> tuple[list[ShardEnvelope], FrameworkRegistry]:
    """The corpus's current shards and its framework registry (read-only)."""
    from folio_insights.frameworks.registry import load_registry

    shards = [s async for s in ctx.shards.iter_shards()]
    return shards, await load_registry(ctx)


async def validate_corpus(
    ctx: CorpusStorageContext,
    *,
    tasks: Iterable[TaskNode] | None = None,
    **options: Any,
) -> ValidationReport:
    """Validate every cluster of ``ctx``'s corpus (``build_validator`` options)."""
    shards, registry = await load_corpus_inputs(ctx)
    validator = build_validator(registry, **options)
    return validator.validate(shards, tasks=tasks, corpus=ctx.corpus)


__all__ = [
    "ClusterValidator",
    "build_validator",
    "load_corpus_inputs",
    "validate_corpus",
]
