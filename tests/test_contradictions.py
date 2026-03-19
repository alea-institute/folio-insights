"""Test scaffolds for TASK-04: contradiction detection and resolution.

Covers cross-encoder NLI screening, LLM deep analysis,
and resolution persistence.
"""

import pytest

from folio_insights.models.task import Contradiction


@pytest.mark.skip(reason="Wave 0 scaffold")
def test_nli_screening():
    """ContradictionDetectionStage uses cross-encoder NLI model to
    screen all unit pairs within each task. Pairs with contradiction
    score > 0.7 are flagged for deep LLM analysis."""


@pytest.mark.skip(reason="Wave 0 scaffold")
def test_deep_analysis():
    """After NLI screening, flagged pairs undergo LLM analysis to
    determine contradiction_type (full/partial/jurisdictional),
    provide explanation, and suggest resolution."""


@pytest.mark.skip(reason="Wave 0 scaffold")
def test_resolution_storage():
    """Contradiction resolutions (keep_both, prefer_a, prefer_b,
    merge, jurisdiction) are stored with resolved_text for merged
    statements and resolver_note for audit trail."""
