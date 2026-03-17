"""Tests for cross-document deduplication.

Covers:
  - Exact dedup by content_hash
  - Near dedup by embedding cosine similarity
  - Cross-document dedup
  - Higher confidence unit is kept as canonical
  - Lineage recording for merged units
"""

from __future__ import annotations

import hashlib
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from folio_insights.models.knowledge_unit import KnowledgeType, KnowledgeUnit, Span
from folio_insights.pipeline.stages.base import InsightsJob
from folio_insights.pipeline.stages.deduplicator import DeduplicatorStage


def _make_unit(
    text: str,
    source_file: str = "test.md",
    confidence: float = 0.5,
    content_hash: str = "",
) -> KnowledgeUnit:
    """Helper to create a KnowledgeUnit for testing."""
    if not content_hash:
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return KnowledgeUnit(
        text=text,
        original_span=Span(start=0, end=len(text), source_file=source_file),
        unit_type=KnowledgeType.ADVICE,
        source_file=source_file,
        confidence=confidence,
        content_hash=content_hash,
    )


# ---------- Exact dedup ----------


@pytest.mark.asyncio
async def test_exact_dedup():
    """Two units with identical content_hash -> only 1 remains."""
    shared_hash = hashlib.sha256(b"identical content").hexdigest()

    unit1 = _make_unit("identical content", source_file="file1.md", confidence=0.7, content_hash=shared_hash)
    unit2 = _make_unit("identical content", source_file="file2.md", confidence=0.6, content_hash=shared_hash)

    stage = DeduplicatorStage()
    job = InsightsJob(
        corpus_name="test",
        source_dir="/tmp/test",
        units=[unit1, unit2],
    )

    result = await stage.execute(job)

    assert len(result.units) == 1
    # Higher confidence unit is kept
    assert result.units[0].confidence == 0.7


# ---------- Near dedup ----------


@pytest.mark.asyncio
async def test_near_dedup():
    """Two units saying the same thing differently -> mock similarity > 0.85 -> dedup."""
    unit1 = _make_unit("Always lock the expert into their document list", confidence=0.8)
    unit2 = _make_unit("Pin down the expert's reviewed documents early", confidence=0.6)

    # Mock embeddings so similarity > 0.85
    mock_embeddings = np.array([
        [1.0, 0.0, 0.0],  # unit1
        [0.95, 0.31, 0.0],  # unit2 -- cosine with unit1 ~0.95
    ])
    # Normalize
    norms = np.linalg.norm(mock_embeddings, axis=1, keepdims=True)
    mock_embeddings = mock_embeddings / norms

    stage = DeduplicatorStage()

    with patch.object(stage, "_encode_units", return_value=mock_embeddings):
        job = InsightsJob(
            corpus_name="test",
            source_dir="/tmp/test",
            units=[unit1, unit2],
        )
        result = await stage.execute(job)

    # One should be removed
    assert len(result.units) == 1
    # Higher confidence kept
    assert result.units[0].confidence == 0.8


# ---------- Cross-document dedup ----------


@pytest.mark.asyncio
async def test_dedup_across_docs():
    """Units from 2 different source files with overlapping advice -> dedup works."""
    shared_hash = hashlib.sha256(b"same advice").hexdigest()

    unit1 = _make_unit(
        "same advice", source_file="book1/ch1.md", confidence=0.9, content_hash=shared_hash
    )
    unit2 = _make_unit(
        "same advice", source_file="book2/ch5.md", confidence=0.7, content_hash=shared_hash
    )

    stage = DeduplicatorStage()
    job = InsightsJob(
        corpus_name="test",
        source_dir="/tmp/test",
        units=[unit1, unit2],
    )

    result = await stage.execute(job)

    assert len(result.units) == 1
    assert result.units[0].source_file == "book1/ch1.md"  # higher confidence


# ---------- Keeps higher confidence ----------


@pytest.mark.asyncio
async def test_dedup_keeps_higher_confidence():
    """The unit with higher confidence is kept as canonical."""
    shared_hash = hashlib.sha256(b"duplicate text").hexdigest()

    low_conf = _make_unit("duplicate text", confidence=0.3, content_hash=shared_hash)
    high_conf = _make_unit("duplicate text", confidence=0.95, content_hash=shared_hash)

    stage = DeduplicatorStage()
    job = InsightsJob(
        corpus_name="test",
        source_dir="/tmp/test",
        units=[low_conf, high_conf],
    )

    result = await stage.execute(job)

    assert len(result.units) == 1
    assert result.units[0].confidence == 0.95
    # Canonical should have cross-reference to the removed unit
    assert len(result.units[0].cross_references) == 1


# ---------- Lineage ----------


@pytest.mark.asyncio
async def test_dedup_lineage():
    """Deduplicated units have merge lineage entries."""
    shared_hash = hashlib.sha256(b"dedup lineage test").hexdigest()

    unit1 = _make_unit("dedup lineage test", confidence=0.8, content_hash=shared_hash)
    unit2 = _make_unit("dedup lineage test", confidence=0.4, content_hash=shared_hash)

    stage = DeduplicatorStage()
    job = InsightsJob(
        corpus_name="test",
        source_dir="/tmp/test",
        units=[unit1, unit2],
    )

    result = await stage.execute(job)

    assert len(result.units) == 1
    canonical = result.units[0]

    # Should have lineage entry for merge
    merge_events = [e for e in canonical.lineage if e.action == "merge"]
    assert len(merge_events) == 1
    assert "merged_from" in merge_events[0].detail


# ---------- Stage basics ----------


def test_dedup_stage_name():
    """DeduplicatorStage has correct name."""
    stage = DeduplicatorStage()
    assert stage.name == "deduplicator"


@pytest.mark.asyncio
async def test_dedup_no_change_on_unique():
    """Units with unique content are not removed."""
    units = [
        _make_unit("Unique advice one", confidence=0.7),
        _make_unit("Completely different advice", confidence=0.8),
    ]

    stage = DeduplicatorStage()

    # Mock encoding so they're dissimilar
    mock_embeddings = np.array([
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
    ], dtype=np.float32)

    with patch.object(stage, "_encode_units", return_value=mock_embeddings):
        job = InsightsJob(
            corpus_name="test",
            source_dir="/tmp/test",
            units=units,
        )
        result = await stage.execute(job)

    assert len(result.units) == 2
