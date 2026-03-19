"""Test scaffolds for TASK-03: cross-source task merging.

Covers embedding-based merging, IRI-based merging, and
deduplication guarantees.
"""

import pytest

from folio_insights.models.task import (
    DiscoveredTask,
    TaskHierarchy,
)


@pytest.mark.skip(reason="Wave 0 scaffold")
def test_cross_source_merging_by_embedding():
    """CrossSourceMergingStage merges tasks discovered in different
    source files when their embedding cosine similarity exceeds 0.85.
    The canonical task (highest confidence) absorbs the other's units."""


@pytest.mark.skip(reason="Wave 0 scaffold")
def test_iri_merge():
    """CrossSourceMergingStage merges tasks with identical FOLIO IRIs
    regardless of embedding similarity. IRI match is an exact merge target."""


@pytest.mark.skip(reason="Wave 0 scaffold")
def test_no_duplicate_tasks_after_merge():
    """After merging, the task hierarchy contains no duplicate tasks:
    each unique FOLIO IRI appears at most once, and no two tasks
    have embedding similarity > 0.85."""
