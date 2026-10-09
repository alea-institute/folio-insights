"""Coverage: task-tree leaves without an authority shard (Phase 9 U1, R4).

Task discovery (``pipeline/discovery``) builds a task tree whose nodes map to
FOLIO concepts (``DiscoveredTask.folio_iri``). A leaf task, one with no child
task, is the most specific thing a practitioner does; if no authority shard
speaks to its concept, the corpus cannot ground advice about that task. The
``CoverageChecker`` reports each such leaf.

* A shard **addresses** a task when one of its concept IRIs
  (``clusters.shard_concepts``) is the task's concept or, given a FOLIO
  ancestry resolver, a descendant of it.
* An **authority shard** states law: its ``speech_act`` is in
  ``AUTHORITY_SPEECH_ACTS`` (holdings, statutory and regulatory text,
  statutory definitions, restatement black letter, administrative
  interpretations) and it is not superseded. Dicta, pleadings, practitioner
  advice, treatise statements and contract terms address a task without
  covering it.

A leaf without a FOLIO concept cannot be matched at all; it is reported as an
``info`` finding rather than silently counted covered or uncovered.

Task input is either a ``TaskHierarchy`` / list of ``DiscoveredTask``
(``task_nodes_from_hierarchy``) or a discovery output file
(``load_task_nodes``: ``discovery.json`` or ``task_tree.json``). Pure stdlib
+ Pydantic; safe for the web tier.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from folio_insights.validation.clusters import is_folio_concept, shard_concepts
from folio_insights.validation.report import Finding, finding_id

if TYPE_CHECKING:
    from folio_insights.bfo.spine import BranchResolver
    from folio_insights.models.task import DiscoveredTask, TaskHierarchy
    from folio_insights.shards import ShardEnvelope

AUTHORITY_SPEECH_ACTS: frozenset[str] = frozenset(
    {
        "holding",
        "statutory_text",
        "statutory_definition",
        "regulatory_text",
        "restatement_black_letter",
        "administrative_interpretation",
    }
)
MAX_ANCESTRY_DEPTH = 64


@dataclass(frozen=True)
class TaskNode:
    """The part of a discovered task the coverage check needs."""

    id: str
    label: str
    folio_iri: str | None = None
    parent_id: str | None = None


def task_nodes_from_hierarchy(
    tasks: TaskHierarchy | Iterable[DiscoveredTask],
) -> list[TaskNode]:
    """``TaskNode``s from a ``TaskHierarchy`` or ``DiscoveredTask``s."""
    items = getattr(tasks, "tasks", tasks)
    return [
        TaskNode(id=t.id, label=t.label, folio_iri=t.folio_iri, parent_id=t.parent_task_id)
        for t in items
    ]


def _node(raw: Mapping[str, Any]) -> TaskNode:
    return TaskNode(
        id=str(raw["id"]),
        label=str(raw.get("label", "")),
        folio_iri=raw.get("folio_iri") or None,
        parent_id=raw.get("parent_task_id", raw.get("parent_id")) or None,
    )


def load_task_nodes(path: Path | str) -> list[TaskNode]:
    """Task nodes from a discovery output file.

    Accepts ``task_tree.json`` (a list of ``{id, parent_id, label,
    folio_iri}``), ``discovery.json`` (a ``DiscoveryJob`` dump: its
    ``task_hierarchy.tasks``, else ``discovered_tasks``) or a bare
    ``{"tasks": [...]}`` object. Raises ``ValueError`` for anything else.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        hierarchy = data.get("task_hierarchy")
        if isinstance(hierarchy, dict) and isinstance(hierarchy.get("tasks"), list):
            rows = hierarchy["tasks"]
        elif isinstance(data.get("discovered_tasks"), list):
            rows = data["discovered_tasks"]
        elif isinstance(data.get("tasks"), list):
            rows = data["tasks"]
        else:
            raise ValueError(f"{path}: no task list (expected task_tree.json or discovery.json)")
    else:
        raise ValueError(f"{path}: expected a JSON list or object of tasks")
    return [_node(r) for r in rows if isinstance(r, Mapping)]


def leaf_tasks(tasks: Iterable[TaskNode]) -> list[TaskNode]:
    """Tasks no other task names as its parent, ordered by ID."""
    nodes = list(tasks)
    parents = {t.parent_id for t in nodes if t.parent_id}
    return sorted((t for t in nodes if t.id not in parents), key=lambda t: t.id)


class CoverageChecker:
    """Flag task-tree leaves that no authority shard covers."""

    def __init__(
        self,
        *,
        authority_speech_acts: Iterable[str] = AUTHORITY_SPEECH_ACTS,
        folio_resolver: BranchResolver | None = None,
        concept_filter: Callable[[str], bool] = is_folio_concept,
    ) -> None:
        self.authority_speech_acts = frozenset(authority_speech_acts)
        self.folio_resolver = folio_resolver
        self.concept_filter = concept_filter
        self._ancestors: dict[str, frozenset[str]] = {}

    def is_authority(self, shard: ShardEnvelope) -> bool:
        return (
            shard.speech_act in self.authority_speech_acts
            and shard.epistemic_status != "superseded"
            and shard.superseded_by is None
        )

    def check(self, tasks: Iterable[TaskNode], shards: Iterable[ShardEnvelope]) -> list[Finding]:
        """One finding per uncovered (or unmappable) leaf, ordered by task ID."""
        authority: dict[str, set[str]] = {}
        other: dict[str, set[str]] = {}
        for shard in shards:
            bucket = authority if self.is_authority(shard) else other
            for concept in shard_concepts(shard, self.concept_filter):
                for target in self._self_and_ancestors(concept):
                    bucket.setdefault(target, set()).add(shard.shard_iri)
        findings: list[Finding] = []
        for task in leaf_tasks(tasks):
            if not task.folio_iri:
                findings.append(Finding(
                    id=finding_id("coverage_gap", "coverage", [], {"task": task.id}),
                    kind="coverage_gap",
                    checker="coverage",
                    severity="info",
                    summary=f"Leaf task {task.label!r} has no FOLIO concept, so its "
                            "coverage cannot be established.",
                    detail={"task_id": task.id, "task_label": task.label, "folio_iri": None,
                            "reason": "unmapped_task"},
                ))
                continue
            if authority.get(task.folio_iri):
                continue
            addressing = sorted(other.get(task.folio_iri, ()))
            findings.append(Finding(
                id=finding_id("coverage_gap", "coverage", [], {"task": task.id}),
                kind="coverage_gap",
                checker="coverage",
                summary=(
                    f"Leaf task {task.label!r} ({task.folio_iri}) has no authority shard"
                    + (f"; {len(addressing)} non-authority shard(s) address it." if addressing
                       else "; no shard addresses it.")
                ),
                detail={
                    "task_id": task.id,
                    "task_label": task.label,
                    "folio_iri": task.folio_iri,
                    "reason": "no_authority_shard",
                    "non_authority_shards": addressing,
                    "remedy": "extract or attach a holding, statute, regulation, "
                              "restatement or administrative interpretation for this task",
                },
            ))
        return findings

    def _self_and_ancestors(self, concept: str) -> frozenset[str]:
        cached = self._ancestors.get(concept)
        if cached is not None:
            return cached
        seen = {concept}
        frontier = [concept]
        depth = 0
        resolver = self.folio_resolver
        while frontier and resolver is not None and depth < MAX_ANCESTRY_DEPTH:
            nxt: list[str] = []
            for node in frontier:
                for parent in resolver.parents(node):
                    if parent not in seen:
                        seen.add(parent)
                        nxt.append(parent)
            frontier, depth = nxt, depth + 1
        result = frozenset(seen)
        self._ancestors[concept] = result
        return result


__all__ = [
    "AUTHORITY_SPEECH_ACTS",
    "CoverageChecker",
    "TaskNode",
    "leaf_tasks",
    "load_task_nodes",
    "task_nodes_from_hierarchy",
]
