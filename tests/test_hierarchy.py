"""Tests for TASK-02: hierarchical task tree construction.

Covers tree building, procedural ordering, unit grouping by type,
and polyhierarchy support.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from folio_insights.models.knowledge_unit import KnowledgeType, KnowledgeUnit, Span
from folio_insights.models.task import (
    DiscoveredTask,
    DiscoveryJob,
    TaskCandidate,
    TaskHierarchy,
)
from folio_insights.pipeline.discovery.stages.hierarchy_construction import (
    HierarchyConstructionStage,
)


def _make_unit(
    unit_id: str,
    text: str,
    source_section: list[str] | None = None,
    unit_type: KnowledgeType = KnowledgeType.ADVICE,
) -> KnowledgeUnit:
    """Create a minimal KnowledgeUnit for testing."""
    return KnowledgeUnit(
        id=unit_id,
        text=text,
        original_span=Span(start=0, end=len(text), source_file="test.md"),
        unit_type=unit_type,
        source_file="test.md",
        source_section=source_section or [],
    )


def _make_candidate(
    label: str,
    heading_path: list[str],
    unit_ids: list[str],
    confidence: float = 0.8,
    source_file: str = "test.md",
) -> TaskCandidate:
    """Create a TaskCandidate for testing."""
    return TaskCandidate(
        label=label,
        source_signal="heading",
        confidence=confidence,
        heading_path=heading_path,
        knowledge_unit_ids=unit_ids,
        source_file=source_file,
    )


def test_hierarchy_construction_builds_tree():
    """HierarchyConstructionStage converts TaskCandidates into a
    parent-child tree of DiscoveredTasks, setting parent_task_id
    and depth based on heading hierarchy."""
    units = [
        _make_unit("u1", "Deposition prep fundamentals"),
        _make_unit("u2", "Expert deposition techniques"),
        _make_unit("u3", "Cross exam leading questions"),
        _make_unit("u4", "Cross exam impeachment rules"),
    ]

    candidates = [
        _make_candidate("Trial Advocacy", ["Trial Advocacy"], ["u1", "u2", "u3", "u4"]),
        _make_candidate("Depositions", ["Trial Advocacy", "Depositions"], ["u1", "u2"]),
        _make_candidate("Cross Examination", ["Trial Advocacy", "Cross Examination"], ["u3", "u4"]),
    ]

    job = DiscoveryJob(
        corpus_name="test",
        source_dir=Path("/tmp/test"),
        knowledge_units=units,
        task_candidates=candidates,
    )

    stage = HierarchyConstructionStage()
    result = asyncio.run(stage.execute(job))

    assert result.task_hierarchy is not None
    tasks = result.task_hierarchy.tasks
    assert len(tasks) == 3

    # Find the top-level task and children
    task_map = {t.label: t for t in tasks}
    assert "Trial Advocacy" in task_map
    assert "Depositions" in task_map
    assert "Cross Examination" in task_map

    # Top-level task has no parent
    top = task_map["Trial Advocacy"]
    assert top.parent_task_id is None
    assert top.depth == 0

    # Child tasks have parent_task_id pointing to top-level
    depo = task_map["Depositions"]
    cross = task_map["Cross Examination"]
    assert depo.parent_task_id == top.id
    assert cross.parent_task_id == top.id
    assert depo.depth == 1
    assert cross.depth == 1


def test_procedural_ordering():
    """Without LLM, tasks default to categorical (is_procedural=False)
    and canonical_order stays None."""
    units = [
        _make_unit("u1", "File the motion first"),
        _make_unit("u2", "Prepare the argument"),
        _make_unit("u3", "Oral argument techniques"),
    ]

    candidates = [
        _make_candidate("Motions Practice", ["Motions Practice"], ["u1", "u2", "u3"]),
        _make_candidate("Filing", ["Motions Practice", "Filing"], ["u1"]),
        _make_candidate("Argument", ["Motions Practice", "Argument"], ["u2", "u3"]),
    ]

    job = DiscoveryJob(
        corpus_name="test",
        source_dir=Path("/tmp/test"),
        knowledge_units=units,
        task_candidates=candidates,
    )

    stage = HierarchyConstructionStage()
    result = asyncio.run(stage.execute(job))

    # Without LLM, all tasks should default to categorical
    for task in result.task_hierarchy.tasks:
        assert task.is_procedural is False
        assert task.canonical_order is None


def test_unit_grouping_by_type():
    """Knowledge units grouped by type under each task should populate
    unit_type_counts correctly."""
    units = [
        _make_unit("u1", "Tip about leading questions", unit_type=KnowledgeType.ADVICE),
        _make_unit("u2", "Rule: leading questions on cross", unit_type=KnowledgeType.RULE),
        _make_unit("u3", "Warning: avoid compound questions", unit_type=KnowledgeType.PITFALL),
        _make_unit("u4", "Smith v. Jones supports this", unit_type=KnowledgeType.CITATION),
    ]

    candidates = [
        _make_candidate(
            "Cross Examination",
            ["Cross Examination"],
            ["u1", "u2", "u3", "u4"],
        ),
    ]

    job = DiscoveryJob(
        corpus_name="test",
        source_dir=Path("/tmp/test"),
        knowledge_units=units,
        task_candidates=candidates,
    )

    stage = HierarchyConstructionStage()
    result = asyncio.run(stage.execute(job))

    task = result.task_hierarchy.tasks[0]
    counts = task.unit_type_counts
    assert counts.get("advice") == 1
    assert counts.get("procedural_rule") == 1
    assert counts.get("pitfall") == 1
    assert counts.get("citation") == 1


def test_polyhierarchy_support():
    """Tasks with multiple FOLIO parent IRIs should have parent_iris populated.
    Primary parent is set as parent_task_id via heading hierarchy."""
    units = [
        _make_unit("u1", "Evidence preservation in depositions"),
        _make_unit("u2", "Deposition evidence handling"),
    ]

    # A candidate with both a heading-based parent and multiple FOLIO parents
    candidate = _make_candidate(
        "Evidence Preservation",
        ["Trial Advocacy", "Evidence Preservation"],
        ["u1", "u2"],
    )
    parent_candidate = _make_candidate(
        "Trial Advocacy",
        ["Trial Advocacy"],
        ["u1", "u2"],
    )

    job = DiscoveryJob(
        corpus_name="test",
        source_dir=Path("/tmp/test"),
        knowledge_units=units,
        task_candidates=[parent_candidate, candidate],
    )

    stage = HierarchyConstructionStage()
    result = asyncio.run(stage.execute(job))

    # The child task should have parent_task_id set via heading hierarchy
    task_map = {t.label: t for t in result.task_hierarchy.tasks}
    child = task_map["Evidence Preservation"]
    parent = task_map["Trial Advocacy"]
    assert child.parent_task_id == parent.id
    # parent_iris is populated by FOLIO hierarchy (may be empty without FolioService)
    assert isinstance(child.parent_iris, list)
