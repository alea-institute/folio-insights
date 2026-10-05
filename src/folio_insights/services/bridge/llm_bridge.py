"""Per-task LLM routing, now resolved through the in-repo LLM port (Phase 10 U1, KTD2).

``LLMBridge.get_llm_for_task(task)`` keeps its task names and the ``LLM_{TASK}_PROVIDER`` /
``LLM_{TASK}_MODEL`` environment overrides, but no longer reaches into folio-enrich's LLM
registry through a ``sys.path`` bridge. It returns a :class:`~folio_insights.llm.TaskLLM` bound
to the task: the same ``structured(prompt, schema=..., temperature=0)`` / ``complete(prompt)``
call shape stage code already uses, now with validated output, a registered prompt template,
one retry layer, usage capture and per-run credentials.

folio-enrich remains a bridge for ingestion and FOLIO services only.
"""

from __future__ import annotations

import logging

from folio_insights.llm import Route, TaskLLM
from folio_insights.llm.port import resolve_route

logger = logging.getLogger(__name__)

# folio-insights specific LLM task names (the routing keys of LLM_{TASK}_PROVIDER/MODEL).
INSIGHTS_TASKS: tuple[str, ...] = (
    # Phase 1: extraction pipeline
    "boundary",
    "classifier",
    "distiller",
    "novelty",
    "heading_mapper",
    "concept",
    "branch_judge",
    # Phase 2: task discovery pipeline
    "task_discovery",
    "task_ordering",
    "contradiction",
    "orphan_assignment",
    # Phase 1 polysemy spike: detector R4 LLM fallback (OQ-5 provider-agnostic)
    "polysemy_fallback",
    # Phase 9 U2: framework detector LLM stage (registered IDs only)
    "framework_detector",
    # Phase 9 U7: BFO classifier LLM fallback (the four envelope categories only)
    "bfo_classifier",
)


class LLMBridge:
    """Hands each pipeline task a port-backed :class:`TaskLLM`.

    Constructing the bridge or fetching a task LLM never reads a key and never fails for a
    missing one; the credential is required (from the current run context) when a call is made.
    """

    def get_llm_for_task(self, task: str, *, route: Route | None = None) -> TaskLLM:
        """Return the port-backed LLM for ``task``.

        Routing (when ``route`` is not given) is resolved per call from, in order: the per-task
        ``LLM_{TASK}_PROVIDER`` / ``LLM_{TASK}_MODEL`` env overrides, the run's
        ``--llm-provider`` / ``--llm-model`` (or API request) choice, then settings.
        """
        if route is None:
            try:
                logger.debug("LLM for task '%s': %s", task, resolve_route(task))
            except Exception:  # noqa: BLE001 - diagnostics only; the call reports real errors
                logger.debug("LLM route for task '%s' unresolved", task, exc_info=True)
        return TaskLLM(task, route=route)
