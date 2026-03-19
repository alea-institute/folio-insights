"""Test scaffolds for TASK-01: task discovery from headings and content clustering.

Covers heading analysis, FOLIO mapping, content clustering, LLM implicit
task discovery, and the weighted blend confidence formula.
"""

import pytest

from folio_insights.models.task import (
    DiscoveryJob,
    TaskCandidate,
    compute_task_confidence,
)


@pytest.mark.skip(reason="Wave 0 scaffold")
def test_heading_analysis_extracts_candidates():
    """HeadingAnalysisStage groups units by source_section and produces
    TaskCandidates with source_signal='heading'. Heading paths with
    fewer than 2 units should be filtered out."""


@pytest.mark.skip(reason="Wave 0 scaffold")
def test_folio_mapping_resolves_concepts():
    """FolioMappingStage resolves each TaskCandidate to the deepest
    appropriate FOLIO concept IRI, setting folio_iri and folio_label.
    Candidates without a FOLIO match get metadata['proposed_sibling']=True."""


@pytest.mark.skip(reason="Wave 0 scaffold")
def test_content_clustering_discovers_implicit_tasks():
    """ContentClusteringStage clusters units by embedding similarity
    and creates TaskCandidates for clusters not already covered by
    heading-based candidates. Minimum cluster size is 3 units."""


@pytest.mark.skip(reason="Wave 0 scaffold")
def test_implicit_task_discovery_via_llm():
    """ContentClusteringStage uses LLM via TASK_DISCOVERY_PROMPT to
    label implicit tasks discovered through content clustering.
    The LLM response sets task_label, is_procedural, and confidence."""


@pytest.mark.skip(reason="Wave 0 scaffold")
def test_weighted_blend_confidence():
    """compute_task_confidence applies weighted blend: 70% FOLIO, 30% heading.
    Example: compute_task_confidence(0.8, 0.6) should return 0.74."""
