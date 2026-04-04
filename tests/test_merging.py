"""Tests for TASK-03: cross-source task merging.

Covers IRI-based merging, embedding-based merging, and
deduplication guarantees.
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
from folio_insights.pipeline.discovery.stages.cross_source_merging import (
    CrossSourceMergingStage,
)


def _make_unit(
    unit_id: str,
    text: str,
    source_file: str = "ch1.md",
) -> KnowledgeUnit:
    """Create a minimal KnowledgeUnit for testing."""
    return KnowledgeUnit(
        id=unit_id,
        text=text,
        original_span=Span(start=0, end=len(text), source_file=source_file),
        unit_type=KnowledgeType.ADVICE,
        source_file=source_file,
        source_section=[],
    )


def _make_task(
    task_id: str,
    label: str,
    folio_iri: str | None = None,
    confidence: float = 0.8,
    source_file: str = "ch1.md",
    unit_ids: list[str] | None = None,
) -> DiscoveredTask:
    """Create a DiscoveredTask for testing."""
    return DiscoveredTask(
        id=task_id,
        label=label,
        folio_iri=folio_iri,
        confidence=confidence,
        source_signals=["heading"],
        metadata={
            "source_file": source_file,
            "knowledge_unit_ids": unit_ids or [],
        },
    )


def _build_job_with_hierarchy(
    tasks: list[DiscoveredTask],
    units: list[KnowledgeUnit],
    task_unit_links: dict[str, list[str]],
) -> DiscoveryJob:
    """Build a DiscoveryJob with a pre-constructed TaskHierarchy."""
    unit_task_links: dict[str, list[str]] = {}
    for tid, uids in task_unit_links.items():
        for uid in uids:
            unit_task_links.setdefault(uid, []).append(tid)

    hierarchy = TaskHierarchy(
        tasks=tasks,
        task_unit_links=task_unit_links,
        unit_task_links=unit_task_links,
    )
    return DiscoveryJob(
        corpus_name="test",
        source_dir=Path("/tmp/test"),
        knowledge_units=units,
        discovered_tasks=tasks,
        task_hierarchy=hierarchy,
    )


def test_cross_source_merging_by_embedding():
    """CrossSourceMergingStage merges tasks with very similar labels
    from different source files via embedding similarity."""
    pytest.importorskip("sentence_transformers")

    units = [
        _make_unit("u1", "Pin down expert methodology", source_file="book_a.md"),
        _make_unit("u2", "Control the expert narrative", source_file="book_b.md"),
    ]

    # Two tasks with near-identical labels from different files
    tasks = [
        _make_task("t1", "Expert Deposition Techniques", confidence=0.9, source_file="book_a.md", unit_ids=["u1"]),
        _make_task("t2", "Expert Deposition Techniques", confidence=0.7, source_file="book_b.md", unit_ids=["u2"]),
    ]

    task_unit_links = {"t1": ["u1"], "t2": ["u2"]}
    job = _build_job_with_hierarchy(tasks, units, task_unit_links)

    stage = CrossSourceMergingStage()
    result = asyncio.run(stage.execute(job))

    # Should merge: identical labels from different sources
    remaining = result.task_hierarchy.tasks
    assert len(remaining) == 1
    # Canonical task should have higher confidence (t1 with 0.9)
    assert remaining[0].id == "t1"
    # Merged task's units should be transferred to canonical
    merged_units = result.task_hierarchy.task_unit_links.get("t1", [])
    assert "u1" in merged_units
    assert "u2" in merged_units


def test_iri_merge():
    """CrossSourceMergingStage merges tasks with identical FOLIO IRIs
    from different source files."""
    units = [
        _make_unit("u1", "Deposition prep step 1", source_file="book_a.md"),
        _make_unit("u2", "Deposition prep step 2", source_file="book_b.md"),
    ]

    shared_iri = "https://folio.openlegalstandard.org/abc123"
    tasks = [
        _make_task("t1", "Deposition Preparation", folio_iri=shared_iri, confidence=0.9, source_file="book_a.md", unit_ids=["u1"]),
        _make_task("t2", "Depo Prep Techniques", folio_iri=shared_iri, confidence=0.6, source_file="book_b.md", unit_ids=["u2"]),
    ]

    task_unit_links = {"t1": ["u1"], "t2": ["u2"]}
    job = _build_job_with_hierarchy(tasks, units, task_unit_links)

    stage = CrossSourceMergingStage()
    result = asyncio.run(stage.execute(job))

    # Should merge by IRI: same folio_iri from different sources
    remaining = result.task_hierarchy.tasks
    assert len(remaining) == 1
    assert remaining[0].folio_iri == shared_iri
    # Canonical should be t1 (higher confidence)
    assert remaining[0].id == "t1"


def test_no_duplicate_tasks_after_merge():
    """After merging, no two tasks share the same FOLIO IRI,
    and the task count is correct."""
    units = [
        _make_unit("u1", "Unit A", source_file="a.md"),
        _make_unit("u2", "Unit B", source_file="b.md"),
        _make_unit("u3", "Unit C", source_file="c.md"),
        _make_unit("u4", "Unit D", source_file="a.md"),
    ]

    iri_shared = "https://folio.openlegalstandard.org/shared1"
    tasks = [
        _make_task("t1", "Task Alpha", folio_iri=iri_shared, confidence=0.9, source_file="a.md", unit_ids=["u1"]),
        _make_task("t2", "Task Beta", folio_iri=iri_shared, confidence=0.7, source_file="b.md", unit_ids=["u2"]),
        _make_task("t3", "Task Gamma", folio_iri=iri_shared, confidence=0.5, source_file="c.md", unit_ids=["u3"]),
        _make_task("t4", "Unique Task", folio_iri="https://folio.openlegalstandard.org/unique", confidence=0.8, source_file="a.md", unit_ids=["u4"]),
    ]

    task_unit_links = {"t1": ["u1"], "t2": ["u2"], "t3": ["u3"], "t4": ["u4"]}
    job = _build_job_with_hierarchy(tasks, units, task_unit_links)

    stage = CrossSourceMergingStage()
    result = asyncio.run(stage.execute(job))

    remaining = result.task_hierarchy.tasks
    # t2 and t3 should be merged into t1; t4 is unique => 2 tasks remain
    assert len(remaining) == 2

    # No duplicate IRIs
    iris = [t.folio_iri for t in remaining if t.folio_iri]
    assert len(iris) == len(set(iris))
