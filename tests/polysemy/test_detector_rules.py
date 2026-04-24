"""4-rule gate exercised in isolation with synthetic clusters."""
from unittest.mock import patch

import numpy as np
import pytest

from folio_insights.polysemy.detector import (
    RuleVerdict,
    detect_polysemy,
)
from folio_insights.polysemy.fixture_loader import ShardFixture
from folio_insights.polysemy.prototype_cluster import PrototypeCluster

pytestmark = pytest.mark.polysemy_spike


def _shard(framework: str, axiom: str, iri: str) -> ShardFixture:
    return ShardFixture(
        iri=iri,
        framework=framework,  # type: ignore[arg-type]
        source_doc="s",
        extracted_text=axiom,
        axiom_summary=axiom,
        term="consideration",
    )


def _cluster(
    term: str = "consideration",
    per_fw: int = 3,
    distance: float = 0.9,
) -> PrototypeCluster:
    shards_by_fw = {
        "CommonLaw": [
            _shard("CommonLaw", f"CL axiom {i}", f"fi:Shard_cl{i}")
            for i in range(per_fw)
        ],
        "Restatement": [
            _shard("Restatement", f"R axiom {i}", f"fi:Shard_r{i}")
            for i in range(per_fw)
        ],
        "FRE": [
            _shard("FRE", f"FRE axiom {i}", f"fi:Shard_fre{i}")
            for i in range(per_fw)
        ],
    }
    # Override term on each shard so the cluster's term matches the
    # `term` arg (ShardFixture.term defaults to "consideration").
    if term != "consideration":
        for shards in shards_by_fw.values():
            for s in shards:
                s.term = term
    centroids = {fw: np.zeros(384) for fw in shards_by_fw}
    pairs = [("CommonLaw", "Restatement"), ("CommonLaw", "FRE"), ("Restatement", "FRE")]
    dists = {(a, b): distance for a, b in pairs}
    dists.update({(b, a): distance for a, b in pairs})
    return PrototypeCluster(
        cluster_id="fi:PrototypeCluster_test0000",
        term=term,
        shards_by_framework=shards_by_fw,
        centroids=centroids,
        cross_framework_cosine_distance=dists,
    )


def test_rule1_axioms_not_contexts() -> None:
    """Rule 1: when SPARQL owl:disjointWith returns False, verdict is
    'coincidence' with R1-no-conflict — NOT polysemy on surface similarity."""
    cluster = _cluster(distance=0.99)  # high distance but no owl:disjointWith
    with patch(
        "folio_insights.polysemy.detector.has_framework_conflicting_axiom",
        return_value=False,
    ):
        v = detect_polysemy(cluster, store=None)  # store unused when patched
    assert isinstance(v, RuleVerdict)
    assert v.decision == "coincidence"
    assert v.matched_rules == ["R1-no-conflict"]


def test_rule2_n_ge_3() -> None:
    """Rule 2: frameworks with <3 shards → coincidence / R2-insufficient-evidence."""
    cluster = _cluster(per_fw=2)  # below N≥3 threshold
    with patch(
        "folio_insights.polysemy.detector.has_framework_conflicting_axiom",
        return_value=True,
    ):
        v = detect_polysemy(cluster, store=None)
    assert isinstance(v, RuleVerdict)
    assert v.matched_rules == ["R2-insufficient-evidence"]


def test_rule3_whitelist_threshold() -> None:
    """Rule 3: TERMS_OF_ART raises threshold from 0.6 → 0.8.

    At distance=0.7 a non-whitelisted term would pass Rule 3 (≥0.6), but
    'consideration' is on TERMS_OF_ART so the 0.8 threshold rejects.
    """
    cluster = _cluster(distance=0.7)  # 'consideration' cluster
    with patch(
        "folio_insights.polysemy.detector.has_framework_conflicting_axiom",
        return_value=True,
    ):
        v = detect_polysemy(cluster, store=None)
    assert isinstance(v, RuleVerdict)
    assert v.decision == "coincidence"
    assert "R3-below-threshold" in v.matched_rules


def test_rule4_homonym_flag() -> None:
    """Rule 4: HOMONYMS force LLM fallback — detector returns LLMVerdict."""
    from folio_insights.polysemy.detector import LLMVerdict, PolysemyVerdict

    cluster = _cluster(term="bar", distance=0.9)  # 'bar' is a HOMONYM
    # Mock the provider resolver path entirely — we just check LLMVerdict type
    canned = PolysemyVerdict(
        decision="homonymy",
        polysemy_vs_homonymy_reasoning="'bar' = drinking establishment vs legal profession",
        rationale="Different etymologies; not a forkable polysemy.",
    )

    class _FakeClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    return canned

    with patch(
        "folio_insights.polysemy.detector.has_framework_conflicting_axiom",
        return_value=True,
    ), patch("instructor.from_provider", return_value=_FakeClient()):
        v = detect_polysemy(cluster, store=None)
    assert isinstance(v, LLMVerdict)
    assert v.decision == "homonymy"
    assert "R4-homonym-flag" in v.matched_rules
