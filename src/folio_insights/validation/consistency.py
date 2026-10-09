"""Per-cluster consistency: HermiT on formal content, NLI on text (Phase 9 U1,
KTD4). WORKER TIER ONLY.

Shards hold propositions as text plus typed links, so a pure reasoner pass
would find almost nothing; a pure text screen would miss what the ontology
entails. The ``ConsistencyChecker`` is therefore hybrid, per cluster:

* **Formal (``checker="hermit"``).** The cluster's formal content
  (``validation.formal``: the shards' all-IRI triples and dependency edges,
  the TBox slice they reach, the caller's ``owl:disjointWith`` seeds) goes to
  a ``FormalReasoner``, HermiT in the worker image. An inconsistent cluster
  is explained by deletion-based minimization: shards are dropped one at a
  time while the rest stays inconsistent, which leaves a minimal conflicting
  set; the background axioms that participate are minimized the same way.
  Up to ``max_conflicts`` disjoint conflicting sets are reported. A
  consistent cluster that makes a named class unsatisfiable (beyond what the
  TBox alone does) gets an ``unsatisfiable_class`` finding with the shards
  responsible.
* **Textual (``checker="nli"``).** Every shard pair in the cluster (minus
  supersession pairs) is scored by the NLI screen in both directions; a pair
  at or above ``nli_threshold`` is a ``contradiction`` finding.

A cluster with no formal axioms, or a run without a reasoner, falls back to
NLI and records why (``mode="nli_fallback"``); a cluster no checker could
examine reads ``unchecked``, never consistent. Each finding names its checker
and carries ranked reconciliation proposals (``validation.proposals``), which
are never applied.

The reasoner is reached only through ``validation.hermit`` (lazy owlready2);
importing this module in the web tier is refused by the dependency-leak guard
(``tests/validation/test_dep_leak_guard.py``) because it is the worker-tier
entry for cluster reasoning.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, TypeVar

from folio_insights.validation.formal import (
    OWL_DISJOINT_WITH,
    FormalReasoner,
    FormalVerdict,
    Triple3,
    dependency_axioms,
    shard_axioms,
    tbox_slice,
    terms_of,
)
from folio_insights.validation.proposals import JurisdictionOf, propose_for_conflict_set
from folio_insights.validation.report import ConsistencyMode, Finding, finding_id

if TYPE_CHECKING:
    from folio_insights.shards import ShardEnvelope
    from folio_insights.validation.clusters import ShardCluster
    from folio_insights.validation.nli import NliScorer

T = TypeVar("T")

DEFAULT_NLI_THRESHOLD = 0.7
DEFAULT_MAX_NLI_PAIRS = 20_000
DEFAULT_MAX_REASONER_CALLS = 200
DEFAULT_MAX_CONFLICTS = 5
DEFAULT_MAX_UNSATISFIABLE = 10
DEFAULT_MAX_BACKGROUND_MINIMIZATION = 48
_EXCERPT = 240


def shard_text(shard: ShardEnvelope) -> str:
    """The text the NLI screen compares: the shard's sense, else its span."""
    return (shard.sense or shard.source_span or "").strip()


def _excerpt(text: str) -> str:
    return text if len(text) <= _EXCERPT else text[: _EXCERPT - 1] + "…"


def _supersession_pair(a: ShardEnvelope, b: ShardEnvelope) -> bool:
    return (
        a.superseded_by == b.shard_iri
        or b.superseded_by == a.shard_iri
        or a.supersedes == b.shard_iri
        or b.supersedes == a.shard_iri
    )


class _BudgetExhausted(Exception):
    """The per-cluster reasoner call budget ran out mid-explanation."""


@dataclass
class ClusterConsistency:
    """How one cluster was checked and what was found."""

    mode: ConsistencyMode
    checkers: list[Literal["hermit", "nli"]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    formal_axiom_count: int = 0
    findings: list[Finding] = field(default_factory=list)


class ConsistencyChecker:
    """Hybrid HermiT + NLI consistency check over shard clusters.

    Args:
        reasoner: a ``FormalReasoner``; ``"auto"`` (default) uses HermiT when
            ``validation.hermit.hermit_available()`` says it can run, else
            none; ``None`` disables the formal check.
        nli: an ``NliScorer``; ``None`` disables the textual screen.
        tbox: TBox triples the formal check slices per cluster.
        disjoint_seeds: ``(class_a, class_b)`` pairs asserted
            ``owl:disjointWith`` for every cluster.
        nli_threshold: contradiction probability that makes a finding.
        max_nli_pairs: a cluster with more shard pairs skips the NLI screen
            (and says so) rather than scoring an unbounded number of pairs.
        max_reasoner_calls: reasoner calls allowed per cluster; when an
            explanation runs out, the finding is reported as not minimal.
        max_conflicts: disjoint conflicting sets reported per cluster.
        max_unsatisfiable: unsatisfiable classes explained per cluster.
        include_dependency_edges: give the reasoner the shards' dependency
            edges as ``fi:`` assertions (they never make a cluster formal).
        text_of: the text of a shard for the NLI screen.
        jurisdiction_of: ``framework_id -> jurisdiction`` for proposals.
    """

    def __init__(
        self,
        *,
        reasoner: FormalReasoner | Literal["auto"] | None = "auto",
        nli: NliScorer | None = None,
        tbox: Iterable[Triple3] = (),
        disjoint_seeds: Iterable[tuple[str, str]] = (),
        nli_threshold: float = DEFAULT_NLI_THRESHOLD,
        max_nli_pairs: int = DEFAULT_MAX_NLI_PAIRS,
        max_reasoner_calls: int = DEFAULT_MAX_REASONER_CALLS,
        max_conflicts: int = DEFAULT_MAX_CONFLICTS,
        max_unsatisfiable: int = DEFAULT_MAX_UNSATISFIABLE,
        include_dependency_edges: bool = True,
        text_of: Callable[[ShardEnvelope], str] = shard_text,
        jurisdiction_of: JurisdictionOf | None = None,
    ) -> None:
        if not 0.0 < nli_threshold <= 1.0:
            raise ValueError(f"nli_threshold must be in (0, 1], got {nli_threshold}")
        if max_reasoner_calls < 1:
            raise ValueError("max_reasoner_calls must be >= 1")
        if reasoner == "auto":
            from folio_insights.validation.hermit import HermitClusterReasoner, hermit_available

            available, reason = hermit_available()
            self.reasoner: FormalReasoner | None = HermitClusterReasoner() if available else None
            self.reasoner_status = "available" if available else f"unavailable: {reason}"
        else:
            self.reasoner = reasoner
            self.reasoner_status = "available" if reasoner is not None else "disabled"
        self.nli = nli
        self.nli_status = "available" if nli is not None else "disabled"
        self.tbox: list[Triple3] = [tuple(t) for t in tbox]  # type: ignore[misc]
        self.seed_axioms: list[Triple3] = sorted(
            {(a, OWL_DISJOINT_WITH, b) for a, b in disjoint_seeds if a != b}
        )
        self.nli_threshold = nli_threshold
        self.max_nli_pairs = max_nli_pairs
        self.max_reasoner_calls = max_reasoner_calls
        self.max_conflicts = max_conflicts
        self.max_unsatisfiable = max_unsatisfiable
        self.include_dependency_edges = include_dependency_edges
        self.text_of = text_of
        self.jurisdiction_of = jurisdiction_of
        self._verdicts: dict[frozenset[Triple3], FormalVerdict] = {}
        self._pair_scores: dict[tuple[str, str], float] = {}
        self._by_members: dict[frozenset[str], ClusterConsistency] = {}
        self._calls_left = 0

    @property
    def reasoner_name(self) -> str:
        return getattr(self.reasoner, "name", "none") if self.reasoner is not None else "none"

    # ── public ────────────────────────────────────────────────────────────

    def check_cluster(
        self, cluster: ShardCluster, shards: Mapping[str, ShardEnvelope]
    ) -> ClusterConsistency:
        """Check one cluster. Clusters with the same members (on different
        axes) are checked once and share the result."""
        members = frozenset(m for m in cluster.members if m in shards)
        cached = self._by_members.get(members)
        if cached is not None:
            return cached
        ordered = [shards[m] for m in sorted(members)]
        result = ClusterConsistency(mode="unchecked")
        formal_ran = self._formal(ordered, result)
        textual_ran = self._textual(ordered, result)
        if formal_ran and textual_ran:
            result.mode = "formal+textual"
        elif formal_ran:
            result.mode = "formal"
        elif textual_ran:
            result.mode = "nli_fallback"
        result.findings.sort(key=lambda f: (f.kind, f.checker, f.shards, f.id))
        self._by_members[members] = result
        return result

    # ── formal (HermiT) ───────────────────────────────────────────────────

    def _formal(self, shards: list[ShardEnvelope], result: ClusterConsistency) -> bool:
        groups: dict[str, tuple[Triple3, ...]] = {}
        for shard in shards:
            axioms = shard_axioms(shard)
            if axioms:
                deps = dependency_axioms(shard) if self.include_dependency_edges else ()
                groups[shard.shard_iri] = tuple(sorted(set(axioms) | set(deps)))
        result.formal_axiom_count = sum(len(shard_axioms(s)) for s in shards)
        if not groups:
            result.notes.append("no formal axioms in this cluster; NLI fallback")
            return False
        if self.reasoner is None:
            result.notes.append(f"formal reasoner {self.reasoner_status}; NLI fallback")
            return False
        by_iri = {s.shard_iri: s for s in shards}
        all_axioms = [t for g in groups.values() for t in g]
        background = sorted(
            set(tbox_slice(self.tbox, terms_of(all_axioms) | terms_of(self.seed_axioms)))
            | set(self.seed_axioms)
        )
        self._calls_left = self.max_reasoner_calls
        result.checkers.append("hermit")
        try:
            base = self._check(background)
        except _BudgetExhausted:  # pragma: no cover - budget >= 1 always allows the base check
            result.notes.append("reasoner call budget exhausted")
            return True
        if not base.consistent:
            result.findings.append(Finding(
                id=finding_id("tbox_inconsistent", "hermit", [], background),
                kind="tbox_inconsistent",
                checker="hermit",
                summary="The TBox slice and disjointness seeds are inconsistent on their own; "
                        "no shard-level explanation is possible until the TBox is fixed.",
                detail={"reasoner": self.reasoner_name, "background_axioms": [list(t) for t in background]},
            ))
            return True
        try:
            full = self._check(background + all_axioms)
            if not full.consistent:
                self._explain_inconsistency(groups, background, by_iri, result)
            else:
                self._explain_unsatisfiable(groups, background, base, full, by_iri, result)
        except _BudgetExhausted:
            self._note_budget(result)
        return True

    def _note_budget(self, result: ClusterConsistency) -> None:
        note = f"reasoner call budget ({self.max_reasoner_calls}) exhausted; explanations partial"
        if note not in result.notes:
            result.notes.append(note)

    def _check(self, triples: Sequence[Triple3]) -> FormalVerdict:
        key = frozenset(triples)
        cached = self._verdicts.get(key)
        if cached is not None:
            return cached
        if self._calls_left <= 0:
            raise _BudgetExhausted
        self._calls_left -= 1
        assert self.reasoner is not None
        verdict = self.reasoner.check(sorted(key))
        self._verdicts[key] = verdict
        return verdict

    def _minimize(self, items: list[T], still_bad: Callable[[list[T]], bool]) -> tuple[list[T], bool]:
        """Deletion-based minimization: ``(core, minimal)``. When the call
        budget runs out the current (still bad, maybe not minimal) core is
        returned with ``minimal=False``."""
        core = list(items)
        i = 0
        try:
            while i < len(core):
                trial = core[:i] + core[i + 1:]
                if still_bad(trial):
                    core = trial
                else:
                    i += 1
        except _BudgetExhausted:
            return core, False
        return core, True

    def _axioms(self, groups: Mapping[str, tuple[Triple3, ...]], keys: Iterable[str]) -> list[Triple3]:
        return [t for k in keys for t in groups[k]]

    def _explain_inconsistency(
        self,
        groups: Mapping[str, tuple[Triple3, ...]],
        background: list[Triple3],
        by_iri: Mapping[str, ShardEnvelope],
        result: ClusterConsistency,
    ) -> None:
        remaining = sorted(groups)
        for _ in range(self.max_conflicts):
            core, minimal = self._minimize(
                remaining,
                lambda keys: not self._check(background + self._axioms(groups, keys)).consistent,
            )
            used_background = background
            if minimal and len(background) <= DEFAULT_MAX_BACKGROUND_MINIMIZATION:
                fixed = self._axioms(groups, core)
                used_background, minimal = self._minimize(
                    background, lambda bg: not self._check(bg + fixed).consistent
                )
            self._add_conflict(core, used_background, minimal, groups, by_iri, result)
            remaining = [k for k in remaining if k not in core]
            if not minimal or not remaining:
                break
            if self._check(background + self._axioms(groups, remaining)).consistent:
                break

    def _add_conflict(
        self,
        core: list[str],
        background: list[Triple3],
        minimal: bool,
        groups: Mapping[str, tuple[Triple3, ...]],
        by_iri: Mapping[str, ShardEnvelope],
        result: ClusterConsistency,
    ) -> None:
        conflicting = [by_iri[k] for k in core]
        if not minimal:
            self._note_budget(result)
        what = (
            "is inconsistent with the TBox slice" if len(core) == 1
            else f"cannot all hold together ({len(core)} shards)"
        )
        result.findings.append(Finding(
            id=finding_id("contradiction", "hermit", core),
            kind="contradiction",
            checker="hermit",
            shards=list(core),
            summary=f"Formal contradiction: {', '.join(core)} {what}.",
            detail={
                "reasoner": self.reasoner_name,
                "minimal": minimal,
                "shard_axioms": {k: [list(t) for t in groups[k]] for k in core},
                "background_axioms": [list(t) for t in background],
                "source_uris": {k: by_iri[k].source_uri for k in core},
            },
            proposals=propose_for_conflict_set(conflicting, jurisdiction_of=self.jurisdiction_of),
        ))

    def _explain_unsatisfiable(
        self,
        groups: Mapping[str, tuple[Triple3, ...]],
        background: list[Triple3],
        base: FormalVerdict,
        full: FormalVerdict,
        by_iri: Mapping[str, ShardEnvelope],
        result: ClusterConsistency,
    ) -> None:
        new = sorted(set(full.unsatisfiable) - set(base.unsatisfiable))
        for cls in new[: self.max_unsatisfiable]:
            core, minimal = self._minimize(
                sorted(groups),
                lambda keys, cls=cls: cls in self._check(
                    background + self._axioms(groups, keys)
                ).unsatisfiable,
            )
            if not minimal:
                self._note_budget(result)
            result.findings.append(Finding(
                id=finding_id("unsatisfiable_class", "hermit", core, cls),
                kind="unsatisfiable_class",
                checker="hermit",
                shards=core,
                summary=f"Class {cls} is unsatisfiable given {', '.join(core)}.",
                detail={
                    "reasoner": self.reasoner_name,
                    "class": cls,
                    "minimal": minimal,
                    "shard_axioms": {k: [list(t) for t in groups[k]] for k in core},
                    "background_axioms": [list(t) for t in background],
                },
                proposals=propose_for_conflict_set(
                    [by_iri[k] for k in core], jurisdiction_of=self.jurisdiction_of
                ),
            ))
        if len(new) > self.max_unsatisfiable:
            result.notes.append(
                f"{len(new) - self.max_unsatisfiable} further unsatisfiable classes not explained"
            )

    # ── textual (NLI) ─────────────────────────────────────────────────────

    def _textual(self, shards: list[ShardEnvelope], result: ClusterConsistency) -> bool:
        if self.nli is None:
            result.notes.append(f"NLI screen {self.nli_status}")
            return False
        texts = {s.shard_iri: self.text_of(s) for s in shards}
        pairs = [
            (a, b)
            for i, a in enumerate(shards)
            for b in shards[i + 1:]
            if texts[a.shard_iri] and texts[b.shard_iri] and not _supersession_pair(a, b)
        ]
        if len(pairs) > self.max_nli_pairs:
            result.notes.append(
                f"NLI screen skipped: {len(pairs)} pairs exceed the cap of {self.max_nli_pairs}"
            )
            return False
        todo = [(a.shard_iri, b.shard_iri) for a, b in pairs
                if (a.shard_iri, b.shard_iri) not in self._pair_scores]
        if todo:
            batch = [(texts[x], texts[y]) for x, y in todo] + [(texts[y], texts[x]) for x, y in todo]
            try:
                scores = self.nli.contradiction_probabilities(batch)
            except Exception as exc:  # model load / inference failure: say so, never pass
                self.nli_status = f"failed: {type(exc).__name__}: {exc}"
                self.nli = None
                result.notes.append(f"NLI screen {self.nli_status}")
                return False
            if len(scores) != len(batch):
                raise ValueError(
                    f"NLI scorer returned {len(scores)} scores for {len(batch)} pairs"
                )
            n = len(todo)
            for k, key in enumerate(todo):
                self._pair_scores[key] = max(float(scores[k]), float(scores[k + n]))
        result.checkers.append("nli")
        model = getattr(self.nli, "name", type(self.nli).__name__)
        for a, b in pairs:
            score = self._pair_scores[(a.shard_iri, b.shard_iri)]
            if score < self.nli_threshold:
                continue
            ids = [a.shard_iri, b.shard_iri]
            result.findings.append(Finding(
                id=finding_id("contradiction", "nli", ids),
                kind="contradiction",
                checker="nli",
                shards=ids,
                summary=(
                    f"Textual contradiction (NLI {score:.2f} >= {self.nli_threshold:.2f}) "
                    f"between {a.shard_iri} and {b.shard_iri}."
                ),
                detail={
                    "nli_model": model,
                    "score": round(score, 6),
                    "threshold": self.nli_threshold,
                    "texts": {a.shard_iri: _excerpt(texts[a.shard_iri]),
                              b.shard_iri: _excerpt(texts[b.shard_iri])},
                    "source_uris": {a.shard_iri: a.source_uri, b.shard_iri: b.source_uri},
                    "frameworks": {a.shard_iri: a.framework_id, b.shard_iri: b.framework_id},
                },
                proposals=propose_for_conflict_set([a, b], jurisdiction_of=self.jurisdiction_of),
            ))
        return True

    def status(self) -> dict[str, Any]:
        return {"reasoner": self.reasoner_status, "nli": self.nli_status}


__all__ = [
    "ClusterConsistency",
    "ConsistencyChecker",
    "DEFAULT_NLI_THRESHOLD",
    "shard_text",
]
