"""Four-path reconciliation bridge extending folio-enrich's two-path Reconciler.

Integrates all four extraction paths:
  1. EntityRuler (Aho-Corasick pattern matching)
  2. LLM concept identification
  3. Semantic (embedding similarity search)
  4. Heading Context (document structure)

The base two-path reconciliation (EntityRuler + LLM) is proven and
untouched. This bridge adds semantic and heading context on top.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ReconciledConcept(BaseModel):
    """A FOLIO concept reconciled across up to four extraction paths."""

    iri: str
    label: str
    confidence: float
    contributing_paths: list[str] = Field(default_factory=list)
    branch: str = ""


class FourPathReconciler:
    """Extend folio-enrich's Reconciler from 2-path to 4-path.

    Wraps the imported Reconciler and integrates semantic + heading
    context paths without modifying the base logic.
    """

    def __init__(self, base_reconciler: Any = None) -> None:
        self._base_reconciler = base_reconciler

    def reconcile(
        self,
        ruler_concepts: list[dict[str, Any]],
        llm_concepts: list[dict[str, Any]],
        semantic_concepts: list[dict[str, Any]],
        heading_concepts: list[dict[str, Any]],
    ) -> list[ReconciledConcept]:
        """Reconcile concepts from all four extraction paths.

        1. Run base 2-path reconciliation (EntityRuler + LLM) -- proven, don't touch
        2. Integrate semantic path: boost matching, add new
        3. Integrate heading context: boost only, or add new suggestions
        4. Each final concept records which paths contributed

        Args:
            ruler_concepts: EntityRuler matches as dicts with iri, label, confidence.
            llm_concepts: LLM-identified concepts as dicts.
            semantic_concepts: Embedding similarity matches as dicts.
            heading_concepts: Document-structure heading matches as dicts.

        Returns:
            List of ReconciledConcept with contributing_paths recorded.
        """
        # Build initial result set from base reconciliation
        base_results = self._run_base_reconciliation(ruler_concepts, llm_concepts)

        # Index base results by IRI for fast lookup
        by_iri: dict[str, ReconciledConcept] = {r.iri: r for r in base_results if r.iri}
        by_label: dict[str, ReconciledConcept] = {
            r.label.lower(): r for r in base_results if r.label
        }

        # Integrate semantic path
        for sc in semantic_concepts:
            iri = sc.get("iri", "")
            label = sc.get("label", "")
            confidence = sc.get("confidence", 0.0)
            branch = sc.get("branch", "")

            matched = by_iri.get(iri) or by_label.get(label.lower())
            if matched:
                # Boost existing concept confidence
                matched.confidence = min(1.0, matched.confidence + 0.1)
                if "semantic" not in matched.contributing_paths:
                    matched.contributing_paths.append("semantic")
            else:
                # Add new concept from semantic path
                new_rc = ReconciledConcept(
                    iri=iri,
                    label=label,
                    confidence=confidence,
                    contributing_paths=["semantic"],
                    branch=branch,
                )
                base_results.append(new_rc)
                if iri:
                    by_iri[iri] = new_rc
                if label:
                    by_label[label.lower()] = new_rc

        # Integrate heading context (never override, only boost or suggest)
        for hc in heading_concepts:
            iri = hc.get("iri", "")
            label = hc.get("label", "")
            confidence = hc.get("confidence", 0.0)
            branch = hc.get("branch", "")

            matched = by_iri.get(iri) or by_label.get(label.lower())
            if matched:
                # Heading context boosts confidence of matching concepts
                matched.confidence = min(1.0, matched.confidence + 0.05)
                if "heading_context" not in matched.contributing_paths:
                    matched.contributing_paths.append("heading_context")
            else:
                # Add as new suggestion from heading context
                new_rc = ReconciledConcept(
                    iri=iri,
                    label=label,
                    confidence=confidence,
                    contributing_paths=["heading_context"],
                    branch=branch,
                )
                base_results.append(new_rc)
                if iri:
                    by_iri[iri] = new_rc
                if label:
                    by_label[label.lower()] = new_rc

        return base_results

    def _run_base_reconciliation(
        self,
        ruler_concepts: list[dict[str, Any]],
        llm_concepts: list[dict[str, Any]],
    ) -> list[ReconciledConcept]:
        """Run folio-enrich's base 2-path reconciliation.

        If the base reconciler is available, convert to ConceptMatch objects
        and run it. Otherwise, do a simple merge.
        """
        if self._base_reconciler is not None:
            try:
                return self._reconcile_with_base(ruler_concepts, llm_concepts)
            except Exception:
                logger.warning(
                    "Base reconciler failed; falling back to simple merge",
                    exc_info=True,
                )

        # Simple merge fallback
        return self._simple_merge(ruler_concepts, llm_concepts)

    def _reconcile_with_base(
        self,
        ruler_concepts: list[dict[str, Any]],
        llm_concepts: list[dict[str, Any]],
    ) -> list[ReconciledConcept]:
        """Use the imported base Reconciler for 2-path reconciliation."""
        from folio_insights.services.bridge.folio_bridge import _ensure_folio_enrich_path

        _ensure_folio_enrich_path()
        from app.models.annotation import ConceptMatch

        # Convert dicts to ConceptMatch objects
        ruler_cm = [ConceptMatch(**c) for c in ruler_concepts]
        llm_cm = [ConceptMatch(**c) for c in llm_concepts]

        results = self._base_reconciler.reconcile_with_embedding_triage(ruler_cm, llm_cm)

        reconciled: list[ReconciledConcept] = []
        for r in results:
            paths = []
            cat = r.category
            if "both_agree" in cat:
                paths = ["entity_ruler", "llm"]
            elif "ruler_only" in cat:
                paths = ["entity_ruler"]
            elif "llm_only" in cat:
                paths = ["llm"]
            elif "conflict_resolved" in cat:
                paths = ["entity_ruler", "llm"]

            reconciled.append(
                ReconciledConcept(
                    iri=r.concept.folio_iri or "",
                    label=r.concept.folio_label or r.concept.concept_text,
                    confidence=r.concept.confidence,
                    contributing_paths=paths,
                    branch=(r.concept.branches[0] if r.concept.branches else ""),
                )
            )
        return reconciled

    def _simple_merge(
        self,
        ruler_concepts: list[dict[str, Any]],
        llm_concepts: list[dict[str, Any]],
    ) -> list[ReconciledConcept]:
        """Simple merge when base reconciler is not available."""
        seen_iris: set[str] = set()
        results: list[ReconciledConcept] = []

        for c in ruler_concepts:
            iri = c.get("iri", "")
            rc = ReconciledConcept(
                iri=iri,
                label=c.get("label", c.get("concept_text", "")),
                confidence=c.get("confidence", 0.5),
                contributing_paths=["entity_ruler"],
                branch=c.get("branch", ""),
            )
            results.append(rc)
            if iri:
                seen_iris.add(iri)

        for c in llm_concepts:
            iri = c.get("iri", "")
            if iri and iri in seen_iris:
                # Boost existing
                for r in results:
                    if r.iri == iri:
                        r.confidence = min(1.0, r.confidence + 0.05)
                        if "llm" not in r.contributing_paths:
                            r.contributing_paths.append("llm")
                        break
            else:
                rc = ReconciledConcept(
                    iri=iri,
                    label=c.get("label", c.get("concept_text", "")),
                    confidence=c.get("confidence", 0.5),
                    contributing_paths=["llm"],
                    branch=c.get("branch", ""),
                )
                results.append(rc)
                if iri:
                    seen_iris.add(iri)

        return results
