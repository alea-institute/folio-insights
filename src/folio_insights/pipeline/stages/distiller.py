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
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field
from pydantic_settings import BaseSettings

from folio_insights.config import get_settings
from folio_insights.llm.errors import RunHalted
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


class AtomicExtractionSettings(BaseSettings):
    """Atomic-only sizing, loaded only when enabled; legacy settings stay untouched.

    Env: FOLIO_INSIGHTS_ATOMIC_INPUT_TOKEN_BUDGET / OUTPUT_TOKEN_BUDGET.
    Input includes the prompt, schema and framing; output also caps generation.
    """

    input_token_budget: int = Field(default=32768, gt=0)
    output_token_budget: int = Field(default=16384, gt=0)

    model_config = {"env_prefix": "FOLIO_INSIGHTS_ATOMIC_", "env_file": ".env", "extra": "ignore"}


@dataclass(frozen=True)
class _AtomicBlock:
    id: str
    parent: KnowledgeUnit
    start: int
    end: int


def _atomic_admitted(text: str) -> bool:
    """Relax only the legacy one/two-word shortcut for terminated statements."""
    if not text:
        return False
    if not is_structural(text):
        return True
    words = re.findall(r"[^\W\d_]+", text, re.UNICODE)
    if not 1 <= len(words) <= 2 or not re.search(r"[.!?][\"')\]]*$", text):
        return False
    return not re.search(r"\.{4,}", text) and not re.match(
        r"^(?:[—–-]|[\d]+|[IVXLCDM]+[.)]|[A-Za-z][.)]|"
        r"(?:section|chapter|part|article|appendix|title|clause|subsection|rule)\b)",
        text, re.IGNORECASE,
    )


def _atomic_prompt(group: list[_AtomicBlock], source: str) -> str:
    return ATOMIC_DISTILL.render(blocks=json.dumps([
        {"id": b.id, "text": source[b.start:b.end], "section_path": b.parent.source_section}
        for b in group
    ], ensure_ascii=False))


def _split_atomic_group(group: list[_AtomicBlock], source: str) -> list[list[_AtomicBlock]]:
    """Shrink at sentence boundaries, sharing a whole sentence where possible.

    Two-sentence leaves must become singletons to make progress; an indivisible
    sentence is never cut, even when it exceeds the budget.
    """
    if len(group) > 2:
        middle = len(group) // 2
        return [group[:middle + 1], group[middle:]]
    if len(group) == 2:
        left, right = group
        right_parts = _split_atomic_group([right], source)
        if right_parts:
            return [[left, *right_parts[0]], [right]]
        left_parts = _split_atomic_group([left], source)
        if left_parts:
            return [[left], [*left_parts[-1], right]]
        return [[left], [right]]
    block = group[0]
    from folio_insights.services.text_normalization import split_sentences

    spans = []
    position = block.start
    for sentence in split_sentences(source[block.start:block.end]):
        start = source.find(sentence, position, block.end)
        if start < 0:
            # A tokenizer that rewrites source bytes cannot provide safe cut points.
            return []
        position = start + len(sentence)
        spans.append((start, position))
    if len(spans) <= 1:
        return []
    middle = len(spans) // 2
    return [[_AtomicBlock(f"{block.id}.{start}-{end}", block.parent, start, end)]
            for start, end in [(block.start, spans[middle if len(spans) > 2 else 0][1]),
                               (spans[middle][0], block.end)]]


class DistillerStage(InsightsPipelineStage):
    """Distill knowledge unit text to its core insight.

    Replaces unit.text with compressed distilled form while keeping
    the original text accessible via original_span. Updates
    content_hash with hash of distilled text.
    """

    def __init__(
        self, *, atomic_extraction: bool = False,
        input_token_budget: int | None = None, output_token_budget: int | None = None,
    ) -> None:
        self.atomic_extraction = atomic_extraction
        if atomic_extraction:
            overrides = {key: value for key, value in {
                "input_token_budget": input_token_budget,
                "output_token_budget": output_token_budget,
            }.items() if value is not None}
            settings = AtomicExtractionSettings(**overrides)
            self.input_token_budget = settings.input_token_budget
            self.output_token_budget = settings.output_token_budget

    def _atomic_group_fits(self, group: list[_AtomicBlock], source: str) -> bool:
        # Match llm.cost's conservative byte-per-token bound and framing allowance.
        prompt_bytes = len(_atomic_prompt(group, source).encode("utf-8"))
        schema_bytes = len(json.dumps(AtomicDistilledOutput.model_json_schema()).encode("utf-8"))
        input_bound = prompt_bytes + schema_bytes + 1024
        # Allow expansion for rules, elements, links and JSON keys. Provider length
        # failures still trigger smaller groups: this is an estimate, not a proof.
        output_bound = 128 + sum(6 * len(source[b.start:b.end].encode("utf-8")) + 256
                                 for b in group)
        return input_bound <= self.input_token_budget and output_bound <= self.output_token_budget

    def _atomic_groups(
        self, blocks: list[_AtomicBlock], source: str, diagnostics: list[dict],
    ) -> list[list[_AtomicBlock]]:
        pieces: list[_AtomicBlock] = []
        seen: set[tuple[int, int]] = set()

        def fit(block: _AtomicBlock) -> None:
            if (block.start, block.end) in seen:
                return
            seen.add((block.start, block.end))
            if self._atomic_group_fits([block], source):
                pieces.append(block)
                return
            smaller = _split_atomic_group([block], source)
            if not smaller:
                diagnostics.append({"source_file": block.parent.source_file,
                                    "local_id": block.id, "reason": "oversized_sentence",
                                    "start": block.start, "end": block.end})
                pieces.append(block)
                return
            for group in smaller:
                fit(group[0])

        for block in blocks:
            fit(block)
        groups: list[list[_AtomicBlock]] = []
        group: list[_AtomicBlock] = []
        for block in pieces:
            if group and not self._atomic_group_fits([*group, block], source):
                groups.append(group)
                group = [group[-1]] if self._atomic_group_fits([group[-1], block], source) else []
            group.append(block)
        if group:
            groups.append(group)
        return groups

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

        Boundary shape checks control admission. Overlapping bounded groups retain
        adjacent context; grounded children and links reconcile at document scope.
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
            list_evidence = any(event.stage == "boundary_detection" and event.action == "split"
                                and event.detail == "method=structural_list_evidence"
                                for event in parent.lineage)
            if not _atomic_admitted(text) and not list_evidence:
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
            if (anchor is None or not anchor.verified
                    or not (_atomic_admitted(anchor.snippet)
                            or (list_evidence and anchor.snippet == text))):
                diagnostic(parent.id, "unverified_input")
                continue
            start, end = offset + anchor.start, offset + anchor.end
            blocks[f"b{index}"] = (parent, start, end)
            used.add((start, end))
        if not blocks:
            return [], diagnostics

        ordered_blocks = [_AtomicBlock(id, parent, start, end)
                          for id, (parent, start, end) in sorted(
                              blocks.items(), key=lambda item: (item[1][1], item[1][2]))]
        outputs: list[tuple[AtomicDistilledOutput, dict[str, tuple[KnowledgeUnit, int, int]]]] = []
        provider = bridge.get_llm_for_task("distiller")  # type: ignore[union-attr]

        async def extract_group(group: list[_AtomicBlock]) -> None:
            try:
                result = await provider.structured(
                    _atomic_prompt(group, source), schema=AtomicDistilledOutput,
                    template=ATOMIC_DISTILL, temperature=0, max_tokens=self.output_token_budget,
                )
                output = AtomicDistilledOutput.model_validate(result)
            except RunHalted:
                raise
            except Exception as exc:
                # Size rejections and truncated completions cannot succeed as-is.
                # The port does not retry these errors; retry strictly smaller groups.
                message = str(exc).lower()
                oversized = any(term in message for term in (
                    "context length", "context_length", "context window", "max_tokens",
                    "max tokens", "token limit", "too many tokens", "request too large",
                    "incompleteoutputexception",
                )) or getattr(exc, "status_code", None) == 413
                smaller = _split_atomic_group(group, source) if oversized else []
                if smaller:
                    diagnostic(group[0].id, "oversized_group_split", block_ids=[b.id for b in group])
                    for child_group in smaller:
                        await extract_group(child_group)
                    return
                if oversized:
                    diagnostic(group[0].id, "oversized_sentence",
                               start=group[0].start, end=group[0].end)
                tracker.attempt()
                tracker.failure(file, exc)
                diagnostic(group[0].id, "llm_failed", block_ids=[b.id for b in group])
                logger.warning("Atomic extraction group failed for %s", file, exc_info=True)
                return
            # Only terminal groups count: a size-rejected parent is superseded by
            # its children, so counting it would dilute the terminal failure ratio.
            tracker.attempt()
            outputs.append((output, {b.id: (b.parent, b.start, b.end) for b in group}))

        for group in self._atomic_groups(ordered_blocks, source, diagnostics):
            await extract_group(group)

        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        provenance = SourceProvenance(
            source_snapshot_id=data.get("source_snapshot_id") or file,
            source_sha256=digest,
            genre=data.get("genre") or job.metadata.get("genre", "know-how"),
            subgenre=data.get("subgenre", ""),
        )
        counts = {group: Counter(p.id for p in output.propositions)
                  for group, (output, _) in enumerate(outputs)}
        ambiguous_aliases = {id for counter in counts.values()
                             for id, count in counter.items() if count > 1}
        candidates = [(group, candidate, support_blocks)
                      for group, (output, support_blocks) in enumerate(outputs)
                      for candidate in output.propositions]
        accepted: list[tuple[int, AtomicProposition, KnowledgeUnit]] = []
        resolved: dict[tuple[int, str], str] = {}
        aliases: dict[str, set[str]] = {}
        unique: dict[tuple[int, int, str], KnowledgeUnit] = {}
        # Overlapping requests may legitimately re-emit the same occurrence. Allocate
        # independently per response, then reconcile equal source spans below.
        occurrence_uses: dict[tuple[int, str], Counter[tuple[int, int]]] = {}
        for group, candidate, blocks in candidates:
            if any(id not in blocks for id in candidate.support_ids):
                diagnostic(candidate.id, "missing_support", support_ids=candidate.support_ids)
                continue
            supports = [blocks[id] for id in dict.fromkeys(candidate.support_ids)]
            start = min(s[1] for s in supports)
            end = max(s[2] for s in supports)
            evidence = source[start:end]
            text = candidate.text.strip()
            if not text or (candidate.kind not in {"element", "citation"} and not _atomic_admitted(text)):
                diagnostic(candidate.id, "non_substantive")
                continue
            support = check_support(text, evidence)
            if not support.supported:
                for code, _ in support.failures():
                    diagnostic(candidate.id, code, support_recall=support.ratio)
                continue

            # A narrow exact match is useful for highlighting, but a paraphrase must keep
            # its complete supporting blocks, not a fuzzy fragment or its parent's score.
            if (text in evidence and check_support(text, text).supported
                    and all(citation in text for citation in candidate.citations)):
                occurrences = []
                position = evidence.find(text)
                while position >= 0:
                    occurrences.append((start + position, start + position + len(text)))
                    position = evidence.find(text, position + len(text))
                uses = occurrence_uses.setdefault(
                    (group, unicodedata.normalize("NFC", text)), Counter(),
                )
                # First unused match in source order; surplus emissions cycle over
                # existing matches so their aliases and links still resolve.
                start, end = min(occurrences, key=lambda span: uses[span])
                if uses[start, end]:
                    diagnostic(candidate.id, "surplus_occurrence", start=start, end=end,
                               occurrence_count=len(occurrences))
                uses[start, end] += 1
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
                id=str(uuid5(NAMESPACE_URL, json.dumps([
                    file, digest, start, end, unicodedata.normalize("NFC", text),
                ]))),
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
            key = (start, end, unicodedata.normalize("NFC", text))
            if key in unique:
                existing = unique[key]
                for citation in unit.unresolved_citations:
                    if citation not in existing.unresolved_citations:
                        existing.unresolved_citations.append(citation)
                unit = existing
            else:
                unique[key] = unit
            accepted.append((group, candidate, unit))
            if counts[group][candidate.id] == 1:
                resolved[group, candidate.id] = unit.id
                aliases.setdefault(candidate.id, set()).add(unit.id)

        # Resolve only after all children have stable IDs and independent grounding.
        for group, candidate, unit in accepted:
            for link in candidate.links:
                targets = aliases.get(link.target_id, set())
                target = resolved.get((group, link.target_id))
                cross_group = counts[group][link.target_id] == 0
                if (cross_group and link.target_id not in ambiguous_aliases
                        and len(targets) == 1):
                    target = next(iter(targets))
                reason = ("self_endpoint" if link.target_id == candidate.id or target == unit.id else
                          "ambiguous_endpoint" if counts[group][link.target_id] > 1 or
                          (cross_group and (len(targets) > 1 or
                                            link.target_id in ambiguous_aliases)) else
                          "missing_endpoint" if target is None else "")
                if reason:
                    diagnostic(candidate.id, reason, relation=link.relation, target_id=link.target_id)
                    continue
                resolved_link = PropositionLink(relation=link.relation, target_id=target)
                if resolved_link not in unit.links:
                    unit.links.append(resolved_link)
        units = finalize_document(list(unique.values()), source_text=source,
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
