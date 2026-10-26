"""Source, gold and evaluation input contracts (measured-propositions KTD1)."""
from __future__ import annotations

import hashlib
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Nonempty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Commit = Annotated[str, StringConstraints(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")]
Genre = Literal["opinions", "statutes-regulations", "briefs", "know-how"]
LinkType = Literal["exception-to", "penalty-for", "condition-of", "cites", "contradicts"]


class MeasurementModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceSnapshot(MeasurementModel):
    source_id: Nonempty
    group_id: Nonempty
    title: Nonempty
    genre: Genre
    subgenre: Nonempty
    jurisdiction: Nonempty
    synthetic: bool
    partition: Literal["tuning", "evaluation-candidate", "held-out", "retired"]
    example_id: int | None = Field(default=None, ge=1, le=8)
    text: str = Field(min_length=1)
    sha256: Sha256

    @model_validator(mode="after")
    def check_digest(self) -> SourceSnapshot:
        if hashlib.sha256(self.text.encode("utf-8")).hexdigest() != self.sha256:
            raise ValueError("source snapshot digest does not match text")
        return self


class SupportingSpan(MeasurementModel):
    """Half-open code-point offsets; supporting text is derived, never serialized."""

    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def check_order(self) -> SupportingSpan:
        if self.end <= self.start:
            raise ValueError("span end must follow start")
        return self

    def source_slice(self, source_text: str) -> str:
        """Return the exact support, rejecting offsets Python would silently clip."""
        if not 0 <= self.start < self.end <= len(source_text):
            raise ValueError("span outside source snapshot: not an exact source slice")
        return source_text[self.start:self.end]


class TagSelection(MeasurementModel):
    """Author/model labels only; deterministic ontology code supplies IRIs."""

    label: Nonempty
    branch: Nonempty


class PropositionLink(MeasurementModel):
    relation: LinkType
    target_id: Nonempty


class GoldProposition(MeasurementModel):
    item_id: Nonempty
    kind: Literal["rule", "element", "exception", "penalty", "fact", "definition",
                  "advice", "citation", "outcome"]
    text: Nonempty
    span: SupportingSpan
    tags: tuple[TagSelection, ...] = Field(min_length=1)
    links: tuple[PropositionLink, ...] = ()


class EvaluationItem(MeasurementModel):
    """A source-scoped judge item; gold/omission coverage is independent of predictions."""

    item_id: Nonempty
    source_id: Nonempty
    kind: Literal["prediction", "gold", "omission", "tag"]
    proposition_id: Nonempty
    tag: TagSelection | None = None


class GoldDocument(MeasurementModel):
    source: SourceSnapshot
    propositions: tuple[GoldProposition, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def check_grounding_and_links(self) -> GoldDocument:
        ids = [p.item_id for p in self.propositions]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate proposition item ID")
        for prop in self.propositions:
            try:
                prop.span.source_slice(self.source.text)
            except ValueError as exc:
                raise ValueError(f"{prop.item_id}: {exc}") from exc
            for link in prop.links:
                if link.target_id == prop.item_id:
                    raise ValueError(f"{prop.item_id}: self link is invalid")
                if link.target_id not in ids:
                    raise ValueError(f"{prop.item_id}: missing link target {link.target_id}")
        return self


class GoldSuite(MeasurementModel):
    format: Literal[1]
    suite_id: Nonempty
    gold_revision: Nonempty
    ontology_sha256: Sha256
    ontology_slice_sha256: Sha256
    adjudication_status: Literal["draft", "judge-cross-checked", "human-verified"]
    documents: tuple[GoldDocument, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def check_unique_sources(self) -> GoldSuite:
        ids = [d.source.source_id for d in self.documents]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate source ID")
        examples = [d.source.example_id for d in self.documents if d.source.example_id is not None]
        if len(examples) != len(set(examples)):
            raise ValueError("duplicate README example ID")
        return self


class JudgeIdentity(MeasurementModel):
    cli_version: Nonempty
    model: Nonempty


class EvaluationInputs(MeasurementModel):
    """Pinned independently of outputs; persisted by the later run coordinator."""

    source_snapshots: dict[Nonempty, Sha256] = Field(min_length=1)
    gold_revision: Nonempty
    gold_sha256: Sha256
    split_manifest_sha256: Sha256
    ontology_sha256: Sha256
    scorer_version: Nonempty
    matcher_version: Nonempty
    baseline_commit: Commit
    candidate_commit: Commit
    baseline_config_sha256: Sha256
    candidate_config_sha256: Sha256
    extraction_prompt_sha256: dict[Nonempty, Sha256] = Field(min_length=1)
    judge_prompt_sha256: dict[Nonempty, Sha256] = Field(min_length=1)
    judge_identities: dict[Nonempty, JudgeIdentity] = Field(min_length=1)
    sampling_seed: int = Field(ge=0)
