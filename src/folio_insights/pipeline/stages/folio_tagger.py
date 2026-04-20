"""FOLIO tagger pipeline stage: four-path concept extraction and reconciliation.

Four extraction paths run independently on each KnowledgeUnit:
  1. EntityRuler (Aho-Corasick pattern matching against FOLIO labels)
  2. LLM Concept Identification (structured LLM call)
  3. Semantic (embedding similarity search against FOLIO concept embeddings)
  4. Heading Context (document structure -> FOLIO concept mapping)

Results are reconciled via FourPathReconciler and scored with
folio-enrich's 5-stage confidence pipeline.
"""

from __future__ import annotations

import logging
from typing import Any

from folio_insights.models.knowledge_unit import ConceptTag, KnowledgeUnit
from folio_insights.pipeline.stages.base import (
    InsightsJob,
    InsightsPipelineStage,
    record_lineage,
)
from folio_insights.services.bridge.reconciliation_bridge import (
    FourPathReconciler,
    ReconciledConcept,
)
from folio_insights.services.heading_context import HeadingContextExtractor

logger = logging.getLogger(__name__)


class FolioTaggerStage(InsightsPipelineStage):
    """Tag knowledge units with FOLIO concepts via four extraction paths.

    Paths:
      1. entity_ruler: Aho-Corasick pattern matching
      2. llm: LLM concept identification
      3. semantic: Embedding similarity search
      4. heading_context: Document structure heading mapping
    """

    # Minimum FolioService.search_by_label score to accept a label-to-IRI
    # resolution as canonical. Calibrated from UAT I-1: LLM-generated labels
    # are often hyphenated/lower-cased (e.g. 'cross-examine' vs 'Cross-Examination'),
    # which scored 0.6-0.7 against the FOLIO catalogue. The old threshold of 0.7
    # rejected most LLM-path matches, producing empty IRIs. 0.6 is the floor
    # that resolves well-known FOLIO labels without admitting spurious matches
    # (confirmed against the 27K-label FOLIO catalogue).
    _FOLIO_LABEL_RESOLUTION_THRESHOLD = 0.6

    @property
    def name(self) -> str:
        return "folio_tagger"

    async def execute(self, job: InsightsJob) -> InsightsJob:
        """Run all four extraction paths and reconcile for each unit."""
        if not job.units:
            logger.info("No units to tag")
            return job

        # Initialize services
        folio_service = self._get_folio_service()
        embedding_service = self._get_embedding_service()
        aho_matcher = self._get_aho_matcher(folio_service)
        heading_extractor = HeadingContextExtractor(folio_service)
        reconciler = self._get_reconciler(embedding_service)

        for unit in job.units:
            try:
                await self._tag_unit(
                    unit,
                    folio_service=folio_service,
                    embedding_service=embedding_service,
                    aho_matcher=aho_matcher,
                    heading_extractor=heading_extractor,
                    reconciler=reconciler,
                )
            except Exception:
                logger.warning(
                    "Failed to tag unit %s; skipping", unit.id, exc_info=True
                )

        tagged_count = sum(1 for u in job.units if u.folio_tags)
        logger.info(
            "FOLIO tagger: %d/%d units tagged", tagged_count, len(job.units)
        )
        return job

    async def _tag_unit(
        self,
        unit: KnowledgeUnit,
        *,
        folio_service: Any,
        embedding_service: Any,
        aho_matcher: Any,
        heading_extractor: HeadingContextExtractor,
        reconciler: FourPathReconciler,
    ) -> None:
        """Run all four paths and reconcile for a single unit."""
        # Path 1: EntityRuler (Aho-Corasick)
        ruler_concepts = self._run_entity_ruler(unit.text, aho_matcher, folio_service)

        # Path 2: LLM Concept Identification
        llm_concepts = await self._run_llm_concept(unit.text, unit.source_section)

        # Path 3: Semantic (embedding similarity)
        semantic_concepts = self._run_semantic(unit.text, embedding_service)

        # Path 4: Heading Context
        heading_concepts = await heading_extractor.extract_heading_concepts(
            unit.source_section, folio_service
        )
        heading_dicts = [
            {
                "iri": t.iri,
                "label": t.label,
                "confidence": t.confidence,
                "branch": t.branch,
            }
            for t in heading_concepts
        ]

        # Reconcile all four paths
        reconciled = reconciler.reconcile(
            ruler_concepts, llm_concepts, semantic_concepts, heading_dicts
        )

        # Resolve to FOLIO IRIs and create ConceptTags
        tags = self._reconciled_to_tags(reconciled, folio_service)
        unit.folio_tags = tags

        # Set unit confidence from tag confidences
        if tags:
            unit.confidence = max(t.confidence for t in tags)

        # Record lineage
        paths_used = set()
        for rc in reconciled:
            paths_used.update(rc.contributing_paths)

        record_lineage(
            unit,
            stage="folio_tagger",
            action="tag",
            detail=f"{len(tags)} concepts, paths={sorted(paths_used)}",
        )

    def _run_entity_ruler(
        self, text: str, aho_matcher: Any, folio_service: Any
    ) -> list[dict[str, Any]]:
        """Path 1: EntityRuler via Aho-Corasick."""
        if aho_matcher is None:
            return []

        try:
            matches = aho_matcher.find_matches(text)
            concepts = []
            for match in matches:
                concepts.append({
                    "iri": match.entity_id if hasattr(match, "entity_id") else "",
                    "label": match.text if hasattr(match, "text") else str(match),
                    "concept_text": match.text if hasattr(match, "text") else str(match),
                    "confidence": 0.72,  # default entity ruler confidence
                    "branch": "",
                })
            return concepts
        except Exception:
            logger.warning("EntityRuler path failed", exc_info=True)
            return []

    async def _run_llm_concept(
        self, text: str, section_path: list[str]
    ) -> list[dict[str, Any]]:
        """Path 2: LLM concept identification."""
        try:
            from folio_insights.services.bridge.llm_bridge import LLMBridge

            llm_bridge = LLMBridge()
            llm_provider = llm_bridge.get_llm_for_task("concept")

            context = " > ".join(section_path) if section_path else ""
            prompt = (
                f"Identify FOLIO legal ontology concepts in this text. "
                f"Return concept labels and confidence scores.\n\n"
                f"Text: {text}\n"
                f"Section context: {context}"
            )

            result = await llm_provider.structured(
                prompt,
                schema={
                    "type": "object",
                    "properties": {
                        "concepts": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "concept_text": {"type": "string"},
                                    "confidence": {"type": "number"},
                                },
                            },
                        }
                    },
                },
                temperature=0,
            )

            return [
                {
                    "iri": "",
                    "label": c.get("concept_text", ""),
                    "concept_text": c.get("concept_text", ""),
                    "confidence": c.get("confidence", 0.5),
                    "branch": "",
                }
                for c in result.get("concepts", [])
            ]
        except Exception:
            logger.warning("LLM concept path failed", exc_info=True)
            return []

    def _run_semantic(
        self, text: str, embedding_service: Any
    ) -> list[dict[str, Any]]:
        """Path 3: Semantic embedding similarity search."""
        if embedding_service is None or embedding_service.index_size == 0:
            return []

        try:
            results = embedding_service.search(text, top_k=10)
            concepts = []
            for r in results:
                if r.score >= 0.3:  # minimum semantic threshold
                    concepts.append({
                        "iri": r.metadata.get("iri", ""),
                        "label": r.label,
                        "confidence": r.score,
                        "branch": r.metadata.get("branch", ""),
                    })
            return concepts
        except Exception:
            logger.warning("Semantic path failed", exc_info=True)
            return []

    def _reconciled_to_tags(
        self,
        reconciled: list[ReconciledConcept],
        folio_service: Any,
    ) -> list[ConceptTag]:
        """Convert reconciled concepts to ConceptTag objects.

        IRI resolution: if the reconciled concept has no IRI, try
        ``folio_service.search_by_label(rc.label)`` and accept the top match if
        score >= 0.6. If resolution fails, the tag retains ``iri=''`` AND its
        ``extraction_path`` is rewritten to ``'proposed_class'`` so downstream
        consumers (proposed_classes.json, OWL exporter) can route correctly.

        See UAT Issue I-1 for the bug this fixes.
        """
        tags: list[ConceptTag] = []

        for rc in reconciled:
            # Determine primary extraction path from reconciler metadata
            if rc.contributing_paths:
                primary_path = rc.contributing_paths[0]
            else:
                primary_path = "unknown"

            # Resolve IRI via FolioService if the reconciled concept lacks one
            iri = rc.iri
            if not iri and rc.label and folio_service is not None:
                try:
                    results = folio_service.search_by_label(rc.label)
                    if results:
                        top_match, top_score = results[0]
                        if top_score >= self._FOLIO_LABEL_RESOLUTION_THRESHOLD:
                            iri = getattr(top_match, "iri", "") or ""
                except Exception:
                    logger.warning(
                        "search_by_label failed for label=%r",
                        rc.label,
                        exc_info=True,
                    )

            # If still no IRI, this concept is a proposed class — rewrite the
            # extraction path so downstream consumers can distinguish "LLM
            # extracted but no FOLIO match" from ordinary LLM-path hits.
            if not iri:
                primary_path = "proposed_class"

            tag = ConceptTag(
                iri=iri,
                label=rc.label,
                confidence=rc.confidence,
                extraction_path=primary_path,
                branch=rc.branch,
            )
            tags.append(tag)

        return tags

    def _get_folio_service(self) -> Any:
        """Get FolioService from bridge."""
        try:
            from folio_insights.services.bridge.folio_bridge import get_folio_service
            return get_folio_service()
        except Exception:
            logger.warning("FolioService not available", exc_info=True)
            return None

    def _get_embedding_service(self) -> Any:
        """Get EmbeddingService from bridge."""
        try:
            from folio_insights.services.bridge.folio_bridge import get_embedding_service
            return get_embedding_service()
        except Exception:
            logger.warning("EmbeddingService not available", exc_info=True)
            return None

    def _get_aho_matcher(self, folio_service: Any) -> Any:
        """Get AhoCorasickMatcher from bridge."""
        try:
            from folio_insights.services.bridge.folio_bridge import (
                get_aho_corasick_matcher,
            )
            MatcherClass = get_aho_corasick_matcher()
            matcher = MatcherClass()
            if folio_service:
                labels = folio_service.get_all_labels()
                if labels:
                    matcher.load_patterns(labels)
            return matcher
        except Exception:
            logger.warning("AhoCorasickMatcher not available", exc_info=True)
            return None

    def _get_reconciler(self, embedding_service: Any) -> FourPathReconciler:
        """Get FourPathReconciler wrapping folio-enrich's Reconciler."""
        try:
            from folio_insights.services.bridge.folio_bridge import (
                _ensure_folio_enrich_path,
            )
            _ensure_folio_enrich_path()
            from app.services.reconciliation.reconciler import Reconciler

            base = Reconciler(embedding_service=embedding_service)
            return FourPathReconciler(base_reconciler=base)
        except Exception:
            logger.warning(
                "Base Reconciler not available; using simple merge",
                exc_info=True,
            )
            return FourPathReconciler()
