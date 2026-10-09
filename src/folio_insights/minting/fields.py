"""Field inference, framework and BFO for a mint-eligible unit (drain U8, R3, KTD3).

Three independent sources fill the envelope fields eligibility cannot:

* **Analysed fields** (``sense``, ``reference``, ``logical_form_imputed``, ``layer``,
  ``predication_mode``, ``fork``, ``speech_act``) come from ONE structured LLM call
  per unit through the Phase 10 port, with the registered template
  ``llm.templates.MINT_FIELDS`` (``mint.fields.v1``). The prompt carries the
  verified source slice and the unit text and tells the model to use the slice
  only. Every field returns a confidence; a field below its floor (default
  ``DEFAULT_FIELD_FLOOR`` = 0.6, configurable per field) refuses the unit with
  ``field_low_confidence:<field>`` instead of keeping a guess. With no LLM the
  unit is refused ``field_inference_unavailable``; no field is ever defaulted
  (KTD3 fails closed).
* **framework_id** comes from Phase 9's ``FrameworkDetector`` (explicit source
  metadata, the corpus default, citation patterns, then the LLM restricted to
  registered IDs). A detection below its threshold refuses the unit
  ``framework_unconfident``; v1-style framework IDs in the source metadata are
  migrated by the detector (``models.framework.migrate_v1_framework_id``) and
  their warnings are carried into the mint report.
* **bfo_category** comes from Phase 9's ``BfoClassifier`` in STRICT mode: the
  subject's verified FOLIO tags typed through their FOLIO ancestry, then the LLM
  fallback. No typing refuses the unit ``bfo_unclassifiable``; the documented
  speech-act default is never used for a minted shard.

The synchronous Phase 9 LLM adapters (``PortFrameworkLLM`` / ``PortBfoLLM``) run in
a worker thread (``asyncio.to_thread`` copies the run's LLM context into it).
"""
from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from folio_insights.llm.errors import LLMError, RunHalted
from folio_insights.llm.schemas import MintFieldsOutput
from folio_insights.llm.templates import MINT_FIELDS
from folio_insights.minting.eligibility import (
    BFO_UNCLASSIFIABLE,
    FIELD_INFERENCE_FAILED,
    FIELD_INFERENCE_UNAVAILABLE,
    FIELD_LOW_CONFIDENCE,
    FRAMEWORK_UNCONFIDENT,
    Eligible,
    Reason,
    Refused,
)

if TYPE_CHECKING:
    from folio_insights.bfo.classifier import BfoAssignment, BfoClassifier
    from folio_insights.bfo.spine import BranchResolver
    from folio_insights.frameworks.detector import FrameworkDetection, FrameworkDetector
    from folio_insights.llm.context import LLMRunContext
    from folio_insights.llm.port import LLMPort
    from folio_insights.models.knowledge_unit import KnowledgeUnit
    from folio_insights.rubric.oracle import IriOracle

#: The task name ``mint.fields.v1`` routes under (``LLM_MINT_FIELDS_PROVIDER/MODEL`` override).
MINT_FIELDS_TASK = MINT_FIELDS.task
DEFAULT_FIELD_FLOOR = 0.6
FIELD_NAMES: tuple[str, ...] = (
    "sense",
    "reference",
    "logical_form_imputed",
    "layer",
    "predication_mode",
    "fork",
    "speech_act",
)


@dataclass(frozen=True)
class InferredFields:
    """The seven field values, their confidences and the route that produced them."""

    values: Mapping[str, str]
    confidences: Mapping[str, float]
    provider: str
    model: str

    @property
    def min_confidence(self) -> float:
        return min(self.confidences.values())


@dataclass(frozen=True)
class FieldFloors:
    """Per-field confidence floors (``default`` for any field not named)."""

    default: float = DEFAULT_FIELD_FLOOR
    per_field: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        unknown = set(self.per_field) - set(FIELD_NAMES)
        if unknown:
            raise ValueError(f"unknown field(s) for a confidence floor: {sorted(unknown)}")
        for value in (self.default, *self.per_field.values()):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"a confidence floor must be within [0, 1]; got {value}")

    def floor(self, name: str) -> float:
        return self.per_field.get(name, self.default)


def field_messages(unit: KnowledgeUnit, eligible: Eligible) -> list[dict[str, str]]:
    """The chat messages of the unit's one field-inference call."""
    return MINT_FIELDS.messages(
        span=eligible.verified_span,
        unit_text=unit.text,
        unit_type=unit.unit_type.value,
        section=" > ".join(unit.source_section) or "(none)",
    )


async def infer_fields(
    unit: KnowledgeUnit,
    eligible: Eligible,
    *,
    port: LLMPort | None,
    context: LLMRunContext | None = None,
    floors: FieldFloors | None = None,
) -> InferredFields | Refused:
    """One structured call -> the seven fields, or a refusal (module docstring).

    ``RunHalted`` (missing credentials, a spent budget, a rejected key) propagates:
    the minter stops calling the model and refuses the remaining units
    ``field_inference_unavailable``.
    """
    if port is None:
        return Refused.single(FIELD_INFERENCE_UNAVAILABLE,
                              "no LLM is configured; analysed fields are never defaulted")
    floors = floors or FieldFloors()
    try:
        output, usage = await port.structured(
            MINT_FIELDS_TASK, MintFieldsOutput, field_messages(unit, eligible),
            template=MINT_FIELDS, temperature=0.0, context=context,
        )
    except RunHalted:
        raise
    except LLMError as exc:
        return Refused.single(FIELD_INFERENCE_FAILED,
                              f"the field-inference call failed ({type(exc).__name__})")
    values: dict[str, str] = {}
    confidences: dict[str, float] = {}
    reasons: list[Reason] = []
    for name in FIELD_NAMES:
        scored = getattr(output, name)
        value = str(scored.value).strip()
        confidence = float(scored.confidence)
        values[name], confidences[name] = value, confidence
        floor = floors.floor(name)
        if not value:
            reasons.append(Reason(f"{FIELD_LOW_CONFIDENCE}:{name}", f"{name} is empty"))
        elif confidence < floor:
            reasons.append(Reason(f"{FIELD_LOW_CONFIDENCE}:{name}",
                                  f"{name} confidence {confidence:.2f} is below its floor "
                                  f"{floor:.2f}"))
    if reasons:
        return Refused.of(reasons)
    return InferredFields(values, confidences, usage.provider, usage.model)


# ── framework ────────────────────────────────────────────────────────────


async def detect_framework(
    detector: FrameworkDetector, metadata: Any
) -> tuple[FrameworkDetection | None, Refused | None]:
    """``(detection, None)`` when confident, else ``(detection or None, refusal)``."""
    try:
        detection = await asyncio.to_thread(detector.detect, metadata)
    except RunHalted:
        raise
    except LLMError as exc:
        return None, Refused.single(FRAMEWORK_UNCONFIDENT,
                                    f"the framework detector's LLM stage failed "
                                    f"({type(exc).__name__}); no framework is defaulted")
    if not detection.is_confident(detector.threshold):
        evidence = "; ".join(detection.evidence[-2:]) or "no evidence"
        return detection, Refused.single(
            FRAMEWORK_UNCONFIDENT,
            f"no framework at confidence {detector.threshold:.2f} ({evidence})",
        )
    return detection, None


# ── BFO ──────────────────────────────────────────────────────────────────


class OracleBranchResolver:
    """A ``bfo.spine.BranchResolver`` over an ``IriOracle``'s branch answers.

    The oracle names each concept's top-level FOLIO branch(es) from the real
    ontology (or a frozen fixture); this resolver answers a concept's "parents"
    with those branch classes, which is all ``top_level_branches`` needs. The
    tag's own claimed ``branch`` is never consulted (Phase 9 review P2-9).
    """

    def __init__(self, oracle: IriOracle) -> None:
        self._oracle = oracle

    def parents(self, iri: str) -> Iterable[str]:
        from folio_insights.bfo.spine import BRANCH_BY_IRI, branch_for

        if iri in BRANCH_BY_IRI:
            return ()
        out: list[str] = []
        for label in self._oracle.branch_of(iri):
            mapping = branch_for(label)
            if mapping is not None and mapping.iri not in out:
                out.append(mapping.iri)
        return tuple(out)


def strict_classifier(
    *, resolver: BranchResolver | None, llm: Any | None = None
) -> BfoClassifier:
    from folio_insights.bfo.classifier import BfoClassifier

    return BfoClassifier(mode="strict", llm=llm, resolver=resolver)


async def classify_bfo(
    classifier: BfoClassifier,
    eligible: Eligible,
    speech_act: str,
    *,
    subject: str,
) -> BfoAssignment | Refused:
    """The strict BFO category of the unit's subject, from its usable tags."""
    from folio_insights.bfo.classifier import BfoInput, BfoUnclassifiable, FolioTag

    item = BfoInput(
        speech_act=speech_act,
        folio_tags=tuple(
            FolioTag(iri=t.iri, verified=True, confidence=max(0.0, min(1.0, t.confidence)))
            for t in eligible.tags
        ),
        subject=subject,
    )
    try:
        return await asyncio.to_thread(classifier.classify, item)
    except BfoUnclassifiable as exc:
        return Refused.single(BFO_UNCLASSIFIABLE, str(exc))
    except RunHalted:
        raise
    except LLMError as exc:
        return Refused.single(BFO_UNCLASSIFIABLE,
                              f"the BFO classifier's LLM fallback failed ({type(exc).__name__})")


__all__ = [
    "DEFAULT_FIELD_FLOOR",
    "FIELD_NAMES",
    "MINT_FIELDS_TASK",
    "FieldFloors",
    "InferredFields",
    "OracleBranchResolver",
    "classify_bfo",
    "detect_framework",
    "field_messages",
    "infer_fields",
    "strict_classifier",
]
