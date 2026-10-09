"""Application settings with pydantic-settings and .env support."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Global configuration for folio-insights."""

    # Bridge paths -- folio-insights imports services from sibling repos via
    # a sys.path bridge (see src/folio_insights/services/bridge/). Since the
    # 2026-10-09 retirement (docs/bridge-retirement-2026-10-09.md) only the
    # multi-format IngestionBridge (enrich) and the tabular MapperBridge
    # (folio-mapper, with a stdlib CSV fallback) still use these paths.
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

    # Deterministic-IRI integrity (B5). The entity-ruler path is what produces deterministic
    # concept IRIs. If it cannot load, the tagger would fall back to LLM/semantic IRIs silently.
    # True (the default) fails the run loudly instead; False runs degraded. Either way the state
    # is recorded in output metadata (``metadata.folio_tagger``).
    require_deterministic_iri: bool = True

    # Boundary detection performance (B7). Ambiguous (long) paragraphs are refined
    # concurrently, at most ``boundary_tier_concurrency`` at a time. The Tier-3 LLM refiner is
    # off by default: a deterministic sentence-group split handles long paragraphs with no
    # network dependency and no dropped content. ``boundary_max_unit_chars`` caps a split unit.
    boundary_llm_refine: bool = False
    boundary_tier_concurrency: int = 8
    boundary_max_unit_chars: int = 600

    # Per-unit tagging failures (Phase 10 KTD7). A unit whose tagging raises is counted and
    # recorded, never silently skipped; the run fails when more than this fraction of the units
    # it tried to tag failed.
    tagger_max_unit_failure_ratio: float = 0.05
    # Per-unit LLM-path failures (distill, classify, novelty, concept): the run fails when more
    # than this fraction of the units a path attempted failed (KTD7). Halting errors (no key,
    # rejected key, spend cap, unknown model) stop the run regardless.
    llm_max_unit_failure_ratio: float = 0.05

    # Substantive-input guard (B6). Boundary detection drops boundaries by SHAPE only (heading,
    # contents entry, attribution); the distiller additionally skips text shorter than this.
    min_substantive_chars: int = 20

    model_config = {"env_prefix": "FOLIO_INSIGHTS_", "env_file": ".env", "extra": "ignore"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached Settings singleton."""
    return Settings()
