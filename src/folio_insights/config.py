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

    model_config = {"env_prefix": "FOLIO_INSIGHTS_", "env_file": ".env", "extra": "ignore"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached Settings singleton."""
    return Settings()
