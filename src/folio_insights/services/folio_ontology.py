# Vendored from folio-enrich backend/app/services/folio/folio_service.py @ 510a652 (MIT).
# Also vendors the FOLIO-path constants it reads from folio-enrich
# backend/app/services/folio/branch_config.py, backend/app/services/folio/match_tier.py,
# backend/app/services/ontology/spec.py (FOLIO_SPEC) and
# backend/app/services/folio/owl_cache.py (get_owl_content_hash) @ 510a652 (MIT).
"""In-repo FOLIO ontology read service.

Replaces the sys.path bridge to folio-enrich's
``app.services.folio.folio_service.FolioService``. It is a narrowed copy of that
class restricted to the FOLIO ontology and to the methods folio-insights calls
(``search_by_label``, ``get_concept``, ``get_all_labels``, plus the small count
and prefix helpers): ``folio_tagger.py``, ``heading_context.py``, discovery
``folio_mapping.py`` and ``hierarchy_construction.py``.

What was narrowed, and why the result is equivalent for FOLIO:

* folio-enrich's ``OntologySpec`` / ``OntologyRegistry`` (multi-ontology) is
  replaced by the FOLIO spec's constants below. The registry's FOLIO path builds
  exactly ``FolioService(FOLIO_SPEC)``; ``get_instance()`` here is the same
  per-process singleton.
* Only the FOLIO load path is kept: ``FOLIO(github_repo_branch="main")``. The
  hardened http-ingestion path served the non-FOLIO Canon ontology only.
* The branch map uses folio-python's ``get_folio_branches()`` (enrich's FOLIO
  path, byte-identical); the canonical non-FOLIO branch derivation is dropped.
* ``translation_matching_enabled`` (enrich default ``False``) is a constructor
  argument defaulting to ``False``.
* Lemma keys: identical logic and the identical on-disk cache
  (``~/.folio-enrich/cache/lemmas/labels_<owl-hash>_v1.pkl``), so a box that
  already holds enrich's lemma cache indexes the same lemma keys. Computing new
  lemmas needs spaCy + ``en_core_web_sm``; neither is a folio-insights
  dependency, so without the cache the lemma tier is empty (enrich degrades the
  same way when spaCy is missing).

Parity with the enrich implementation (label index, search results, concept
lookups) is pinned by ``tests/test_bridge_retirement_parity.py``.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---- FOLIO spec constants (enrich ontology/spec.py FOLIO_SPEC + branch_config.py) ----------

# Bump when the lemma rules or denylist change (kept equal to enrich's LEMMA_VERSION so the
# shared disk cache key matches).
LEMMA_VERSION = "1"
_LEMMA_CACHE_DIR = Path.home() / ".folio-enrich" / "cache" / "lemmas"

_GITHUB_REPO_BRANCH = "main"

# Branch key (folio-python FOLIOTypes name) -> display name.
_BRANCH_DISPLAY_NAMES: dict[str, str] = {
    "ACTOR_PLAYER": "Actor / Player",
    "AREA_OF_LAW": "Area of Law",
    "ASSET_TYPE": "Asset Type",
    "COMMUNICATION_MODALITY": "Communication Modality",
    "CURRENCY": "Currency",
    "DATA_FORMAT": "Data Format",
    "DOCUMENT_ARTIFACT": "Document / Artifact",
    "DOCUMENT_METADATA": "Document Metadata",
    "ENGAGEMENT_TERMS": "Engagement Terms",
    "EVENT": "Event",
    "FINANCIAL_CONCEPTS": "Financial Concepts and Metrics",
    "FOLIO_TYPE": "FOLIO Type",
    "FORUMS_VENUES": "Forums and Venues",
    "GOVERNMENTAL_BODY": "Governmental Body",
    "INDUSTRY": "Industry",
    "LANGUAGE": "Language",
    "LEGAL_AUTHORITIES": "Legal Authorities",
    "LEGAL_ENTITY": "Legal Entity",
    "LEGAL_USE_CASES": "Legal Use Cases",
    "LOCATION": "Location",
    "MATTER_NARRATIVE": "Matter Narrative",
    "MATTER_NARRATIVE_FORMAT": "Matter Narrative Format",
    "OBJECTIVES": "Objectives",
    "SERVICE": "Service",
    "STANDARDS_COMPATIBILITY": "Standards Compatibility",
    "STATUS": "Status",
    "SYSTEM_IDENTIFIERS": "System Identifiers",
}

EXCLUDED_BRANCHES: frozenset[str] = frozenset({
    "Standards Compatibility",
    "FOLIO Type",
    "ZZZ - SANDBOX: UNDER CONSTRUCTION",
    "Area of Law",
})

# Legal pluralia-tantum / terms of art whose singular has a *different* meaning.
LEMMA_DENYLIST: frozenset[str] = frozenset({
    "damages", "damage", "costs", "cost", "proceedings", "proceeding",
    "goods", "good", "arms", "arm", "premises", "savings", "saving",
    "findings", "finding", "securities", "minutes", "minute",
    "holdings", "holding", "pleadings", "pleading", "articles", "article",
    "data", "datum", "leaves", "leave", "wills", "will", "means",
})

_CONCEPT_EXCLUDE_SUBSTRINGS: tuple[str, ...] = ("DUPE",)  # matched on UPPERCASED label
_CONCEPT_EXCLUDE_PREFIXES: tuple[str, ...] = ("ZZZ:",)  # matched on UPPERCASED label

# ---- match tiers (enrich folio/match_tier.py) ---------------------------------------------

LABEL_TYPE_ORDER: dict[str, int] = {
    "preferred": 0,
    "lemma_preferred": 1,
    "alternative": 2,
    "lemma_alternative": 3,
    "hidden": 4,
    "translation": 5,
}
PRIMARY_LABEL_TYPES: frozenset[str] = frozenset({"preferred", "lemma_preferred"})


def get_branch_display_name(key: str) -> str:
    """Display name for a branch key (e.g. ACTOR_PLAYER -> 'Actor / Player')."""
    return _BRANCH_DISPLAY_NAMES.get(key, key)


def label_type_rank(label_type: str) -> int:
    return LABEL_TYPE_ORDER.get(label_type, 99)


def is_higher_priority(new_type: str, existing_type: str) -> bool:
    return label_type_rank(new_type) < label_type_rank(existing_type)


def lemma_type_for(base_label_type: str) -> str:
    return "lemma_preferred" if base_label_type in PRIMARY_LABEL_TYPES else "lemma_alternative"


def get_owl_content_hash() -> str:
    """SHA-256 (16 hex chars) of folio-python's cached FOLIO OWL, or "" when absent.

    Same file and digest as enrich's ``owl_cache.get_owl_content_hash`` (folio-python's
    github cache key ``alea-institute/FOLIO/main``).
    """
    cache_hash = hashlib.blake2b(b"alea-institute/FOLIO/main").hexdigest()
    cache_file = Path.home() / ".folio" / "cache" / "github" / f"{cache_hash}.owl"
    if not cache_file.exists():
        return ""
    return hashlib.sha256(cache_file.read_bytes()).hexdigest()[:16]


# ---- data classes (enrich folio_service.py) -----------------------------------------------


@dataclass
class FOLIOConcept:
    iri: str
    preferred_label: str
    alternative_labels: list[str]
    definition: str
    branch: str
    parent_iris: list[str]
    folio_pref_label: str = ""
    examples: list[str] | None = None
    notes: list[str] | None = None
    editorial_note: str = ""
    comment: str = ""
    description: str = ""
    source: str = ""
    see_also: list[str] | None = None
    hidden_label: str = ""
    is_defined_by: str = ""
    deprecated: bool = False
    history_note: str = ""
    country: str = ""
    translations: dict[str, str] | None = None


@dataclass
class LabelInfo:
    """A label entry that tracks whether it's a preferred or alternative label."""

    concept: FOLIOConcept
    label_type: str  # "preferred" / "alternative" / "lemma_*" / "hidden" / "translation"
    matched_label: str  # The actual label text that matched


class FolioOntologyService:
    """FOLIO read service over folio-python (label index, search, concept lookup)."""

    _instance: FolioOntologyService | None = None
    _instance_lock = threading.Lock()

    def __init__(self, *, translation_matching_enabled: bool = False, folio: Any = None) -> None:
        self._translation_matching_enabled = translation_matching_enabled
        self._folio = folio
        self._labels_cache: dict[str, LabelInfo] | None = None
        self._branch_map: dict[str, str] | None = None
        self._lemma_map: dict[str, str] | None = None
        if folio is not None:
            self._build_branch_map()

    @classmethod
    def get_instance(cls) -> FolioOntologyService:
        """Process-wide singleton (enrich: ``FolioService.get_instance()`` via its registry)."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Test hook: drop the singleton."""
        with cls._instance_lock:
            cls._instance = None

    # ---- loading ------------------------------------------------------------------------

    def _load_folio(self) -> Any:
        from folio import FOLIO

        return FOLIO(github_repo_branch=_GITHUB_REPO_BRANCH)

    def _get_folio(self) -> Any:
        if self._folio is None:
            self._folio = self._load_folio()
            self._build_branch_map()
            logger.info("Ontology 'folio' loaded with %d concepts", len(self._folio.classes))
        return self._folio

    def _build_branch_map(self) -> None:
        """Map concept IRI -> branch display name via folio-python ``get_folio_branches()``."""
        if self._folio is None:
            return
        self._branch_map = {}
        try:
            branches = self._folio.get_folio_branches()
            for branch_type, concepts in branches.items():
                branch_key = branch_type.name if hasattr(branch_type, "name") else str(branch_type)
                branch_name = get_branch_display_name(branch_key)
                for concept in concepts:
                    if hasattr(concept, "iri"):
                        self._branch_map[concept.iri] = branch_name
        except Exception:
            logger.warning("Failed to build branch map", exc_info=True)

    def _get_branch(self, iri: str, parent_iris: list[str]) -> str:
        """Determine the branch for a concept by checking its IRI and ancestors."""
        if self._branch_map is None:
            return ""
        if iri in self._branch_map:
            return self._branch_map[iri]
        for parent_iri in parent_iris:
            if parent_iri in self._branch_map:
                return self._branch_map[parent_iri]
        try:
            folio = self._get_folio()
            parents = folio.get_parents(iri)
            for parent in parents:
                if hasattr(parent, "iri") and parent.iri in self._branch_map:
                    self._branch_map[iri] = self._branch_map[parent.iri]
                    return self._branch_map[parent.iri]
        except Exception:
            pass
        return ""

    # ---- search / lookup ------------------------------------------------------------------

    def search_by_label(self, label: str, top_k: int = 5) -> list[tuple[FOLIOConcept, float]]:
        folio = self._get_folio()
        try:
            results = folio.search_by_label(label, include_alt_labels=True)
        except Exception:
            logger.warning("search_by_label failed for '%s'", label, exc_info=True)
            return []
        output = []
        for concept, score in results[:top_k]:
            output.append((self._to_folio_concept(concept), score))
        return output

    def search_by_prefix(self, prefix: str, top_k: int = 10) -> list[FOLIOConcept]:
        folio = self._get_folio()
        try:
            results = folio.search_by_prefix(prefix)
            return [self._to_folio_concept(c) for c, _ in results[:top_k]]
        except Exception:
            logger.warning("search_by_prefix failed for '%s'", prefix, exc_info=True)
            return []

    def get_concept(self, iri: str) -> FOLIOConcept | None:
        folio = self._get_folio()
        try:
            concept = folio[iri]
            return self._to_folio_concept(concept)
        except Exception:
            return None

    def get_concept_count(self) -> int:
        return len(self._get_folio().classes)

    def get_label_count(self) -> int:
        return len(self.get_all_labels())

    # ---- label index ----------------------------------------------------------------------

    def _is_excluded_concept(self, fc: FOLIOConcept) -> bool:
        """Excluded branches, deprecated concepts, and DUPE/ZZZ: editorial markers."""
        if fc.branch in EXCLUDED_BRANCHES:
            return True
        if fc.deprecated:
            return True
        up = (fc.preferred_label or "").upper()
        if any(sub in up for sub in _CONCEPT_EXCLUDE_SUBSTRINGS):
            return True
        if any(up.startswith(pre) for pre in _CONCEPT_EXCLUDE_PREFIXES):
            return True
        return False

    @staticmethod
    def _primary_and_alt_labels(fc: FOLIOConcept):
        """Yield (raw_label, base_label_type) for the labels eligible for lemma keys."""
        if fc.preferred_label:
            yield fc.preferred_label, "preferred"
        if fc.folio_pref_label:
            yield fc.folio_pref_label, "preferred"
        for alt in fc.alternative_labels:
            if alt:
                yield alt, "alternative"

    def _lemma_cache_path(self) -> Path:
        h = get_owl_content_hash() or "nohash"
        return _LEMMA_CACHE_DIR / f"labels_{h}_v{LEMMA_VERSION}.pkl"

    def _load_lemma_cache(self) -> dict[str, str] | None:
        try:
            path = self._lemma_cache_path()
            if path.exists():
                import pickle

                with open(path, "rb") as f:
                    data = pickle.load(f)  # noqa: S301 -- trusted local cache
                if isinstance(data, dict):
                    logger.info("Loaded %d label lemmas from cache", len(data))
                    return data
        except Exception:
            logger.debug("Lemma cache load failed", exc_info=True)
        return None

    def _save_lemma_cache(self, lemma_map: dict[str, str]) -> None:
        try:
            path = self._lemma_cache_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            import pickle

            with open(path, "wb") as f:
                pickle.dump(lemma_map, f)
        except Exception:
            logger.debug("Lemma cache save failed", exc_info=True)

    def _compute_label_lemmas(self) -> dict[str, str]:
        """Map single-word label (lowercased) -> its lemma, for singular/plural reachability."""
        if self._lemma_map is not None:
            return self._lemma_map

        cached = self._load_lemma_cache()
        if cached is not None:
            self._lemma_map = cached
            return cached

        folio = self._get_folio()
        candidates: set[str] = set()
        for concept in folio.classes:
            try:
                fc = self._to_folio_concept(concept)
                if self._is_excluded_concept(fc):
                    continue
                for raw, _ in self._primary_and_alt_labels(fc):
                    low = raw.lower()
                    if " " in low or len(low) <= 3 or low in LEMMA_DENYLIST:
                        continue
                    candidates.add(low)
            except Exception:
                continue

        lemma_map: dict[str, str] = {}
        try:
            import spacy

            nlp = spacy.load("en_core_web_sm", disable=["ner", "parser"])
            if not {"tagger", "attribute_ruler"} <= set(nlp.pipe_names):
                logger.warning(
                    "spaCy pipeline missing tagger/attribute_ruler (%s); "
                    "skipping lemma normalization", nlp.pipe_names,
                )
                self._lemma_map = {}
                return {}
            for doc in nlp.pipe(sorted(candidates), batch_size=512):
                original = doc.text.lower()
                lemma = doc[0].lemma_.lower() if len(doc) else original
                if lemma != original and len(lemma) > 2 and lemma not in LEMMA_DENYLIST:
                    lemma_map[original] = lemma
        except Exception:
            logger.warning(
                "Lemma normalization failed; proceeding without lemma keys", exc_info=True
            )
            self._lemma_map = {}
            return {}

        self._lemma_map = lemma_map
        self._save_lemma_cache(lemma_map)
        logger.info("Computed %d label lemmas for reachability", len(lemma_map))
        return lemma_map

    @staticmethod
    def _maybe_set(labels: dict[str, LabelInfo], key: str, fc: FOLIOConcept,
                   label_type: str, matched_label: str) -> None:
        existing = labels.get(key)
        if existing is None or is_higher_priority(label_type, existing.label_type):
            labels[key] = LabelInfo(concept=fc, label_type=label_type, matched_label=matched_label)

    def get_all_labels(self) -> dict[str, LabelInfo]:
        """All concept labels (lowercased) -> LabelInfo.

        Priority (highest first): preferred > lemma_preferred > alternative >
        lemma_alternative > hidden > translation.
        """
        if self._labels_cache is not None:
            return self._labels_cache

        folio = self._get_folio()
        lemma_map = self._compute_label_lemmas()
        labels: dict[str, LabelInfo] = {}

        for concept in folio.classes:
            try:
                fc = self._to_folio_concept(concept)
                if self._is_excluded_concept(fc):
                    continue

                pref = fc.preferred_label
                if pref:
                    self._maybe_set(labels, pref.lower(), fc, "preferred", pref)
                if fc.folio_pref_label:
                    self._maybe_set(
                        labels, fc.folio_pref_label.lower(), fc, "preferred", fc.folio_pref_label
                    )
                for alt in fc.alternative_labels:
                    if alt:
                        self._maybe_set(labels, alt.lower(), fc, "alternative", alt)
                if fc.hidden_label:
                    self._maybe_set(labels, fc.hidden_label.lower(), fc, "hidden", fc.hidden_label)
                if self._translation_matching_enabled and fc.translations:
                    pref_lower = pref.lower() if pref else ""
                    for _lang, trans_text in fc.translations.items():
                        if trans_text and trans_text.lower() != pref_lower:
                            self._maybe_set(
                                labels, trans_text.lower(), fc, "translation", trans_text
                            )

                for raw, base_type in self._primary_and_alt_labels(fc):
                    lemma = lemma_map.get(raw.lower())
                    if lemma:
                        self._maybe_set(labels, lemma, fc, lemma_type_for(base_type), raw)
            except Exception:
                continue

        self._labels_cache = labels
        logger.info("Indexed %d FOLIO labels", len(labels))
        return labels

    # ---- conversion -----------------------------------------------------------------------

    def _to_folio_concept(self, concept: Any) -> FOLIOConcept:
        pref_label = (
            getattr(concept, "label", None) or getattr(concept, "preferred_label", "") or ""
        )
        alt_labels = getattr(concept, "alternative_labels", []) or []
        definition = getattr(concept, "definition", "") or ""
        iri = getattr(concept, "iri", "") or ""
        parent_iris = getattr(concept, "sub_class_of", []) or []

        examples = getattr(concept, "examples", []) or []
        notes = getattr(concept, "notes", []) or []
        editorial_note = getattr(concept, "editorial_note", "") or ""
        comment = getattr(concept, "comment", "") or ""
        description = getattr(concept, "description", "") or ""
        source = getattr(concept, "source", "") or ""
        see_also = getattr(concept, "see_also", []) or []
        hidden_label = getattr(concept, "hidden_label", "") or ""
        is_defined_by = getattr(concept, "is_defined_by", "") or ""
        deprecated = bool(getattr(concept, "deprecated", False))
        history_note = getattr(concept, "history_note", "") or ""
        country = getattr(concept, "country", "") or ""
        raw_translations = getattr(concept, "translations", {}) or {}
        translations = dict(raw_translations) if raw_translations else None

        branch = self._get_branch(iri, list(parent_iris))

        # FOLIO skos:prefLabel — only store when it exists and differs from rdfs:label
        folio_pref = getattr(concept, "preferred_label", "") or ""
        folio_pref_label = (
            folio_pref if folio_pref and folio_pref.lower() != pref_label.lower() else ""
        )

        return FOLIOConcept(
            iri=iri,
            preferred_label=pref_label,
            alternative_labels=list(alt_labels),
            definition=definition,
            branch=branch,
            parent_iris=list(parent_iris),
            folio_pref_label=folio_pref_label,
            examples=list(examples) if examples else None,
            notes=list(notes) if notes else None,
            editorial_note=editorial_note,
            comment=comment,
            description=description,
            source=source,
            see_also=list(see_also) if see_also else None,
            hidden_label=hidden_label,
            is_defined_by=is_defined_by,
            deprecated=deprecated,
            history_note=history_note,
            country=country,
            translations=translations,
        )
