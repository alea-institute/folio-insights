"""Rule-first BFO typing of a shard's subject (Phase 9 U7, KTD11; PRD §8 P7).

Order: the rule classifier (the subject's VERIFIED FOLIO tags through the
branch table), then the LLM fallback (through the Phase 10 port; it can only
answer one of the four envelope categories — the schema forbids anything
else), then the mode's last resort:

* ``permissive`` — the documented default for the shard's speech act,
  recorded as ``source="default"`` (``bfo_assignment == "default"``);
* ``strict`` — ``BfoUnclassifiable``: the shard is refused.

Every assignment carries its evidence. Coverage counts only rule and LLM
assignments, never defaults. Phase 10's minter calls ``BfoClassifier.classify``
to fill the envelope's ``bfo_category``.
"""
from __future__ import annotations

from typing import Literal, Protocol, get_args, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from folio_insights.bfo.spine import (
    CATEGORY_SPINE_CLASS,
    DEFAULT_CATEGORY_BY_SPEECH_ACT,
    BfoCategory,
    branch_for,
)

AssignmentSource = Literal["rule", "llm", "default"]
BfoMode = Literal["permissive", "strict"]
LLM_THRESHOLD = 0.7
BFO_CATEGORIES: tuple[str, ...] = get_args(BfoCategory)


class BfoUnclassifiable(ValueError):
    """Strict mode: no rule or LLM typing for the subject."""


class FolioTag(BaseModel):
    """A FOLIO tag on the shard's subject; only verified tags type it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    iri: str
    branch: str  # the top-level branch, by IRI or label
    verified: bool = True
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class BfoInput(BaseModel):
    """What the classifier sees for one shard."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    speech_act: str
    folio_tags: tuple[FolioTag, ...] = ()
    subject: str = ""
    source_uri: str | None = None


class BfoAssignment(BaseModel):
    """A BFO category with its provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    category: BfoCategory
    spine_class: str
    source: AssignmentSource
    branch: str | None = None
    evidence: tuple[str, ...] = ()

    @property
    def bfo_assignment(self) -> AssignmentSource:
        return self.source

    @property
    def is_default(self) -> bool:
        return self.source == "default"


class BfoLLMChoice(BaseModel):
    category: BfoCategory | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = ""


@runtime_checkable
class BfoLLM(Protocol):
    def classify(self, item: BfoInput) -> BfoLLMChoice: ...


class PortBfoLLM:
    """The LLM fallback through the Phase 10 port (task ``bfo_classifier``)."""

    def __init__(self, task_llm: object | None = None) -> None:
        if task_llm is None:
            from folio_insights.services.bridge.llm_bridge import LLMBridge

            task_llm = LLMBridge().get_llm_for_task("bfo_classifier")
        self._llm = task_llm

    def classify(self, item: BfoInput) -> BfoLLMChoice:
        from folio_insights.llm.schemas import BfoCategoryChoice
        from folio_insights.llm.templates import BFO_CLASSIFY

        prompt = BFO_CLASSIFY.render(
            subject=item.subject or "(none)",
            speech_act=item.speech_act,
            tags="; ".join(f"{t.iri} ({t.branch})" for t in item.folio_tags) or "(none)",
        )
        reply = self._llm.structured_model_sync(  # type: ignore[attr-defined]
            prompt, BfoCategoryChoice, template=BFO_CLASSIFY
        )
        return BfoLLMChoice(
            category=reply.category, confidence=reply.confidence, rationale=reply.rationale
        )


class BfoClassifier:
    """Rule -> LLM -> default (permissive) or refusal (strict)."""

    def __init__(
        self,
        *,
        mode: BfoMode = "permissive",
        llm: BfoLLM | None = None,
        llm_threshold: float = LLM_THRESHOLD,
    ) -> None:
        if mode not in ("permissive", "strict"):
            raise ValueError(f"unknown BFO mode {mode!r}")
        self.mode = mode
        self.llm = llm
        self.llm_threshold = llm_threshold

    def classify(self, item: BfoInput) -> BfoAssignment:
        evidence: list[str] = []

        # 1. rules: the highest-confidence verified tag on a known branch
        candidates = []
        for index, tag in enumerate(item.folio_tags):
            if not tag.verified:
                evidence.append(f"rule: {tag.iri} skipped (unverified)")
                continue
            mapping = branch_for(tag.branch)
            if mapping is None:
                evidence.append(f"rule: {tag.iri} has unknown branch {tag.branch!r}")
                continue
            candidates.append((-tag.confidence, index, tag, mapping))
        if candidates:
            _, _, tag, mapping = min(candidates, key=lambda c: (c[0], c[1]))
            categories = {m.category for *_, m in candidates}
            evidence.append(f"rule: {tag.iri} in branch {mapping.label!r} -> {mapping.category}")
            if len(categories) > 1:
                evidence.append(
                    "rule: verified tags span categories "
                    + ", ".join(sorted(categories))
                    + "; the highest-confidence tag decides"
                )
            return BfoAssignment(
                category=mapping.category,
                spine_class=mapping.spine_class,
                source="rule",
                branch=mapping.iri,
                evidence=tuple(evidence),
            )

        # 2. LLM fallback (one of the four categories, or none)
        if self.llm is not None:
            choice = self.llm.classify(item)
            if choice.category is not None and choice.confidence >= self.llm_threshold:
                evidence.append(f"llm: {choice.category} ({choice.confidence:.2f})")
                return BfoAssignment(
                    category=choice.category,
                    spine_class=CATEGORY_SPINE_CLASS[choice.category],
                    source="llm",
                    evidence=tuple(evidence),
                )
            evidence.append(
                "llm: no category" if choice.category is None
                else f"llm: {choice.category} below threshold ({choice.confidence:.2f})"
            )

        # 3. strict refuses; permissive records the documented default
        if self.mode == "strict":
            raise BfoUnclassifiable(
                "no verified FOLIO tag or confident LLM typing for the subject "
                f"(speech act {item.speech_act!r}); strict mode refuses it"
            )
        default = DEFAULT_CATEGORY_BY_SPEECH_ACT.get(item.speech_act, "continuant_dependent")
        evidence.append(f"default: speech act {item.speech_act!r} -> {default}")
        return BfoAssignment(
            category=default,
            spine_class=CATEGORY_SPINE_CLASS[default],
            source="default",
            evidence=tuple(evidence),
        )


__all__ = [
    "AssignmentSource",
    "BFO_CATEGORIES",
    "BfoAssignment",
    "BfoClassifier",
    "BfoInput",
    "BfoLLM",
    "BfoLLMChoice",
    "BfoMode",
    "BfoUnclassifiable",
    "FolioTag",
    "LLM_THRESHOLD",
    "PortBfoLLM",
]
