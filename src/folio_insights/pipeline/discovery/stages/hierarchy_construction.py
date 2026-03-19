"""Stage 4: Hierarchy Construction -- build parent-child task tree.

Converts TaskCandidates into DiscoveredTasks with parent-child relationships,
determines procedural vs categorical ordering via LLM, assigns orphan units
to nearest tasks, groups units by type, and detects jurisdiction sensitivity.
"""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from typing import Any
from uuid import uuid4

from folio_insights.models.knowledge_unit import KnowledgeType, KnowledgeUnit
from folio_insights.models.task import (
    DiscoveredTask,
    TaskCandidate,
    TaskHierarchy,
)
from folio_insights.pipeline.discovery.stages.base import DiscoveryStage, DiscoveryJob

logger = logging.getLogger(__name__)

# Regex patterns for jurisdiction sensitivity heuristic
_JURISDICTION_PATTERNS = re.compile(
    r"(?i)\b("
    r"in federal court|in state court|some states|varies by state|"
    r"varies by jurisdiction|jurisdictional|under .{2,30} law|"
    r"depending on the jurisdiction|most jurisdictions|"
    r"minority of jurisdictions|federal rules?|state rules?"
    r")\b"
)


class HierarchyConstructionStage(DiscoveryStage):
    """Build the parent-child task hierarchy from task candidates.

    Converts TaskCandidates to DiscoveredTasks, establishes hierarchy
    from heading paths and FOLIO concepts, determines procedural ordering,
    assigns orphan units, and detects jurisdiction sensitivity.
    """

    def __init__(self, folio_service: Any | None = None) -> None:
        self._folio_service = folio_service

    @property
    def name(self) -> str:
        return "hierarchy_construction"

    async def execute(self, job: DiscoveryJob) -> DiscoveryJob:
        """Build task tree from candidates, assign units, detect flags."""
        locked_ids: set[str] = set(job.metadata.get("locked_task_ids", []))

        # 1. Convert candidates to DiscoveredTasks
        tasks = self._candidates_to_tasks(job.task_candidates, locked_ids)

        # Merge with any pre-loaded locked tasks
        locked_existing = {t.id: t for t in job.discovered_tasks if t.id in locked_ids}
        task_map = {t.id: t for t in tasks}
        task_map.update(locked_existing)
        tasks = list(task_map.values())

        # 2. Build parent-child relationships from heading paths
        self._build_heading_hierarchy(tasks)

        # 3. Build parent-child relationships from FOLIO concept hierarchy
        self._build_folio_hierarchy(tasks)

        # 4. Determine procedural vs categorical and canonical ordering
        await self._classify_task_types(tasks)

        # 5. Build bidirectional task-unit links
        task_unit_links, unit_task_links = self._build_unit_links(
            tasks, job.knowledge_units
        )

        # 6. Assign orphan units to nearest task
        orphan_unit_ids = self._assign_orphan_units(
            tasks, job.knowledge_units, task_unit_links, unit_task_links
        )

        # 7. Group knowledge units by type under each task
        self._compute_unit_type_counts(tasks, task_unit_links, job.knowledge_units)

        # 8. Detect jurisdiction sensitivity
        self._detect_jurisdiction_sensitivity(
            tasks, task_unit_links, job.knowledge_units
        )

        # 9. Set depth based on hierarchy
        self._compute_depths(tasks)

        # Build hierarchy
        job.discovered_tasks = tasks
        job.orphan_unit_ids = orphan_unit_ids
        job.task_hierarchy = TaskHierarchy(
            tasks=tasks,
            task_unit_links=task_unit_links,
            unit_task_links=unit_task_links,
            orphan_unit_ids=orphan_unit_ids,
            contradictions=[],  # Filled by ContradictionDetectionStage
        )

        logger.info(
            "Hierarchy construction: %d tasks, %d orphan units, "
            "%d procedural tasks",
            len(tasks),
            len(orphan_unit_ids),
            sum(1 for t in tasks if t.is_procedural),
        )

        return job

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _candidates_to_tasks(
        self,
        candidates: list[TaskCandidate],
        locked_ids: set[str],
    ) -> list[DiscoveredTask]:
        """Convert TaskCandidates to DiscoveredTasks, skipping locked ones."""
        tasks: list[DiscoveredTask] = []
        seen_labels: dict[str, str] = {}  # label -> task_id (dedup by label)

        for candidate in candidates:
            # Skip if a locked task already covers this label
            lower_label = candidate.label.lower().strip()
            if lower_label in seen_labels:
                continue

            task_id = str(uuid4())
            task = DiscoveredTask(
                id=task_id,
                label=candidate.label,
                folio_iri=candidate.folio_iri,
                folio_label=candidate.folio_label,
                is_procedural=candidate.is_procedural,
                canonical_order=candidate.canonical_order,
                confidence=candidate.confidence,
                source_signals=[candidate.source_signal],
                metadata={
                    "heading_path": candidate.heading_path,
                    "source_file": candidate.source_file,
                    "knowledge_unit_ids": candidate.knowledge_unit_ids,
                },
            )
            tasks.append(task)
            seen_labels[lower_label] = task_id

        return tasks

    def _build_heading_hierarchy(self, tasks: list[DiscoveredTask]) -> None:
        """Set parent-child relationships from heading_path metadata.

        If heading_path is ["Ch.5", "Cross-Examination", "Leading Questions"],
        then "Leading Questions" is a child of "Cross-Examination", which is
        a child of "Ch.5".
        """
        # Build mapping: (heading_path prefix) -> task_id
        path_to_task: dict[tuple[str, ...], str] = {}
        for task in tasks:
            heading_path = task.metadata.get("heading_path", [])
            if heading_path:
                path_to_task[tuple(heading_path)] = task.id

        # For each task, find the nearest parent by checking prefix paths
        for task in tasks:
            if task.parent_task_id is not None:
                continue  # Already has parent

            heading_path = task.metadata.get("heading_path", [])
            if len(heading_path) < 2:
                continue  # Top-level, no parent to find

            # Walk up the heading path to find parent
            for depth in range(len(heading_path) - 1, 0, -1):
                parent_path = tuple(heading_path[:depth])
                parent_id = path_to_task.get(parent_path)
                if parent_id is not None and parent_id != task.id:
                    task.parent_task_id = parent_id
                    break

    def _build_folio_hierarchy(self, tasks: list[DiscoveredTask]) -> None:
        """Set parent-child from FOLIO concept polyhierarchy.

        For tasks with folio_iri, look up parent IRIs via FolioService
        and store in parent_iris for polyhierarchy support.
        """
        folio_service = self._get_folio_service()
        if folio_service is None:
            return

        # Build IRI -> task_id map
        iri_to_task: dict[str, str] = {}
        for task in tasks:
            if task.folio_iri:
                iri_to_task[task.folio_iri] = task.id

        for task in tasks:
            if not task.folio_iri:
                continue

            try:
                concept = folio_service.get_concept(task.folio_iri)
                if concept is None:
                    continue

                # Get parent IRIs from FOLIO concept
                parent_iris = getattr(concept, "parent_iris", [])
                if not parent_iris:
                    broader = getattr(concept, "broader", [])
                    parent_iris = [
                        getattr(b, "iri", str(b))
                        for b in broader
                        if b is not None
                    ]

                task.parent_iris = parent_iris

                # If no heading-based parent, try FOLIO parent
                if task.parent_task_id is None and parent_iris:
                    for piri in parent_iris:
                        parent_task_id = iri_to_task.get(piri)
                        if parent_task_id is not None and parent_task_id != task.id:
                            task.parent_task_id = parent_task_id
                            break

            except Exception:
                logger.debug(
                    "FOLIO hierarchy lookup failed for %s",
                    task.folio_iri,
                    exc_info=True,
                )

    async def _classify_task_types(self, tasks: list[DiscoveredTask]) -> None:
        """Use LLM to classify top-level tasks as procedural or categorical.

        For procedural tasks, also determines canonical ordering of subtasks.
        Falls back to is_procedural=False if LLM is unavailable.
        """
        import json as _json

        # Only classify top-level tasks (or tasks that have children)
        child_ids = {t.parent_task_id for t in tasks if t.parent_task_id}
        top_level = [t for t in tasks if t.parent_task_id is None or t.id in child_ids]

        llm = self._get_llm()
        if llm is None:
            logger.info("LLM unavailable; defaulting all tasks to categorical")
            return

        from folio_insights.services.prompts.task_discovery import (
            TASK_ORDERING_PROMPT,
        )

        for task in top_level:
            if task.is_procedural:
                continue  # Already classified by content clustering

            # Get subtask labels
            children = [t for t in tasks if t.parent_task_id == task.id]
            if not children:
                continue

            subtask_labels = "\n".join(f"- {c.label}" for c in children)

            prompt = TASK_ORDERING_PROMPT.format(
                task_label=task.label,
                subtask_labels=subtask_labels,
            )

            try:
                response = await llm.generate(prompt)
                parsed = _json.loads(response)

                is_ordered = parsed.get("is_ordered", False)
                task.is_procedural = is_ordered

                if is_ordered:
                    ordered_labels = parsed.get("ordered_labels", [])
                    # Assign canonical_order to children matching ordered labels
                    label_order = {
                        lbl.strip().lower(): idx
                        for idx, lbl in enumerate(ordered_labels)
                    }
                    for child in children:
                        order = label_order.get(child.label.lower().strip())
                        if order is not None:
                            child.canonical_order = order

            except Exception:
                logger.debug(
                    "LLM task classification failed for '%s'; defaulting to categorical",
                    task.label,
                    exc_info=True,
                )

    def _build_unit_links(
        self,
        tasks: list[DiscoveredTask],
        units: list[KnowledgeUnit],
    ) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
        """Build bidirectional task <-> unit link dictionaries."""
        task_unit_links: dict[str, list[str]] = defaultdict(list)
        unit_task_links: dict[str, list[str]] = defaultdict(list)

        for task in tasks:
            unit_ids = task.metadata.get("knowledge_unit_ids", [])
            for uid in unit_ids:
                if uid not in task_unit_links[task.id]:
                    task_unit_links[task.id].append(uid)
                if task.id not in unit_task_links[uid]:
                    unit_task_links[uid].append(task.id)

        return dict(task_unit_links), dict(unit_task_links)

    def _assign_orphan_units(
        self,
        tasks: list[DiscoveredTask],
        units: list[KnowledgeUnit],
        task_unit_links: dict[str, list[str]],
        unit_task_links: dict[str, list[str]],
    ) -> list[str]:
        """Find units not linked to any task and assign to nearest by embedding similarity.

        Returns list of orphan unit IDs (assigned but flagged).
        """
        all_linked_unit_ids: set[str] = set()
        for uids in task_unit_links.values():
            all_linked_unit_ids.update(uids)

        orphan_units = [u for u in units if u.id not in all_linked_unit_ids]
        if not orphan_units or not tasks:
            return []

        orphan_ids: list[str] = []

        try:
            # Use embedding similarity to find nearest task
            from folio_insights.services.task_clustering import _get_model

            model = _get_model()

            # Compute task centroids from their linked unit texts
            task_texts: dict[str, str] = {}
            unit_map = {u.id: u for u in units}
            for task in tasks:
                linked_ids = task_unit_links.get(task.id, [])
                linked_texts = [
                    unit_map[uid].text
                    for uid in linked_ids
                    if uid in unit_map
                ]
                if linked_texts:
                    task_texts[task.id] = " ".join(linked_texts[:10])

            if not task_texts:
                return [u.id for u in orphan_units]

            task_ids_ordered = list(task_texts.keys())
            task_embeddings = model.encode(
                list(task_texts.values()),
                normalize_embeddings=True,
            )

            for orphan in orphan_units:
                orphan_embedding = model.encode(
                    [orphan.text],
                    normalize_embeddings=True,
                )
                # Cosine similarity (normalized embeddings -> dot product)
                similarities = orphan_embedding @ task_embeddings.T
                best_idx = int(similarities[0].argmax())
                best_task_id = task_ids_ordered[best_idx]

                # Assign to nearest task
                task_unit_links.setdefault(best_task_id, []).append(orphan.id)
                unit_task_links.setdefault(orphan.id, []).append(best_task_id)
                orphan_ids.append(orphan.id)

                # Flag the task as having orphans
                for task in tasks:
                    if task.id == best_task_id:
                        task.has_orphans = True
                        break

            logger.info(
                "Orphan assignment: %d units assigned to nearest tasks",
                len(orphan_ids),
            )

        except Exception:
            logger.warning(
                "Orphan assignment failed; %d units remain unlinked",
                len(orphan_units),
                exc_info=True,
            )
            orphan_ids = [u.id for u in orphan_units]

        return orphan_ids

    def _compute_unit_type_counts(
        self,
        tasks: list[DiscoveredTask],
        task_unit_links: dict[str, list[str]],
        units: list[KnowledgeUnit],
    ) -> None:
        """Count knowledge unit types per task."""
        unit_map = {u.id: u for u in units}

        for task in tasks:
            linked_ids = task_unit_links.get(task.id, [])
            type_counter: Counter[str] = Counter()
            for uid in linked_ids:
                unit = unit_map.get(uid)
                if unit is not None:
                    type_counter[unit.unit_type.value] += 1
            task.unit_type_counts = dict(type_counter)

    def _detect_jurisdiction_sensitivity(
        self,
        tasks: list[DiscoveredTask],
        task_unit_links: dict[str, list[str]],
        units: list[KnowledgeUnit],
    ) -> None:
        """Flag tasks with jurisdiction-sensitive knowledge units.

        Uses regex heuristic to detect phrases like "in federal court",
        "some states require", "varies by jurisdiction", etc.
        """
        unit_map = {u.id: u for u in units}

        for task in tasks:
            linked_ids = task_unit_links.get(task.id, [])
            for uid in linked_ids:
                unit = unit_map.get(uid)
                if unit is not None and _JURISDICTION_PATTERNS.search(unit.text):
                    task.is_jurisdiction_sensitive = True
                    break

    def _compute_depths(self, tasks: list[DiscoveredTask]) -> None:
        """Set depth for each task based on parent chain."""
        task_map = {t.id: t for t in tasks}
        for task in tasks:
            depth = 0
            current = task
            visited: set[str] = set()
            while current.parent_task_id and current.parent_task_id in task_map:
                if current.parent_task_id in visited:
                    break  # Prevent cycles
                visited.add(current.parent_task_id)
                depth += 1
                current = task_map[current.parent_task_id]
            task.depth = depth

    def _get_folio_service(self) -> Any | None:
        """Lazy-load FolioService from bridge."""
        if self._folio_service is not None:
            return self._folio_service
        try:
            from folio_insights.services.bridge.folio_bridge import get_folio_service

            self._folio_service = get_folio_service()
        except Exception:
            logger.warning(
                "FolioService unavailable; FOLIO hierarchy will be skipped"
            )
            self._folio_service = None
        return self._folio_service

    def _get_llm(self) -> Any | None:
        """Get LLM for task type classification."""
        try:
            from folio_insights.services.bridge.llm_bridge import LLMBridge

            bridge = LLMBridge()
            return bridge.get_llm_for_task("task_ordering")
        except Exception:
            logger.debug("LLMBridge unavailable for task ordering", exc_info=True)
            return None
