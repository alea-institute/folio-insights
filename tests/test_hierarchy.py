"""Test scaffolds for TASK-02: hierarchical task tree construction.

Covers tree building, procedural ordering, unit grouping by type,
and polyhierarchy support.
"""

import pytest

from folio_insights.models.task import (
    DiscoveredTask,
    TaskHierarchy,
)


@pytest.mark.skip(reason="Wave 0 scaffold")
def test_hierarchy_construction_builds_tree():
    """HierarchyConstructionStage converts TaskCandidates into a
    parent-child tree of DiscoveredTasks, setting parent_task_id
    and depth based on FOLIO concept hierarchy."""


@pytest.mark.skip(reason="Wave 0 scaffold")
def test_procedural_ordering():
    """HierarchyConstructionStage detects procedural tasks via LLM
    and assigns canonical_order to subtasks (preparation -> execution
    -> follow-up). Non-procedural tasks have canonical_order=None."""


@pytest.mark.skip(reason="Wave 0 scaffold")
def test_unit_grouping_by_type():
    """Under each DiscoveredTask, knowledge units are grouped by type
    (advice, principle, citation, procedural_rule, pitfall) and counts
    stored in unit_type_counts."""


@pytest.mark.skip(reason="Wave 0 scaffold")
def test_polyhierarchy_support():
    """Tasks with FOLIO polyhierarchy (multiple parent IRIs) appear
    once in the hierarchy with parent_iris containing all parents.
    The primary parent is set as parent_task_id."""
