"""Application settings with pydantic-settings and .env support."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
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

    # In-repo FOLIO ontology service (services/folio_ontology.py). The label-lemma cache is
    # insights-owned (never folio-enrich's directory). A failed FOLIO load (e.g. an offline box
    # with no ~/.folio cache) is not retried for ``folio_load_retry_seconds``; lookups in that
    # window raise immediately instead of re-attempting the GitHub fetch every call.
    folio_lemma_cache_dir: Path = Path("~/.folio-insights/cache/lemmas")
    folio_load_retry_seconds: float = 300.0

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

    # Abandoned paused jobs (R18, KTD13): a needs_credentials / budget_exhausted job nobody
    # resumed within this many seconds is cancelled as "expired", so it stops blocking its
    # corpus. 0 or negative disables the sweep; non-finite values are rejected.
    # Env: FOLIO_INSIGHTS_JOB_PAUSED_TTL_SECONDS.
    job_paused_ttl_seconds: float = 86400.0

    @field_validator("job_paused_ttl_seconds", mode="before")
    @classmethod
    def _check_paused_ttl(cls, value: object) -> float:
        from folio_insights.jobs.worker import parse_paused_ttl

        return parse_paused_ttl(value)

    # API operator authentication (drain plan U5, R15, KTD10; api/auth.py). State-changing API
    # routes need an operator bearer token whose SHA-256 is listed in ``api_tokens_file`` (one
    # ``sha256:<64 hex> <handle> <role>`` line per token, mode 600, outside the repository).
    # ``api_auth`` is ``required`` (the default, also with no tokens file: fail closed) or
    # ``loopback-open`` (local development: a loopback client addressing a loopback host may
    # write without a token). See "API authentication" in docs/storage-operations.md.
    api_auth: str = "required"
    api_tokens_file: Path | None = None

    model_config = {"env_prefix": "FOLIO_INSIGHTS_", "env_file": ".env", "extra": "ignore"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached Settings singleton."""
    return Settings()
