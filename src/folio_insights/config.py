"""Application settings with pydantic-settings and .env support."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Global configuration for folio-insights."""

    # Bridge paths
    folio_enrich_path: Path = Path(
        os.path.expanduser("~/Coding Projects/folio-enrich/backend")
    )
    folio_mapper_path: Path = Path(
        os.path.expanduser("~/Coding Projects/folio-mapper/backend")
    )

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
