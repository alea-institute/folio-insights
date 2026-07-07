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
        # Deterministic FOLIO IRI path (entity ruler). Loud on failure — a
        # silent fallback to LLM/semantic guessing is what buried the
        # wrong-concept-IRI bug (docs/solutions/sys-path-bridge-staleness.md).
        aho_matcher, det_status, det_reason = self._get_entity_ruler(folio_service)
        job.metadata["folio_tagger"] = {
            "deterministic_iri_path": det_status,  # "active" | "degraded"
            "deterministic_iri_reason": det_reason,
        }
        if det_status != "active":
            logger.error(
                "FOLIO tagger running in DEGRADED mode — deterministic IRI "
                "path unavailable (%s). Tags will come from LLM/semantic "
                "paths only and may be wrong-concept. Surfaced in output "
                "metadata.folio_tagger.",
                det_reason,
            )
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
        ruler_tag_count = sum(
            1
            for u in job.units
            for t in u.folio_tags
            if t.extraction_path == "entity_ruler"
        )
        job.metadata["folio_tagger"]["units_tagged"] = tagged_count
        job.metadata["folio_tagger"]["entity_ruler_tags"] = ruler_tag_count
        logger.info(
            "FOLIO tagger: %d/%d units tagged (%d deterministic entity_ruler "
            "tags, deterministic_iri_path=%s)",
            tagged_count,
            len(job.units),
            ruler_tag_count,
            job.metadata["folio_tagger"]["deterministic_iri_path"],
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
                iri = getattr(match, "entity_id", "") or ""
                surface = getattr(match, "text", None) or str(match)
                # Enrich label/branch from the deterministic IRI so tags carry
                # the canonical FOLIO label (not the matched surface form) and
                # a branch for RUB-EXTRACT-02/03 judging. Cheap: FolioService
                # get_concept is in-memory over the loaded ontology.
                label = surface
                branch = ""
                if iri and folio_service is not None:
                    try:
                        concept = folio_service.get_concept(iri)
                        if concept is not None:
                            label = (
                                getattr(concept, "preferred_label", "")
                                or getattr(concept, "folio_pref_label", "")
                                or surface
                            )
                            branch = getattr(concept, "branch", "") or ""
                    except Exception:
                        logger.debug(
                            "get_concept enrichment failed for %s", iri, exc_info=True
                        )
                concepts.append({
                    "iri": iri,
                    "label": label,
                    "concept_text": surface,
                    "confidence": 0.72,  # default entity ruler confidence
                    "branch": branch,
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

    # A resolved concept must actually carry a label matching the requested
    # one. Judged run uat_ta_ch01_v3 showed search_by_label at 0.6 binding
    # invented LLM labels to unrelated IRIs ("skills"→Kiribati, "ADR"→American
    # Depositary Receipt, "Court Appointed Neutrals"→Web Search Portals
    # Industry): 1,271/1,337 LLM-path tags (95%) were label↔IRI mismatches.
    # We now verify the candidate concept's own labels against the requested
    # label with rapidfuzz and reject below this floor — unresolvable labels
    # route to proposed_class instead of a wrong IRI (RUB-EXTRACT-01/04).
    _LABEL_IRI_VERIFY_THRESHOLD = 85.0

    def _reconciled_to_tags(
        self,
        reconciled: list[ReconciledConcept],
        folio_service: Any,
    ) -> list[ConceptTag]:
        """Convert reconciled concepts to ConceptTag objects.

        IRI resolution: if the reconciled concept has no IRI (LLM path), try
        ``folio_service.search_by_label(rc.label)`` — but only accept a match
        whose OWN labels genuinely correspond to the requested label
        (rapidfuzz >= ``_LABEL_IRI_VERIFY_THRESHOLD``). Deterministic paths
        (entity_ruler) and index-backed paths (semantic) already carry
        canonical FOLIO labels and are not second-guessed here.

        If resolution fails or verification rejects the match, the tag retains
        ``iri=''`` AND its ``extraction_path`` is rewritten to
        ``'proposed_class'`` so downstream consumers (proposed_classes.json,
        OWL exporter, Ecosystem Loop) route it as a proposal — never a
        force-mapped wrong IRI. See UAT Issue I-1 and the uat_ta_ch01_v3
        judged run (Dimension A collapse) for the bugs this fixes.
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
            branch = rc.branch
            if not iri and rc.label and folio_service is not None:
                try:
                    results = folio_service.search_by_label(rc.label)
                    if results:
                        top_match, top_score = results[0]
                        if top_score >= self._FOLIO_LABEL_RESOLUTION_THRESHOLD and (
                            self._label_matches_concept(rc.label, top_match)
                        ):
                            iri = getattr(top_match, "iri", "") or ""
                            resolved_branch = getattr(top_match, "branch", "")
                            if not branch and isinstance(resolved_branch, str):
                                branch = resolved_branch
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
                branch=branch,
            )
            tags.append(tag)

        return tags

    @classmethod
    def _label_matches_concept(cls, label: str, concept: Any) -> bool:
        """True iff ``concept``'s own labels genuinely correspond to ``label``.

        Guards against search_by_label fuzzy false-friends: the accepted
        concept must have a preferred/alternative label that rapidfuzz-matches
        the requested label at >= ``_LABEL_IRI_VERIFY_THRESHOLD`` (token-order
        insensitive, case-insensitive). Cheap, deterministic, in-memory.
        """
        try:
            from rapidfuzz import fuzz
        except ImportError:  # rapidfuzz is a declared bridge dep; be safe
            return True

        wanted = (label or "").strip().lower()
        if not wanted:
            return False

        candidates: list[str] = []
        for attr in ("preferred_label", "folio_pref_label", "hidden_label"):
            v = getattr(concept, attr, "") or ""
            if v:
                candidates.append(v)
        alts = getattr(concept, "alternative_labels", None) or []
        candidates.extend(a for a in alts if a)

        best = 0.0
        for cand in candidates:
            cand_l = cand.lower()
            # max of token-sort (word-order variants) and partial-ratio
            # (morphological/stem variants, e.g. "cross-examine" vs
            # "cross-examination"). partial_ratio rescues genuine noun/verb
            # forms while the 85 floor still rejects lexically-distant
            # false-friends (measured: true variants >=96, false-friends <=63).
            score = max(
                fuzz.token_sort_ratio(wanted, cand_l),
                fuzz.partial_ratio(wanted, cand_l),
            )
            if score > best:
                best = score
                if best >= cls._LABEL_IRI_VERIFY_THRESHOLD:
                    return True
        logger.debug(
            "label-IRI verification rejected %r (best label score %.0f < %.0f)",
            label,
            best,
            cls._LABEL_IRI_VERIFY_THRESHOLD,
        )
        return False

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

    def _get_entity_ruler(
        self, folio_service: Any
    ) -> tuple[Any, str, str]:
        """Build the deterministic FOLIO entity ruler from the bridge.

        Returns ``(matcher_or_None, status, reason)`` where ``status`` is
        ``"active"`` or ``"degraded"``.

        Failure is LOUD, never silent: if ``settings.require_deterministic_iri``
        is set (default True) any failure re-raises so the run aborts with a
        clear error, rather than emitting plausible-but-wrong LLM IRIs. When
        disabled, the failure is logged at ERROR level and reported via the
        returned status so it lands in output metadata.
        """
        from folio_insights.config import get_settings

        require = get_settings().require_deterministic_iri
        try:
            from folio_insights.services.bridge.folio_bridge import get_entity_ruler

            RulerClass = get_entity_ruler()
            ruler = RulerClass()
            if folio_service is None:
                reason = "FolioService unavailable — no labels to load"
                if require:
                    raise RuntimeError(reason)
                return None, "degraded", reason
            labels = folio_service.get_all_labels()
            if not labels:
                reason = "FolioService.get_all_labels() returned no labels"
                if require:
                    raise RuntimeError(reason)
                return None, "degraded", reason
            ruler.load_patterns(labels)
            logger.info(
                "Deterministic FOLIO entity ruler loaded with %d labels", len(labels)
            )
            return ruler, "active", ""
        except Exception as exc:
            if require:
                # Fail loud. A broken deterministic path must not silently
                # degrade to LLM guessing (docs/solutions/
                # sys-path-bridge-staleness.md). Set
                # FOLIO_INSIGHTS_REQUIRE_DETERMINISTIC_IRI=false to override.
                logger.error(
                    "Deterministic FOLIO IRI path failed to initialize and "
                    "require_deterministic_iri is set — aborting.",
                    exc_info=True,
                )
                raise
            logger.error(
                "Deterministic FOLIO entity ruler unavailable — DEGRADED mode",
                exc_info=True,
            )
            return None, "degraded", f"{type(exc).__name__}: {exc}"

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
