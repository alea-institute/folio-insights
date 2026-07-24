"""FOLIO tagger pipeline stage: four-path concept extraction, reconciliation, and judge.

Four extraction paths run independently on each KnowledgeUnit:
  1. EntityRuler (Aho-Corasick pattern matching against FOLIO labels)
  2. LLM Concept Identification (structured LLM call)
  3. Semantic (embedding similarity search against FOLIO concept embeddings)
  4. Heading Context (document structure -> FOLIO concept mapping)

Results are reconciled via FourPathReconciler, resolved to IRIs, and vetoed by the deterministic
gates (place/agency + alias blocklist). Every surviving **non-ruler** tag then goes through the
LLM-as-judge stage (``folio_resolve.build_judge_prompt`` / ``parse_judge_json``) with the corpus
**domain prior** injected (this corpus is a litigation practice treatise -> multi-tag
Litigation / Trial Practice) and each candidate's FOLIO **definition** shown to the judge (the
charge->Encumbrance blind-spot fix). The gates remain vetoes: the judge only ever sees post-gate
tags and can lower/reject but never resurrect a gated tag. Per-tag judge verdicts are recorded as
``ScoreCalibration`` samples.

Metadata / front-matter units are **not** insights, so they never emit insight tags — but they are
mapped to FOLIO and their mappings are folded into the domain prior as context for the body units
that follow (Damien's metadata-as-signal directive, d3c44e2a).
"""

from __future__ import annotations

import json
import logging
import os
from collections import Counter
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

# This corpus is a litigation practice treatise. Damien's multi-tag prior (unit 4b06a90c / finding
# 002): a single corpus carries MULTIPLE subject tags, all of which flow into every judge call so
# an ambiguous term ("Defenses", "charge") disambiguates in a litigation context. These base
# subjects are always active; metadata-as-signal harvest (below) appends corpus-specific ones.
BASE_PRIOR_SUBJECTS: tuple[str, ...] = ("Litigation", "Trial Practice")

# Structured-output schema for the judge (mirrors folio_resolve.build_judge_prompt's contract).
_JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "judged": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "iri_hash": {"type": "string"},
                    "adjusted_score": {"type": "number"},
                    "verdict": {"type": "string"},
                    "reasoning": {"type": "string"},
                },
            },
        }
    },
}

# Judge verdict -> calibration verdict (ScoreCalibration's correct/weak/wrong dataset).
_VERDICT_TO_CALIBRATION = {
    "confirmed": "correct",
    "boosted": "correct",
    "penalized": "weak",
    "rejected": "wrong",
}


def _judge_enabled() -> bool:
    """Whether the LLM-judge stage runs. Off unless ``FOLIO_JUDGE_ENABLED`` is truthy.

    Kept opt-in so the unit-test suite (which drives the deterministic paths with fakes) never
    reaches for a real provider; the chapter-run harness sets it to ``1``.
    """
    return os.environ.get("FOLIO_JUDGE_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def _load_alias_blocklist() -> Any:
    """Load the shipped seed alias blocklist (Action != Auction + agency homonyms).

    The seed now ships inside the pinned ``folio_resolve`` package as recorded Ch01/Ch02 verdicts
    keyed on **real** FOLIO IRIs (the old placeholder used a synthetic ``EXAMPLE-Auction`` IRI that
    could never match live resolution — the Ch02 proving run's defect #3). Never raises.
    """
    from folio_resolve import load_seed_blocklist

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
    # owned by the pinned ``folio_resolve.LabelResolver``. The old class-local ``0.6`` bar was a
    # latent scale bug: FolioService.search_by_label returns a 0-100 score, so 0.6 accepted every
    # top match and generic terms mis-mapped to short place/agency labels (the Ch02 proving-run
    # regression). The calibrated bar (92.0) now lives in ``folio_resolve.WHOLE_STRING_THRESHOLD``.

    @property
    def name(self) -> str:
        return "folio_tagger"

    async def execute(self, job: InsightsJob) -> InsightsJob:
        """Two-pass tagging: harvest metadata signal into the prior, then tag + judge body units."""
        if not job.units:
            logger.info("No units to tag")
            return job

        # Initialize services
        folio_service = self._get_folio_service()
        embedding_service = self._get_embedding_service()
        aho_matcher = self._get_aho_matcher(folio_service)
        heading_extractor = HeadingContextExtractor(folio_service)
        reconciler = self._get_reconciler(embedding_service)

        # ---- Pass A: metadata-as-signal (Damien's d3c44e2a directive) --------------------------
        # Metadata / front-matter units are a MEANS to insights, not insights. They emit no insight
        # tags, but we DO map them to FOLIO and fold those mappings into the corpus domain prior so
        # the judge on the body units that follow is context-aware.
        prior = self._build_domain_prior(job, folio_service, aho_matcher)
        prior_context = prior.as_judge_context()
        job.metadata.setdefault("folio_resolve", {})["domain_prior"] = {
            "corpus": prior.corpus_name,
            "active_subjects": [t.label for t in prior.active_tags()],
            "judge_context": prior_context,
        }
        logger.info("Domain prior (%s): %s", prior.corpus_name, prior_context)

        # ---- Pass B: body units get the full pipeline (paths -> reconcile -> gates -> judge) -----
        for unit in job.units:
            try:
                if not self._is_taggable_source(unit):
                    # Metadata/front-matter: no insight tags (already harvested in Pass A).
                    unit.folio_tags = []
                    record_lineage(
                        unit,
                        stage="folio_tagger",
                        action="skip",
                        detail="metadata-as-signal: mapped to prior, not emitted as insight",
                    )
                    continue
                await self._tag_unit(
                    unit,
                    folio_service=folio_service,
                    embedding_service=embedding_service,
                    aho_matcher=aho_matcher,
                    heading_extractor=heading_extractor,
                    reconciler=reconciler,
                    prior_context=prior_context,
                )
            except Exception:
                logger.warning(
                    "Failed to tag unit %s; skipping", unit.id, exc_info=True
                )

        self._flush_calibration(job)
        tagged_count = sum(1 for u in job.units if u.folio_tags)
        logger.info(
            "FOLIO tagger: %d/%d units tagged (judge_enabled=%s, %d judge calls)",
            tagged_count, len(job.units), _judge_enabled(), self._judge_call_count,
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
        prior_context: str = "",
    ) -> None:
        """Run all four paths, reconcile, gate, and judge for a single body unit.

        Metadata/front-matter exclusion happens upstream in ``execute`` (Pass A) so this method
        only ever sees taggable body/heading units.
        """
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

        # Resolve to FOLIO IRIs, decompose, and run the deterministic gates.
        tags = self._reconciled_to_tags(reconciled, folio_service)

        # Judge stage: every surviving non-ruler tag is adjudicated by the LLM judge with the
        # domain prior injected and each candidate's FOLIO definition shown. The gates already ran;
        # the judge can lower/reject but never resurrect a gated tag (it only sees post-gate tags).
        if _judge_enabled():
            tags = await self._run_judge(
                unit, tags, folio_service=folio_service, prior_context=prior_context
            )

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

    # ---- Domain prior (metadata-as-signal) ---------------------------------------------------

    def _build_domain_prior(
        self, job: InsightsJob, folio_service: Any, aho_matcher: Any
    ) -> Any:
        """Build the corpus domain prior: base litigation subjects + harvested metadata mappings.

        Base subjects (Litigation / Trial Practice) are always active. Metadata / front-matter
        units are then mapped to FOLIO deterministically (entity-ruler exact matches, no LLM) and
        the most frequent mappings are added to the prior as active context (Damien's d3c44e2a
        metadata-as-signal directive). Metadata units themselves emit no insight tags.
        """
        from folio_resolve import DomainPrior

        # Base multi-tag prior, resolved to real IRIs where possible (label-only is a fine fallback
        # since the judge consumes only the rendered labels via ``as_judge_context``).
        subjects: list[tuple[str, str]] = []
        for label in BASE_PRIOR_SUBJECTS:
            iri = self._first_iri_for_label(label, folio_service)
            subjects.append((iri, label))
        prior = DomainPrior.from_manifest_subjects(job.corpus_name, subjects)

        # Harvest metadata/front-matter mappings into a frequency counter.
        harvested: Counter[tuple[str, str]] = Counter()
        for unit in job.units:
            if self._is_taggable_source(unit):
                continue
            mappings = self._ruler_mappings(unit.text, aho_matcher)
            for iri, label in mappings:
                harvested[(iri, label)] += 1
            record_lineage(
                unit,
                stage="folio_tagger",
                action="metadata-signal",
                detail=f"harvested {len(mappings)} FOLIO mapping(s) into prior",
            )

        # Add the strongest distinct metadata mappings (cap keeps the prior focused, not noisy).
        # Noise filter (Ch04 finding): single-occurrence one-word ruler fragments ("non", "rule")
        # are surface accidents of front-matter text, not subjects — require either a repeated
        # mention or a multi-word label before a mapping earns a place in the prior.
        harvested_records: list[dict[str, object]] = []
        for (iri, label), count in harvested.most_common(12):
            if not (iri and label) or len(label) < 4:
                continue
            if count < 2 and len(label.split()) < 2:
                continue
            if len(harvested_records) >= 8:
                break
            prior.add(iri, label, source="metadata")
            harvested_records.append({"iri": iri, "label": label, "count": count})
        job.metadata.setdefault("folio_resolve", {})["metadata_mappings"] = harvested_records
        return prior

    def _ruler_mappings(self, text: str, aho_matcher: Any) -> list[tuple[str, str]]:
        """Deterministic FOLIO mappings for a metadata unit via entity-ruler exact matches."""
        if aho_matcher is None or not text:
            return []
        out: list[tuple[str, str]] = []
        seen: set[str] = set()
        try:
            for match in aho_matcher.find_matches(text):
                iri = getattr(match, "entity_id", "") or ""
                label = getattr(match, "text", "") or ""
                if iri and iri not in seen:
                    seen.add(iri)
                    out.append((iri, label))
        except Exception:
            logger.warning("metadata ruler mapping failed", exc_info=True)
        return out

    def _first_iri_for_label(self, label: str, folio_service: Any) -> str:
        if folio_service is None or not label:
            return ""
        try:
            results = folio_service.search_by_label(label)
            if results:
                obj, score = results[0]
                if float(score) >= 92.0:
                    return getattr(obj, "iri", "") or ""
        except Exception:
            logger.warning("prior label resolution failed for %r", label, exc_info=True)
        return ""

    # ---- LLM judge stage ---------------------------------------------------------------------

    async def _run_judge(
        self,
        unit: KnowledgeUnit,
        tags: list[ConceptTag],
        *,
        folio_service: Any,
        prior_context: str,
    ) -> list[ConceptTag]:
        """Adjudicate every non-ruler resolved tag with the domain-prior + definition-level judge.

        One batched LLM call per unit validates all its non-ruler candidates at once. Entity-ruler
        tags (exact Aho-Corasick matches) and proposed-class tags (no IRI) bypass the judge. The
        judge sees each candidate's FOLIO **definition** (the charge->Encumbrance blind-spot fix)
        and the corpus **domain prior** as document-type context. Verdicts are enforced by
        ``folio_resolve.parse_judge_json`` (rejected -> drop; confirmed clamped ±5; boost capped
        +25) and recorded as calibration samples.
        """
        from folio_resolve import build_judge_prompt, parse_judge_json

        candidates = [t for t in tags if t.iri and t.extraction_path != "entity_ruler"]
        if not candidates:
            return tags

        id_map: dict[str, ConceptTag] = {}
        cand_dicts: list[dict[str, object]] = []
        ranked: dict[str, float] = {}
        for i, tag in enumerate(candidates):
            cid = f"c{i}"  # short, echo-safe id (full IRIs get mangled by the LLM)
            id_map[cid] = tag
            # Normalize mixed-scale confidences: most paths deliver 0-1, but a few deliver 0-100
            # (a seam the Ch04 calibration data exposed — one 90.0-scale tag became a 9000 judge
            # score, whose "confirmed ±5" clamp then produced a nonsense 8995).
            conf = tag.confidence if tag.confidence <= 1.0 else tag.confidence / 100.0
            original = round(max(0.0, min(1.0, conf)) * 100.0, 1)
            ranked[cid] = original
            cand_dicts.append({
                "iri": cid,
                "label": tag.label,
                "definition": self._definition_for(tag.iri, folio_service)[:240],
                "score": original,
            })

        system, user = build_judge_prompt(unit.text, cand_dicts, document_type=prior_context)
        try:
            provider = self._get_judge_provider()
            result = await provider.structured(
                f"{system}\n\n{user}", schema=_JUDGE_SCHEMA, temperature=0
            )
            self._judge_call_count += 1
        except Exception:
            logger.warning("judge call failed for unit %s; keeping pre-judge tags", unit.id, exc_info=True)
            return tags

        judged = {j.iri: j for j in parse_judge_json(json.dumps(result), ranked)}

        kept: list[ConceptTag] = []
        rejected = 0
        for tag in tags:
            cid = next((k for k, v in id_map.items() if v is tag), None)
            if cid is None:
                kept.append(tag)  # ruler / proposed-class tag: not adjudicated
                continue
            verdict = judged.get(cid)
            if verdict is None:
                kept.append(tag)  # judge did not rule on it: keep the gated tag as-is
                continue
            self._record_calibration(ranked[cid], verdict.verdict)
            self._judge_decisions.append({
                "unit_id": unit.id,
                "text": (unit.text or "")[:280],
                "label": tag.label,
                "iri": tag.iri,
                "branch": tag.branch,
                "path": tag.extraction_path,
                "original_score": ranked[cid],
                "verdict": verdict.verdict,
                "adjusted_score": verdict.adjusted_score,
                "reasoning": verdict.reasoning,
            })
            if verdict.verdict == "rejected":
                rejected += 1
                continue
            tag.confidence = max(0.0, min(1.0, verdict.adjusted_score / 100.0))
            kept.append(tag)

        if rejected:
            record_lineage(
                unit,
                stage="folio_tagger",
                action="judge",
                detail=f"judge rejected {rejected}/{len(candidates)} non-ruler candidate(s)",
            )
        return kept

    def _get_judge_provider(self) -> Any:
        provider = getattr(self, "_judge_provider", None)
        if provider is None:
            from folio_insights.services.bridge.llm_bridge import LLMBridge

            provider = LLMBridge().get_llm_for_task("branch_judge")
            self._judge_provider = provider
        return provider

    def _definition_for(self, iri: str, folio_service: Any) -> str:
        """FOLIO definition text for a concept IRI (cached), for the definition-level judge."""
        if not iri or folio_service is None:
            return ""
        cache = self._definition_cache
        if iri in cache:
            return cache[iri]
        definition = ""
        try:
            concept = folio_service.get_concept(iri)
            raw = getattr(concept, "definition", "") or getattr(concept, "description", "") or ""
            definition = raw if isinstance(raw, str) else ""
        except Exception:
            logger.warning("definition lookup failed for iri=%r", iri, exc_info=True)
        cache[iri] = definition
        return definition

    def _record_calibration(self, score: float, verdict: str) -> None:
        band = _VERDICT_TO_CALIBRATION.get(verdict, "weak")
        self._calibration_samples.append((score, band))

    def _flush_calibration(self, job: InsightsJob) -> None:
        """Record judge verdicts as ScoreCalibration samples (job metadata + optional sidecar)."""
        samples = self._calibration_samples
        if not samples:
            return
        from folio_resolve import CalibrationSample, ScoreCalibration

        calib = ScoreCalibration.fit(CalibrationSample(score=s, verdict=v) for s, v in samples)
        verdict_counts = Counter(v for _s, v in samples)
        payload = {
            "sample_count": len(samples),
            "verdict_counts": dict(verdict_counts),
            "weak_band_bounds": list(calib.weak_band_bounds()),
            "samples": [{"score": s, "verdict": v} for s, v in samples],
            "decisions": self._judge_decisions,
            "metadata_mappings": job.metadata.get("folio_resolve", {}).get("metadata_mappings", []),
            "domain_prior": job.metadata.get("folio_resolve", {}).get("domain_prior", {}),
        }
        job.metadata.setdefault("folio_resolve", {})["calibration"] = {
            k: payload[k] for k in ("sample_count", "verdict_counts", "weak_band_bounds")
        }
        out_path = os.environ.get("FOLIO_JUDGE_CALIBRATION_OUT", "").strip()
        if out_path:
            try:
                with open(out_path, "w") as fh:
                    json.dump(payload, fh, indent=2)
            except OSError:
                logger.warning("could not write calibration sidecar to %s", out_path, exc_info=True)

    @property
    def _judge_call_count(self) -> int:
        return getattr(self, "_judge_call_count_store", 0)

    @_judge_call_count.setter
    def _judge_call_count(self, value: int) -> None:
        self._judge_call_count_store = value

    @property
    def _calibration_samples(self) -> list[tuple[float, str]]:
        samples = getattr(self, "_calibration_samples_store", None)
        if samples is None:
            samples = []
            self._calibration_samples_store = samples
        return samples

    @property
    def _judge_decisions(self) -> list[dict[str, Any]]:
        decisions = getattr(self, "_judge_decisions_store", None)
        if decisions is None:
            decisions = []
            self._judge_decisions_store = decisions
        return decisions

    @property
    def _definition_cache(self) -> dict[str, str]:
        cache = getattr(self, "_definition_cache_store", None)
        if cache is None:
            cache = {}
            self._definition_cache_store = cache
        return cache

    def _reconciled_to_tags(
        self,
        reconciled: list[ReconciledConcept],
        folio_service: Any,
    ) -> list[ConceptTag]:
        """Convert reconciled concepts to ConceptTag objects (Ch02 precision-fix path).

        Resolution is delegated to the pinned ``folio_resolve.LabelResolver`` so every consumer
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
            from folio_resolve import LabelResolver

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
        from folio_resolve import PlaceNameGate

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
        from folio_resolve import SourceClassifier

        classifier = getattr(self, "_source_classifier", None)
        if classifier is None:
            classifier = SourceClassifier()
            self._source_classifier = classifier
        section_label = " > ".join(unit.source_section) if unit.source_section else ""
        return bool(classifier.is_taggable(section_label, unit.text or ""))

    @staticmethod
    def _is_place_or_agency(branch: str) -> bool:
        from folio_resolve.gates import _PLACE_BRANCH_MARKERS

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
        """Get the entity ruler backed by the pinned ``folio_resolve.FOLIOEntityRuler``.

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
            from folio_resolve import FOLIOEntityRuler

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
        """Get FourPathReconciler backed by the pinned ``folio_resolve.Reconciler``.

        Migration item #1: replaces the sys.path import of folio-enrich's Reconciler with
        the pinned package. If ``embedding_service`` exposes ``similarity_batch`` the triage
        path is wired; otherwise the deterministic 2-pass reconcile is used.
        """
        try:
            from folio_resolve import Reconciler

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
