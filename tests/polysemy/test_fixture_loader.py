"""Fixture loader tests — OQ-3 gate (FRE distinct from Restatement) + TTL emission smoke."""
from pathlib import Path

import pytest

pytestmark = pytest.mark.polysemy_spike

FIXTURE_DIR = Path(".planning/phases/01-polysemy-distinguo-spike/fixtures/consideration")


def test_at_least_20_shards_across_3_frameworks() -> None:
    from folio_insights.polysemy.fixture_loader import load_consideration_fixtures

    shards = load_consideration_fixtures(FIXTURE_DIR)
    assert len(shards) >= 20, f"CONTEXT.md D-1 floor: ≥20 shards, got {len(shards)}"
    frameworks = {s.framework for s in shards}
    assert len(frameworks) >= 3, f"D-1: ≥3 frameworks, got {frameworks}"
    for fw in ("CommonLaw", "Restatement"):
        count = sum(1 for s in shards if s.framework == fw)
        assert count >= 3, f"N≥3 per framework (PITFALLS L651): {fw} has {count}"


def test_fre_axioms_distinct_from_restatement() -> None:
    """OQ-3 gate: FRE axioms MUST encode judicial-weighing semantics, not bargain.

    If this fails, swap in UCC §2-209 shards per A9 backup.
    """
    from folio_insights.polysemy.fixture_loader import load_consideration_fixtures

    shards = load_consideration_fixtures(FIXTURE_DIR)
    fre_axioms = " ".join(
        s.axiom_summary.lower() for s in shards if s.framework == "FRE"
    )
    if not fre_axioms:
        pytest.skip("No FRE shards — UCC backup path active (A9)")
    # FRE axioms should mention weighing/relevance/probative terminology
    has_weighing_language = any(
        term in fre_axioms
        for term in ("weigh", "relevance", "probative", "prejudic", "judicial")
    )
    assert has_weighing_language, (
        "OQ-3 gate: FRE axioms do not encode judicial-weighing semantics; "
        "fixture drift or Restatement-overlap detected. Swap to UCC §2-209 per A9."
    )
    # And should NOT be dominated by bargain/exchange semantics
    bargain_hits = sum(
        1 for term in ("bargained", "exchange", "promise") if term in fre_axioms
    )
    assert bargain_hits <= 1, (
        "OQ-3 gate: FRE axioms overlap Restatement's bargain vocabulary — "
        "consider re-phrasing or swapping to UCC."
    )


def test_ttl_emission_contains_vocab() -> None:
    from folio_insights.polysemy.fixture_loader import (
        consideration_fixtures_to_ttl,
        load_consideration_fixtures,
    )

    ttl = consideration_fixtures_to_ttl(load_consideration_fixtures(FIXTURE_DIR))
    assert "@prefix fi:" in ttl
    assert "fi:axiomSummary" in ttl
    assert "fi:inFramework" in ttl
