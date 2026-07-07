"""Application settings with pydantic-settings and .env support."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Global configuration for folio-insights."""

    # Bridge paths -- folio-insights imports services from sibling repos via
    # a sys.path bridge (see src/folio_insights/services/bridge/).
    # Defaults assume folio-enrich and folio-mapper are cloned as sibling
    # directories next to this repo. Override with environment variables
    # FOLIO_INSIGHTS_FOLIO_ENRICH_PATH / FOLIO_INSIGHTS_FOLIO_MAPPER_PATH
    # or a .env file (see .env.example).
    #
    # Source repos:
    #   https://github.com/alea-institute/folio-enrich
    #   https://github.com/alea-institute/folio-mapper
    folio_enrich_path: Path = Path("../folio-enrich/backend")
    folio_mapper_path: Path = Path("../folio-mapper/backend")

    # Doctor microservice (optional, for WPD files)
    doctor_url: str | None = None

    # LLM configuration (provider agnostic)
    llm_provider: str = "google"
    llm_model: str = "gemini-2.5-flash-lite"

    # Confidence thresholds
    confidence_high: float = 0.8
    confidence_medium: float = 0.5

    # Output
    output_dir: Path = Path("./output")
    corpus_name: str = "default"

    # Deterministic-IRI integrity. The FOLIO entity-ruler path (folio-enrich
    # FOLIOEntityRuler, imported via the sys.path bridge) is what produces
    # *deterministic* concept IRIs. If it cannot load, the tagger would fall
    # back to LLM/semantic guessing — the exact silent failure that produced
    # ~60% wrong-concept IRIs in book-UAT (see docs/solutions/
    # sys-path-bridge-staleness.md). Default True = fail LOUD (raise) rather
    # than silently degrade. Set False for ad-hoc runs where an LLM-only tag
    # path is acceptable; the degraded state is still surfaced in output
    # metadata either way.
    require_deterministic_iri: bool = True

    # B7 boundary-detection performance. The >11-min full-chapter stall was
    # serial, blocking Tier-3 LLM-refinement calls — one per ambiguous
    # (>500-char) paragraph, each a ~14.5s Google round-trip with 503 backoff
    # (docs/solutions/boundary-tier3-serial-llm-stall.md). Fixes:
    #  - process ambiguous paragraphs CONCURRENTLY (bounded) instead of serially;
    #  - default the LLM refiner OFF: a deterministic sentence-group split
    #    (Tier-2 semantic + sentence grouping) handles large paragraphs with no
    #    network dependency and no content dropped. Set boundary_llm_refine=True
    #    to re-enable Tier-3 (still bounded + concurrency-capped).
    boundary_llm_refine: bool = False
    boundary_tier_concurrency: int = 8
    # Max chars for a deterministically split unit; larger coherent paragraphs
    # are split on sentence groups so no giant single unit survives.
    boundary_max_unit_chars: int = 600

    # B6 fabrication guard: minimum count of substantive characters a boundary
    # must carry to be unit-ized and distilled. Heading/TOC/attribution lines
    # fall below this and are dropped rather than fed to the generative
    # distiller (which invents authority to fill the void). See docs/solutions/
    # heading-as-unit-fabrication.md.
    min_substantive_chars: int = 40

    model_config = {"env_prefix": "FOLIO_INSIGHTS_", "env_file": ".env", "extra": "ignore"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached Settings singleton."""
    return Settings()
