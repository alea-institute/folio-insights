"""Framework detector: deterministic first, generative last (Phase 9 U2, KTD12).

Sources, in order; the FIRST confident one wins:

1. **metadata** — an explicit framework ID in the source metadata (v1-style
   IDs are migrated: year suffix stripped, with a warning).
2. **corpus_default** — the corpus manifest's default framework.
3. **citation** — known citation patterns in the source's citation strings;
   a single framework must dominate.
4. **llm** — the LLM chooses AMONG REGISTERED frameworks only. It never mints
   an ID: a reply naming an unregistered (or malformed) ID is rejected and
   recorded as evidence, mirroring the tagger's "the LLM never mints IRIs".

Every stage records evidence. When no stage is confident the detection has
no framework (``framework_id is None``) and fails the confidence gate — it
never falls back to a default. Valid-time windows come from supplied
metadata only (``frameworks.valid_time``). Identical inputs give identical
outputs (the deterministic stages are pure; the LLM runs at temperature 0
behind the Phase 10 port, or a fake in tests).
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from folio_insights.models.framework import (
    FrameworkRegistry,
    MalformedFrameworkId,
    check_framework_id,
    migrate_v1_framework_id,
)
from folio_insights.frameworks.valid_time import (
    SourceTimeMetadata,
    ValidTimeWindow,
    infer_valid_time,
)

DetectionSource = Literal["metadata", "corpus_default", "citation", "llm"]
DEFAULT_THRESHOLD = 0.8
METADATA_CONFIDENCE = 1.0
CORPUS_DEFAULT_CONFIDENCE = 0.9
CITATION_CEILING = 0.95

# Citation forms -> framework ID. Only patterns whose framework is registered
# in the corpus registry take part.
CITATION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bFed\.\s*R\.\s*Evid\.|\bFRE\s+\d", re.I), "us.federal.fre"),
    (re.compile(r"\bFed\.\s*R\.\s*Civ\.\s*P\.|\bFRCP\s+\d", re.I), "us.federal.frcp"),
    (re.compile(r"\bU\.\s*C\.\s*C\.|\bUCC\s*§", re.I), "us.ucc"),
    (re.compile(r"\bRestatement\s*\(Second\)\s*of\s*Contracts", re.I), "us.restatement_2d.contracts"),
    (re.compile(r"\bLa\.\s*Civ\.\s*Code|\bLouisiana\s+Civil\s+Code", re.I), "us.louisiana.civil_code"),
)


class SourceMetadata(BaseModel):
    """What the caller knows about a source; nothing is parsed from its text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    framework_id: str | None = None
    title: str | None = None
    jurisdiction: str | None = None
    citations: tuple[str, ...] = ()
    time: SourceTimeMetadata | None = None


class FrameworkDetection(BaseModel):
    """The detector's answer and everything it rests on."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    framework_id: str | None
    source: DetectionSource | None
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: tuple[str, ...] = ()
    valid_time: ValidTimeWindow | None = None
    migration_warnings: tuple[str, ...] = ()

    def is_confident(self, threshold: float = DEFAULT_THRESHOLD) -> bool:
        return self.framework_id is not None and self.confidence >= threshold


class FrameworkLLMChoice(BaseModel):
    """What the LLM stage returns: one registered ID (or none) and a confidence."""

    framework_id: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = ""


@runtime_checkable
class FrameworkLLM(Protocol):
    """Chooses among ``candidates`` (registered IDs) for ``metadata``."""

    def choose(
        self, metadata: SourceMetadata, candidates: list[tuple[str, str]]
    ) -> FrameworkLLMChoice: ...


class PortFrameworkLLM:
    """The LLM stage through the Phase 10 port (task ``framework_detector``)."""

    def __init__(self, task_llm: object | None = None) -> None:
        if task_llm is None:
            from folio_insights.services.bridge.llm_bridge import LLMBridge

            task_llm = LLMBridge().get_llm_for_task("framework_detector")
        self._llm = task_llm

    def choose(
        self, metadata: SourceMetadata, candidates: list[tuple[str, str]]
    ) -> FrameworkLLMChoice:
        from folio_insights.llm.schemas import FrameworkChoice
        from folio_insights.llm.templates import FRAMEWORK_DETECT

        prompt = FRAMEWORK_DETECT.render(
            candidates="\n".join(f"- {fid}: {label}" for fid, label in candidates),
            title=metadata.title or "(none)",
            jurisdiction=metadata.jurisdiction or "(none)",
            citations="; ".join(metadata.citations) or "(none)",
        )
        reply = self._llm.structured_model_sync(  # type: ignore[attr-defined]
            prompt, FrameworkChoice, template=FRAMEWORK_DETECT
        )
        return FrameworkLLMChoice(
            framework_id=reply.framework_id, confidence=reply.confidence, rationale=reply.rationale
        )


class FrameworkDetector:
    """Detect a source's framework against one corpus registry."""

    def __init__(
        self,
        registry: FrameworkRegistry,
        *,
        corpus_default: str | None = None,
        llm: FrameworkLLM | None = None,
        threshold: float = DEFAULT_THRESHOLD,
    ) -> None:
        if corpus_default is not None:
            registry.resolve(corpus_default)  # must be registered
        self.registry = registry
        self.corpus_default = corpus_default
        self.llm = llm
        self.threshold = threshold

    def detect(self, metadata: SourceMetadata) -> FrameworkDetection:
        evidence: list[str] = []
        warnings: tuple[str, ...] = ()
        best = 0.0
        window = infer_valid_time(metadata.time) if metadata.time is not None else None

        def done(fid: str, source: DetectionSource, confidence: float) -> FrameworkDetection:
            return FrameworkDetection(
                framework_id=fid, source=source, confidence=confidence,
                evidence=tuple(evidence), valid_time=window, migration_warnings=warnings,
            )

        # 1. explicit metadata
        if metadata.framework_id is not None:
            try:
                migrated = migrate_v1_framework_id(metadata.framework_id)
                warnings = migrated.warnings
                fid = migrated.framework_id
                if fid in self.registry:
                    evidence.append(f"metadata: framework_id={fid}")
                    return done(fid, "metadata", METADATA_CONFIDENCE)
                evidence.append(f"metadata: framework_id={fid} is not registered; ignored")
            except MalformedFrameworkId:
                evidence.append("metadata: framework_id is malformed; ignored")

        # 2. corpus manifest default
        if self.corpus_default is not None:
            evidence.append(f"corpus_default: {self.corpus_default}")
            return done(self.corpus_default, "corpus_default", CORPUS_DEFAULT_CONFIDENCE)

        # 3. citation patterns
        votes: Counter[str] = Counter()
        for citation in metadata.citations:
            for pattern, fid in CITATION_PATTERNS:
                if fid in self.registry and pattern.search(citation):
                    votes[fid] += 1
        if votes:
            ranked = sorted(votes.items(), key=lambda kv: (-kv[1], kv[0]))
            top, count = ranked[0]
            share = count / sum(votes.values())
            confidence = round(CITATION_CEILING * share, 6)
            tie = len(ranked) > 1 and ranked[1][1] == count
            evidence.append(
                "citation: " + ", ".join(f"{fid}={n}" for fid, n in ranked)
                + (" (tie)" if tie else "")
            )
            if not tie and confidence >= self.threshold:
                return done(top, "citation", confidence)
            best = max(best, 0.0 if tie else confidence)

        # 4. LLM, constrained to registered frameworks
        if self.llm is not None:
            candidates = [(fw.id, fw.label) for fw in self.registry.frameworks()]
            choice = self.llm.choose(metadata, candidates)
            proposed = choice.framework_id
            if proposed is None:
                evidence.append("llm: no framework chosen")
            else:
                try:
                    check_framework_id(proposed)
                    registered = proposed in self.registry
                except MalformedFrameworkId:
                    registered = False
                if not registered:
                    evidence.append(
                        f"llm: proposed {proposed!r}, which is not a registered framework; "
                        "rejected (the LLM never mints framework IDs)"
                    )
                else:
                    evidence.append(f"llm: {proposed} ({choice.confidence:.2f})")
                    if choice.confidence >= self.threshold:
                        return done(proposed, "llm", choice.confidence)
                    best = max(best, choice.confidence)

        evidence.append(f"no confident framework (threshold {self.threshold})")
        return FrameworkDetection(
            framework_id=None, source=None, confidence=best, evidence=tuple(evidence),
            valid_time=window, migration_warnings=warnings,
        )


__all__ = [
    "CITATION_PATTERNS",
    "DEFAULT_THRESHOLD",
    "DetectionSource",
    "FrameworkDetection",
    "FrameworkDetector",
    "FrameworkLLM",
    "FrameworkLLMChoice",
    "PortFrameworkLLM",
    "SourceMetadata",
]
