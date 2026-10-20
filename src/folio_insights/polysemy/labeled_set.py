"""The polysemy labeled set and its FP-gate evaluation (Phase 9 U6, R9, KTD9).

A labeled set is a JSON document of synthetic cases. Each case is one term in
two or more registered frameworks: the frameworks' axiom paraphrases, the TBox
disjointness the case asserts between their term-scoped classes, a gold label
(``polysemy`` | ``homonymy`` | ``univocal``) and the first-pass disposition
(``labeler: "agent"``) that a reviewer would record against a detector flag:
``accept`` for a polysemous term, ``reject`` with a rationale otherwise.

``evaluate_labeled_set`` runs the real detector on every case (real prototype
centroids, the real Rule 1 reasoner over the case's seeds) and turns each case
into a ``DispositionRecord`` that snapshots the detector's verdict; the FP gate
(``fp_audit.fp_gate``) reads those records. Rule 4 (known homonyms) needs an
LLM; tests and the gate pass ``AlwaysPolysemyLLM``, a pessimistic fake that
always answers ``polysemy``, so the measured bound holds whatever a live model
would say there, and no provider is ever called.

Certification: the document may carry a ``certification`` block written by a
human (Open Question 1). It counts only when it names the digest of the cases
(``cases_sha256``); agents never write one, and the shipped set has none, so
its gate reports ``provisional`` at best.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from folio_insights.models.framework import FrameworkRegistry, check_framework_id
from folio_insights.polysemy.dispositions import DispositionRecord, ProposedFork
from folio_insights.polysemy.fixture_loader import ShardFixture
from folio_insights.polysemy.fp_audit import (
    AGENT_LABELER_ID,
    Certification,
    FpGateReport,
    fp_gate,
)

if TYPE_CHECKING:
    from folio_insights.polysemy.detector import LLMVerdict, RuleVerdict

LABELED_SET_FORMAT = "folio-insights/polysemy-labeled-set/v1"
# Fixed so that evaluation is reproducible byte for byte.
EVALUATED_AT = "2026-10-20T00:00:00+00:00"

GoldLabel = Literal["polysemy", "homonymy", "univocal"]


class CaseDisposition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    labeler: Literal["agent", "human"]
    decision: Literal["accept", "reject"]
    rationale: str = Field(min_length=1)

    @field_validator("rationale")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("a disposition rationale is never blank")
        return value


class LabeledCase(BaseModel):
    """One term across frameworks, with its gold label and first-pass disposition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    term: str = Field(min_length=1)
    gold: GoldLabel
    # framework_id -> axiom paraphrases (synthetic; never source text)
    senses: dict[str, tuple[str, ...]]
    # framework pairs whose term-scoped classes the case's TBox states disjoint
    tbox_disjoint: tuple[tuple[str, str], ...] = ()
    disposition: CaseDisposition
    note: str = ""

    @field_validator("senses")
    @classmethod
    def _senses(cls, value: dict[str, tuple[str, ...]]) -> dict[str, tuple[str, ...]]:
        if len(value) < 2:
            raise ValueError("a case spans at least two frameworks")
        for framework_id, axioms in value.items():
            check_framework_id(framework_id)
            if not axioms or any(not a.strip() for a in axioms):
                raise ValueError(f"framework {framework_id!r} needs non-blank axioms")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> LabeledCase:
        for pair in self.tbox_disjoint:
            if len(set(pair)) != 2 or not set(pair) <= set(self.senses):
                raise ValueError(f"{self.id}: disjoint pair {pair} must name two of its frameworks")
        expected = "accept" if self.gold == "polysemy" else "reject"
        if self.disposition.decision != expected:
            raise ValueError(
                f"{self.id}: gold {self.gold!r} is recorded as {expected!r}, "
                f"not {self.disposition.decision!r}"
            )
        return self


class LabeledSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    format: Literal["folio-insights/polysemy-labeled-set/v1"]
    description: str = ""
    labeling: dict[str, Any] = Field(default_factory=dict)
    certification: Certification | None = None
    cases: tuple[LabeledCase, ...]

    @model_validator(mode="after")
    def _unique_ids(self) -> LabeledSet:
        ids = [c.id for c in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("labeled-set case IDs must be unique")
        if self.certification is not None:
            unknown = set(self.certification.sample_reviewed) - set(ids)
            if unknown:
                raise ValueError(f"certification sample names unknown cases {sorted(unknown)}")
        return self

    def check_registered(self, registry: FrameworkRegistry) -> None:
        """Every framework the cases name is registered (``UnregisteredFramework``)."""
        for case in self.cases:
            for framework_id in case.senses:
                registry.resolve(framework_id)

    def cases_sha256(self) -> str:
        """Digest of the cases (what a certification binds to)."""
        payload = [c.model_dump(mode="json") for c in self.cases]
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_labeled_set(path: Path) -> LabeledSet:
    return LabeledSet.model_validate_json(path.read_text(encoding="utf-8"))


class AlwaysPolysemyLLM:
    """A pessimistic stand-in for the Rule 4 LLM: always ``polysemy``.

    With it every Rule 4 case the rules forward counts against the detector if
    its gold label is not polysemy, so the gate bound does not depend on how
    good a live model is. It never touches a provider.
    """

    provider_label = "fake:always-polysemy"

    def __init__(self) -> None:
        self.calls = 0

    def structured_model_sync(self, prompt: str, schema: Any = None, **_: Any) -> Any:
        from folio_insights.llm.schemas import PolysemyVerdict

        self.calls += 1
        return PolysemyVerdict(
            decision="polysemy",
            polysemy_vs_homonymy_reasoning="pessimistic fake: always polysemy",
            rationale="labeled-set gate stand-in; no provider called",
        )


@dataclass(frozen=True)
class CaseOutcome:
    case_id: str
    term: str
    gold: GoldLabel
    detector_decision: str
    matched_rules: tuple[str, ...]
    evidence_score: float
    false_positive: bool


@dataclass(frozen=True)
class LabeledSetEvaluation:
    report: FpGateReport
    outcomes: tuple[CaseOutcome, ...]
    records: tuple[DispositionRecord, ...]
    cases_sha256: str
    llm_label: str

    @property
    def false_negatives(self) -> int:
        return sum(1 for o in self.outcomes if o.gold == "polysemy" and o.detector_decision != "polysemy")


def _case_shards(case: LabeledCase) -> list[ShardFixture]:
    return [
        ShardFixture(
            iri=f"urn:folio:labeled/{case.id}/{framework_id}/{n}",
            framework=framework_id,
            source_doc=f"synthetic:{case.id}",
            extracted_text=axiom,
            axiom_summary=axiom,
            term=case.term,
        )
        for framework_id in sorted(case.senses)
        for n, axiom in enumerate(case.senses[framework_id])
    ]


def detect_case(case: LabeledCase, *, llm: Any) -> RuleVerdict | LLMVerdict:
    """The detector's verdict on one case (its own TBox; no shared state)."""
    from folio_insights.polysemy.detector import detect_polysemy
    from folio_insights.polysemy.prototype_cluster import build_prototype_cluster
    from folio_insights.polysemy.tbox import disjointness_seed_ttl, load_tbox_seeds
    from folio_insights.store.pyoxigraph_store import PyoxigraphStore

    store = PyoxigraphStore(path=None)
    if case.tbox_disjoint:
        load_tbox_seeds(store, disjointness_seed_ttl(case.term, case.tbox_disjoint))
    cluster = build_prototype_cluster(_case_shards(case))
    return detect_polysemy(cluster, store, llm=llm)


def evaluate_labeled_set(
    labeled: LabeledSet,
    *,
    llm: Any | None = None,
    registry: FrameworkRegistry | None = None,
) -> LabeledSetEvaluation:
    """Run the detector over every case and compute the FP gate."""
    from folio_insights.polysemy.fp_audit import is_false_positive
    from folio_insights.polysemy.prototype_cluster import _mint_cluster_id

    labeled.check_registered(registry or FrameworkRegistry.with_defaults())
    llm = llm if llm is not None else AlwaysPolysemyLLM()
    outcomes: list[CaseOutcome] = []
    records: list[DispositionRecord] = []
    for case in labeled.cases:
        verdict = detect_case(case, llm=llm)
        cluster_id = _mint_cluster_id(f"{case.id}:{case.term}", list(case.senses))
        record = DispositionRecord(
            cluster_id=cluster_id,
            term=case.term,
            proposed_fork=ProposedFork(
                cluster_id=cluster_id, term=case.term, frameworks=sorted(case.senses)
            ),
            decision=case.disposition.decision,
            rationale=case.disposition.rationale,
            reviewer_did=AGENT_LABELER_ID,
            reviewed_at_iso=EVALUATED_AT,
            detector_verdict=verdict.model_dump(),
            audit_label=case.id,
            labeler=case.disposition.labeler,
        )
        records.append(record)
        outcomes.append(CaseOutcome(
            case_id=case.id,
            term=case.term,
            gold=case.gold,
            detector_decision=verdict.decision,
            matched_rules=tuple(verdict.matched_rules),
            evidence_score=verdict.evidence_score,
            false_positive=is_false_positive(record),
        ))
    digest = labeled.cases_sha256()
    report = fp_gate(records, labeled=labeled)
    return LabeledSetEvaluation(
        report=report,
        outcomes=tuple(outcomes),
        records=tuple(records),
        cases_sha256=digest,
        llm_label=getattr(llm, "provider_label", type(llm).__name__),
    )


__all__ = [
    "AGENT_LABELER_ID",
    "AlwaysPolysemyLLM",
    "CaseDisposition",
    "CaseOutcome",
    "GoldLabel",
    "LABELED_SET_FORMAT",
    "LabeledCase",
    "LabeledSet",
    "LabeledSetEvaluation",
    "detect_case",
    "evaluate_labeled_set",
    "load_labeled_set",
]
