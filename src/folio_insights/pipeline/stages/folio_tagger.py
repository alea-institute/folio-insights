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


def _load_alias_blocklist() -> Any:
    """Load the shipped seed alias blocklist (Action != Auction + agency homonyms).

    The seed now ships inside the pinned ``folio_matching`` package as recorded Ch01/Ch02 verdicts
    keyed on **real** FOLIO IRIs (the old placeholder used a synthetic ``EXAMPLE-Auction`` IRI that
    could never match live resolution — the Ch02 proving run's defect #3). Never raises.
    """
    from folio_matching import load_seed_blocklist

    return load_seed_blocklist()


class FolioTaggerStage(InsightsPipelineStage):
    """Tag knowledge units with FOLIO concepts via four extraction paths.

    Paths:
      1. entity_ruler: Aho-Corasick pattern matching
      2. llm: LLM concept identification
      3. semantic: Embedding similarity search
      4. heading_context: Document structure heading mapping
    """

    # Label -> IRI resolution (the whole-string acceptance bar and decompose-first ordering) is
    # owned by the pinned ``folio_matching.LabelResolver``. The old class-local ``0.6`` bar was a
    # latent scale bug: FolioService.search_by_label returns a 0-100 score, so 0.6 accepted every
    # top match and generic terms mis-mapped to short place/agency labels (the Ch02 proving-run
    # regression). The calibrated bar (92.0) now lives in ``folio_matching.WHOLE_STRING_THRESHOLD``.

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
        # Metadata / front-matter exclusion (Ch02 unit d3c44e2a): a unit whose source is a
        # title page, copyright block, TOC, index, or publisher metadata is not substantive legal
        # content and must never be tagged. SourceClassifier declares this as a first-class policy
        # instead of a heuristic buried in the tagger (proving-run defect #4).
        if not self._is_taggable_source(unit):
            unit.folio_tags = []
            record_lineage(
                unit,
                stage="folio_tagger",
                action="skip",
                detail="excluded: non-taggable source (metadata/front-matter)",
            )
            return

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
        """Convert reconciled concepts to ConceptTag objects (Ch02 precision-fix path).

        Resolution is delegated to the pinned ``folio_matching.LabelResolver`` so every consumer
        resolves identically (proving-run defects #1 and #2):

        * **Decompose-first for multi-head strings.** A conjoined heading such as "Proposed
          Findings of Fact and Conclusions of Law" resolves each conjunct *before* the whole
          string is considered, yielding one tag per sibling concept (unit ``12b5e434``) instead
          of one wrong whole-string partial.
        * **Calibrated whole-string bar on the real 0-100 scale.** The old ``>= 0.6`` bar was a
          no-op (FOLIO scores 0-100), so generic terms latched onto the short place/agency labels
          rapidfuzz over-scores to 90 ("law" -> Delaware). The bar is now 92.0.
        * **Every resolved tag carries its branch**, so the place/agency gate can veto it.

        A concept whose label resolves to nothing (proposed class) keeps ``iri=''`` and is tagged
        ``proposed_class``. Gates run last: the alias blocklist and the place/agency corroboration
        veto are deterministic — high LLM confidence does NOT exempt a tag from them.
        """
        resolver = None
        if folio_service is not None:
            from folio_matching import LabelResolver

            resolver = LabelResolver(folio_service.search_by_label)

        tags: list[ConceptTag] = []
        for rc in reconciled:
            primary_path = rc.contributing_paths[0] if rc.contributing_paths else "unknown"
            paths = rc.contributing_paths or [primary_path]

            if rc.iri:
                # A path (entity_ruler / semantic / heading_context) already supplied the IRI.
                # Populate branch if the path left it empty so the gate can see every tag.
                branch = rc.branch or self._branch_for(rc.iri, folio_service)
                tags.append(
                    self._gate_or_none(
                        ConceptTag(
                            iri=rc.iri,
                            label=rc.label,
                            confidence=rc.confidence,
                            extraction_path=primary_path,
                            branch=branch,
                        ),
                        resolved_label=self._label_for(rc.iri, folio_service) or rc.label,
                        surface=rc.label,
                        paths=paths,
                    )
                )
                continue

            resolved = resolver.resolve(rc.label) if (resolver and rc.label) else []
            if resolved:
                seen: set[str] = set()
                for r in resolved:
                    if r.iri in seen:
                        continue
                    seen.add(r.iri)
                    tags.append(
                        self._gate_or_none(
                            ConceptTag(
                                iri=r.iri,
                                label=r.surface or rc.label,
                                confidence=rc.confidence,
                                extraction_path=primary_path,
                                branch=r.branch,
                            ),
                            resolved_label=r.label,
                            surface=r.surface or rc.label,
                            paths=paths,
                        )
                    )
            else:
                # No FOLIO match: a genuine proposed class (empty IRI, distinct extraction path).
                tags.append(
                    ConceptTag(
                        iri="",
                        label=rc.label,
                        confidence=rc.confidence,
                        extraction_path="proposed_class",
                        branch=rc.branch,
                    )
                )

        return self._apply_match_gates([t for t in tags if t is not None])

    def _gate_or_none(
        self,
        tag: ConceptTag,
        *,
        resolved_label: str,
        surface: str,
        paths: list[str],
    ) -> ConceptTag | None:
        """Return the tag, or ``None`` if the place/agency gate vetoes it.

        The gate keys on the resolved *branch* (now always populated). A place- or
        governmental-body-branch tag is a mis-map unless corroborated by >= 2 signals. Only
        **non-heading** paths count as corroboration, and heading context contributes at most one
        signal — so a place resolved on a single path, or propagated through headings alone
        (Slovenia -> 118 units, the actual vector), is vetoed. The surface term is trusted only
        for non-heading paths (heading extraction stores the resolved label as its surface).
        """
        from folio_matching import PlaceNameGate

        if not tag.iri or not self._is_place_or_agency(tag.branch):
            return tag
        non_heading = [p for p in paths if p != "heading_context"]
        is_heading = "heading_context" in paths
        gate_query = surface if non_heading else ""  # untrusted heading surface -> no exact exempt
        decision = PlaceNameGate(min_signals=2).evaluate(
            query=gate_query,
            label=resolved_label,
            branch=tag.branch,
            score=tag.confidence * 100.0,
            heading_context_match=is_heading,
            corroborating_signals=len(non_heading),
        )
        if decision.demoted:
            logger.debug("Place/agency gate vetoed %s -> %s (%s)", surface, tag.iri, decision.reason)
            return None
        return tag

    def _apply_match_gates(self, tags: list[ConceptTag]) -> list[ConceptTag]:
        """Final deterministic veto pass: the alias blocklist (Action != Auction + agency homonyms).

        The place/agency gate runs earlier at resolution time (``_gate_or_none``) where the surface
        term and resolved label are both known. Here the shipped seed blocklist drops recorded
        homonym pairings (real FOLIO IRIs) regardless of LLM confidence (Ch02 unit 4b06a90c).
        """
        blocklist = self._get_alias_blocklist()
        kept: list[ConceptTag] = []
        for tag in tags:
            if tag.iri and blocklist.is_blocked(tag.label, tag.iri):
                logger.debug("Alias blocklist dropped %s -> %s", tag.label, tag.iri)
                continue
            kept.append(tag)
        return kept

    def _branch_for(self, iri: str, folio_service: Any) -> str:
        """Resolve a concept's branch from the ontology by IRI (cached per process)."""
        if not iri or folio_service is None:
            return ""
        cache = self._branch_cache
        if iri in cache:
            return cache[iri]
        branch = ""
        try:
            concept = folio_service.get_concept(iri)
            branch = getattr(concept, "branch", "") or ""
        except Exception:
            logger.warning("branch lookup failed for iri=%r", iri, exc_info=True)
        cache[iri] = branch
        return branch

    def _label_for(self, iri: str, folio_service: Any) -> str:
        """Resolve a concept's canonical FOLIO label from the ontology by IRI (cached)."""
        if not iri or folio_service is None:
            return ""
        cache = self._label_cache
        if iri in cache:
            return cache[iri]
        label = ""
        try:
            concept = folio_service.get_concept(iri)
            label = getattr(concept, "preferred_label", "") or getattr(concept, "label", "") or ""
        except Exception:
            logger.warning("label lookup failed for iri=%r", iri, exc_info=True)
        cache[iri] = label
        return label

    @property
    def _branch_cache(self) -> dict[str, str]:
        cache = getattr(self, "_branch_cache_store", None)
        if cache is None:
            cache = {}
            self._branch_cache_store = cache
        return cache

    @property
    def _label_cache(self) -> dict[str, str]:
        cache = getattr(self, "_label_cache_store", None)
        if cache is None:
            cache = {}
            self._label_cache_store = cache
        return cache

    def _is_taggable_source(self, unit: KnowledgeUnit) -> bool:
        """Whether a unit's source is eligible for tagging (metadata/front-matter excluded)."""
        from folio_matching import SourceClassifier

        classifier = getattr(self, "_source_classifier", None)
        if classifier is None:
            classifier = SourceClassifier()
            self._source_classifier = classifier
        section_label = " > ".join(unit.source_section) if unit.source_section else ""
        return bool(classifier.is_taggable(section_label, unit.text or ""))

    @staticmethod
    def _is_place_or_agency(branch: str) -> bool:
        from folio_matching.gates import _PLACE_BRANCH_MARKERS

        b = (branch or "").lower()
        return any(marker in b for marker in _PLACE_BRANCH_MARKERS)

    def _get_alias_blocklist(self) -> Any:
        if getattr(self, "_alias_blocklist", None) is None:
            self._alias_blocklist = _load_alias_blocklist()
        return self._alias_blocklist

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
        """Get the entity ruler backed by the pinned ``folio_matching.FOLIOEntityRuler``.

        Migration item #1 (continued): the ruler previously sys.path-imported folio-enrich's
        ``AhoCorasickMatcher`` from ``app.services.concept.entity_ruler``. That module moved in
        folio-enrich (to ``app.services.matching``), breaking the import and silently dropping the
        entire entity-ruler extraction path. The pinned ``FOLIOEntityRuler`` is a faithful,
        dependency-free port with the same ``load_patterns(dict[str, LabelInfo])`` /
        ``find_matches(text) -> [.. .entity_id, .text]`` interface, and consumes
        ``folio_service.get_all_labels()`` directly (folio-enrich ``LabelInfo`` is duck-compatible:
        ``.concept.iri`` + ``.label_type``). This removes the fragile folio-enrich matcher import.
        """
        try:
            from folio_matching import FOLIOEntityRuler

            ruler = FOLIOEntityRuler()
            if folio_service:
                labels = folio_service.get_all_labels()
                if labels:
                    ruler.load_patterns(labels)
            return ruler
        except Exception:
            logger.warning("FOLIOEntityRuler not available", exc_info=True)
            return None

    def _get_reconciler(self, embedding_service: Any) -> FourPathReconciler:
        """Get FourPathReconciler backed by the pinned ``folio_matching.Reconciler``.

        Migration item #1: replaces the sys.path import of folio-enrich's Reconciler with
        the pinned package. If ``embedding_service`` exposes ``similarity_batch`` the triage
        path is wired; otherwise the deterministic 2-pass reconcile is used.
        """
        try:
            from folio_matching import Reconciler

            sim = getattr(embedding_service, "similarity_batch", None)
            index_size = int(getattr(embedding_service, "index_size", 0) or 0)
            base = Reconciler(
                similarity_batch=sim if callable(sim) else None,
                index_size=index_size,
            )
            return FourPathReconciler(base_reconciler=base)
        except Exception:
            logger.warning(
                "Pinned Reconciler not available; using simple merge",
                exc_info=True,
            )
            return FourPathReconciler()
