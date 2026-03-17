"""Bridge adapter for folio-enrich's LLM registry with per-task routing.

Supports per-task LLM provider/model overrides via environment variables
following the pattern: LLM_{TASK}_PROVIDER, LLM_{TASK}_MODEL.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from folio_insights.services.bridge.folio_bridge import _ensure_folio_enrich_path

logger = logging.getLogger(__name__)

# folio-insights specific LLM task names
INSIGHTS_TASKS: tuple[str, ...] = (
    "boundary",
    "classifier",
    "distiller",
    "novelty",
    "heading_mapper",
    "concept",
    "branch_judge",
)


class LLMBridge:
    """Wraps folio-enrich's LLM registry with per-task routing for folio-insights.

    For each task, checks environment variables for provider/model overrides,
    falling back to global settings from folio-insights config.
    """

    def __init__(self) -> None:
        _ensure_folio_enrich_path()

    def get_llm_for_task(self, task: str) -> Any:
        """Get an LLM provider instance for the given task.

        Checks env vars ``LLM_{TASK}_PROVIDER`` and ``LLM_{TASK}_MODEL``
        for per-task overrides, falling back to global ``llm_provider``
        and ``llm_model`` from folio-insights settings.

        Args:
            task: One of INSIGHTS_TASKS (e.g. "boundary", "classifier").

        Returns:
            An LLMProvider instance from folio-enrich's registry.
        """
        from folio_insights.config import get_settings

        settings = get_settings()
        task_upper = task.upper()

        # Per-task overrides from environment
        provider_name = os.environ.get(
            f"LLM_{task_upper}_PROVIDER", settings.llm_provider
        )
        model_name = os.environ.get(
            f"LLM_{task_upper}_MODEL", settings.llm_model
        )

        # Look up API key for this provider
        api_key_env = f"{provider_name.upper()}_API_KEY"
        api_key = os.environ.get(api_key_env, "")

        from app.services.llm.registry import get_provider

        provider = get_provider(
            provider_type=provider_name,
            api_key=api_key or None,
            model=model_name or None,
        )
        logger.debug(
            "LLM for task '%s': provider=%s, model=%s",
            task, provider_name, model_name,
        )
        return provider
