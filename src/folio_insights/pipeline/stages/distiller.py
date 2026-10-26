"""Distill legacy insights or opt into grounded atomic propositions.

Preserves tactical nuance while stripping filler, hedging, repetition,
and attribution phrases. Calls the LLM port (``folio_insights.llm``) for validated
structured output under the ``distiller.distill`` prompt template, and records that template's
id and hash on the unit's ``distill`` lineage event (KTD2).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections import Counter
from uuid import NAMESPACE_URL, uuid5

from folio_insights.config import get_settings
from folio_insights.llm.schemas import AtomicDistilledOutput, AtomicProposition, DistilledOutput
from folio_insights.llm.templates import ATOMIC_DISTILL, DISTILL
from folio_insights.minting.support import check_support
from folio_insights.models.knowledge_unit import (
    KnowledgeType,
    KnowledgeUnit,
    PropositionLink,
    SourceProvenance,
    Span,
    UnresolvedCitation,
    finalize_document,
)
from folio_insights.pipeline.stages.base import (
    InsightsJob,
    InsightsPipelineStage,
    LLMFailureTracker,
    record_lineage,
)
from folio_insights.services.anchoring import resolve_anchor
from folio_insights.services.substance import is_structural, is_substantive

logger = logging.getLogger(__name__)

# Batch size for LLM calls
_BATCH_SIZE = 15


__all__ = ["DistilledOutput", "DistillerStage"]


class DistillerStage(InsightsPipelineStage):
    """Distill knowledge unit text to its core insight.

    Replaces unit.text with compressed distilled form while keeping
    the original text accessible via original_span. Updates
    content_hash with hash of distilled text.
    """

    def __init__(self, *, atomic_extraction: bool = False) -> None:
        self.atomic_extraction = atomic_extraction

    @property
    def name(self) -> str:
        return "distiller"

    async def execute(self, job: InsightsJob) -> InsightsJob:
        """Distill all knowledge units in the job via LLM.

        Batches units in groups for efficiency. Temperature=0 for
        extraction consistency.
        """
        if self.atomic_extraction:
            return await self._extract_atomic(job)

        if not job.units:
            logger.info("No units to distill")
            return job

        from folio_insights.services.bridge.llm_bridge import LLMBridge

        llm_bridge = LLMBridge()
        tracker = LLMFailureTracker("distiller", "distill")

        # Process in batches
        for batch_start in range(0, len(job.units), _BATCH_SIZE):
            batch = job.units[batch_start : batch_start + _BATCH_SIZE]
            tasks = [self._distill_unit(unit, llm_bridge, tracker) for unit in batch]
            await asyncio.gather(*tasks, return_exceptions=True)
        tracker.check(job)

        logger.info("Distilled %d knowledge units", len(job.units))
        return job

    async def _extract_atomic(self, job: InsightsJob) -> InsightsJob:
        """Extract lists over document-local blocks, then resolve all endpoints together.

        Boundary checks still control admission. Seeing all admitted blocks together lets
        the model retain rules split at 600 characters and links across subdivisions.
        """
        from folio_insights.services.bridge.llm_bridge import LLMBridge

        diagnostics: list[dict] = []
        job.metadata["atomic_extraction"] = {"enabled": True, "diagnostics": diagnostics}
        documents: dict[str, list[KnowledgeUnit]] = {}
        for unit in job.units:
            documents.setdefault(unit.source_file, []).append(unit)
        bridge = LLMBridge()
        tracker = LLMFailureTracker("distiller", "atomic")
        extracted: list[KnowledgeUnit] = []
        items = list(documents.items())
        for start in range(0, len(items), _BATCH_SIZE):
            results = await asyncio.gather(*(
                self._extract_document(file, units, job, bridge, tracker)
                for file, units in items[start:start + _BATCH_SIZE]
            ))
            for units, details in results:
                extracted.extend(units)
                diagnostics.extend(details)
        tracker.check(job)
        job.units = extracted
        return job

    async def _extract_document(
        self, file: str, parents: list[KnowledgeUnit], job: InsightsJob,
        bridge: object, tracker: LLMFailureTracker,
    ) -> tuple[list[KnowledgeUnit], list[dict]]:
        diagnostics: list[dict] = []

        def diagnostic(local_id: str, reason: str, **detail: object) -> None:
            diagnostics.append({"source_file": file, "local_id": local_id,
                                "reason": reason, **detail})

        data = job.metadata.get("ingested", {}).get(file, {}) or {}
        source = data.get("text", "") or ""
        if not source:
            for parent in parents:
                diagnostic(parent.id, "missing_source")
            return [], diagnostics

        # Re-resolve against canonical bytes. Repeated legacy boundaries may all point
        # at the first occurrence; allocate each identical block its own occurrence.
        blocks: dict[str, tuple[KnowledgeUnit, int, int]] = {}
        used: set[tuple[int, int]] = set()
        for index, parent in enumerate(parents):
            text = parent.text.strip()
            if not is_substantive(text, get_settings().min_substantive_chars):
                diagnostic(parent.id, "non_substantive")
                continue
            span = parent.original_span
            if 0 <= span.start < span.end <= len(source) and source[span.start:span.end] == text:
                offset = span.start
                anchor = resolve_anchor(text, source[span.start:span.end])
            else:
                offset = 0
                anchor = resolve_anchor(text, source)
            if anchor and (offset + anchor.start, offset + anchor.end) in used:
                position = source.find(text)
                while position >= 0 and (position, position + len(text)) in used:
                    position = source.find(text, position + 1)
                if position >= 0:
                    offset = position
                    anchor = resolve_anchor(text, source[position:position + len(text)])
            if anchor is None or not anchor.verified or not is_substantive(
                anchor.snippet, get_settings().min_substantive_chars,
            ):
                diagnostic(parent.id, "unverified_input")
                continue
            start, end = offset + anchor.start, offset + anchor.end
            blocks[f"b{index}"] = (parent, start, end)
            used.add((start, end))
        if not blocks:
            return [], diagnostics

        ordered_blocks = sorted(blocks.items(), key=lambda item: (item[1][1], item[1][2]))
        prompt = ATOMIC_DISTILL.render(blocks=json.dumps([
            {"id": id, "text": source[start:end], "section_path": parent.source_section}
            for id, (parent, start, end) in ordered_blocks
        ], ensure_ascii=False))
        tracker.attempt()
        try:
            provider = bridge.get_llm_for_task("distiller")  # type: ignore[union-attr]
            result = await provider.structured(
                prompt, schema=AtomicDistilledOutput, template=ATOMIC_DISTILL, temperature=0,
            )
            output = AtomicDistilledOutput.model_validate(result)
        except Exception as exc:
            tracker.failure(file, exc)
            diagnostic(file, "llm_failed")
            logger.warning("Atomic extraction failed for %s", file, exc_info=True)
            return [], diagnostics

        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        provenance = SourceProvenance(
            source_snapshot_id=data.get("source_snapshot_id") or file,
            source_sha256=digest,
            genre=data.get("genre") or job.metadata.get("genre", "know-how"),
            subgenre=data.get("subgenre", ""),
        )
        counts = Counter(p.id for p in output.propositions)
        accepted: list[tuple[AtomicProposition, KnowledgeUnit]] = []
        resolved: dict[str, str] = {}
        for index, candidate in enumerate(output.propositions):
            if any(id not in blocks for id in candidate.support_ids):
                diagnostic(candidate.id, "missing_support", support_ids=candidate.support_ids)
                continue
            supports = [blocks[id] for id in dict.fromkeys(candidate.support_ids)]
            start = min(s[1] for s in supports)
            end = max(s[2] for s in supports)
            evidence = source[start:end]
            text = candidate.text.strip()
            if not text or (candidate.kind not in {"element", "citation"} and is_structural(text)):
                diagnostic(candidate.id, "non_substantive")
                continue
            support = check_support(text, evidence)
            if not support.supported:
                for code, _ in support.failures():
                    diagnostic(candidate.id, code, support_recall=support.ratio)
                continue

            # A narrow exact match is useful for highlighting, but a paraphrase must keep
            # its complete supporting blocks, not a fuzzy fragment or its parent's score.
            anchor = resolve_anchor(text, evidence)
            if (anchor is not None and anchor.score == 1.0
                    and evidence.count(text) == 1 and check_support(text, anchor.snippet).supported
                    and all(citation in anchor.snippet for citation in candidate.citations)):
                end = start + anchor.end
                start += anchor.start
                evidence = source[start:end]
            exact = resolve_anchor(evidence, source[start:end])
            if exact is None or not exact.verified or exact.score != 1.0:
                diagnostic(candidate.id, "unverified_child")
                continue
            unit_type = (KnowledgeType.CITATION if candidate.kind == "citation" else
                         KnowledgeType.ADVICE if candidate.kind == "advice" else
                         KnowledgeType.RULE if candidate.kind in {"rule", "element", "exception",
                                                                 "penalty"} else
                         KnowledgeType.PRINCIPLE)
            unit = KnowledgeUnit(
                id=str(uuid5(NAMESPACE_URL, json.dumps([file, digest, index, text]))),
                text=text, original_span=Span(start=start, end=end, source_file=file),
                source_snippet=evidence, anchor_verified=True, anchor_score=exact.score,
                source_file=file, source_section=list(supports[0][0].source_section),
                unit_type=unit_type, proposition_kind=candidate.kind, provenance=provenance,
                content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                lineage=[event.model_copy(deep=True) for parent, _, _ in supports
                         for event in parent.lineage],
            )
            record_lineage(unit, stage="distiller", action="atomic_extract",
                           detail=f"support_recall={support.ratio:.4f};method={support.method}",
                           template=ATOMIC_DISTILL)
            for citation in candidate.citations:
                if citation.strip() and citation in evidence:
                    item = UnresolvedCitation(citation=citation)
                    if item not in unit.unresolved_citations:
                        unit.unresolved_citations.append(item)
                else:
                    diagnostic(candidate.id, "unsupported_citation")
            accepted.append((candidate, unit))
            if counts[candidate.id] == 1:
                resolved[candidate.id] = unit.id

        # Resolve only after all children have stable IDs and independent grounding.
        for candidate, unit in accepted:
            for link in candidate.links:
                reason = ("self_endpoint" if link.target_id == candidate.id else
                          "ambiguous_endpoint" if counts[link.target_id] > 1 else
                          "missing_endpoint" if link.target_id not in resolved else "")
                if reason:
                    diagnostic(candidate.id, reason, relation=link.relation, target_id=link.target_id)
                    continue
                resolved_link = PropositionLink(relation=link.relation, target_id=resolved[link.target_id])
                if resolved_link not in unit.links:
                    unit.links.append(resolved_link)
        units = finalize_document([unit for _, unit in accepted], source_text=source,
                                  source_snapshot_id=provenance.source_snapshot_id)
        return units, diagnostics

    async def _distill_unit(
        self,
        unit: KnowledgeUnit,
        llm_bridge: object,
        tracker: LLMFailureTracker | None = None,
    ) -> None:
        """Distill a single knowledge unit's text."""
        # B6, defence in depth: never hand a heading, contents entry or attribution line to the
        # generative distiller (boundary detection already drops them; this catches any that
        # arrive another way). The unit keeps its text and records why it was not distilled.
        if not is_substantive(unit.text, get_settings().min_substantive_chars):
            record_lineage(
                unit,
                stage="distiller",
                action="distill_skipped",
                detail="non-substantive input (heading/contents/attribution); not distilled",
            )
            return

        section_context = " > ".join(unit.source_section) if unit.source_section else "N/A"

        prompt = DISTILL.render(text=unit.text, section_path=section_context)

        if tracker is not None:
            tracker.attempt()
        try:
            llm_provider = llm_bridge.get_llm_for_task("distiller")  # type: ignore[union-attr]
            result = await llm_provider.structured(
                prompt, schema=DistilledOutput, template=DISTILL, temperature=0
            )

            distilled_text = result.get("distilled_text", "").strip()
            if distilled_text:
                unit.text = distilled_text
                unit.content_hash = hashlib.sha256(
                    distilled_text.encode("utf-8")
                ).hexdigest()

            record_lineage(
                unit,
                stage="distiller",
                action="distill",
                detail=f"compressed from {len(unit.original_span.source_file)} chars",
                template=DISTILL,
            )

        except Exception as exc:
            if tracker is not None:
                tracker.failure(unit.id, exc)
            logger.warning(
                "Distillation failed for unit %s; keeping original text",
                unit.id,
                exc_info=True,
            )
            # The failed call shaped nothing, so this event names no template: a unit's prompt
            # hash covers only the templates whose output it carries (KTD2).
            record_lineage(
                unit,
                stage="distiller",
                action="distill_failed",
                detail="LLM call failed; original text retained",
            )
