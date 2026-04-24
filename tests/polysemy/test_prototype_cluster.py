"""Per-framework centroid embeddings + cross-framework cosine distances."""
import numpy as np
import pytest

from folio_insights.polysemy.fixture_loader import ShardFixture
from folio_insights.polysemy.prototype_cluster import (
    build_prototype_cluster,
    centroid_distance_signal,
)

pytestmark = pytest.mark.polysemy_spike


def _mk(framework: str, axiom: str, iri_seed: str) -> ShardFixture:
    return ShardFixture(
        iri=f"fi:Shard_{iri_seed}",
        framework=framework,  # type: ignore[arg-type]
        source_doc=f"{framework} source",
        extracted_text=axiom,
        axiom_summary=axiom,
        term="consideration",
    )


def test_centroid_per_framework() -> None:
    shards = [
        _mk("CommonLaw", "Consideration requires bargained-for detriment.", "a1"),
        _mk("CommonLaw", "Consideration is benefit to promisor or detriment to promisee.", "a2"),
        _mk("CommonLaw", "Practical benefit can constitute fresh consideration.", "a3"),
        _mk("Restatement", "Bargained-for exchange of performance.", "b1"),
        _mk("Restatement", "Promissory estoppel substitutes for consideration.", "b2"),
        _mk("Restatement", "Moral consideration binds to prevent injustice.", "b3"),
        _mk("FRE", "Judicial weighing of probative value vs prejudicial effect.", "c1"),
        _mk("FRE", "Consideration of expert methodology reliability.", "c2"),
        _mk("FRE", "Factors considered in relevance determination.", "c3"),
    ]
    cluster = build_prototype_cluster(shards)
    assert len(cluster.centroids) == 3
    for fw, centroid in cluster.centroids.items():
        assert isinstance(centroid, np.ndarray), fw
        assert centroid.shape == (384,), centroid.shape  # all-MiniLM-L6-v2 dim
    # Distance matrix symmetric + bounded
    d_ab = centroid_distance_signal(cluster, "CommonLaw", "FRE")
    d_ba = centroid_distance_signal(cluster, "FRE", "CommonLaw")
    assert d_ab == pytest.approx(d_ba)
    assert 0.0 <= d_ab <= 2.0
    # FRE axioms (evidentiary weighing) should be further from CommonLaw than Restatement is
    d_cl_rest = centroid_distance_signal(cluster, "CommonLaw", "Restatement")
    assert d_ab > d_cl_rest, (
        f"Expected FRE further from CommonLaw ({d_ab:.3f}) than Restatement ({d_cl_rest:.3f})"
    )
    # Evidence-score discipline — this is NOT a polysemy verdict
    assert cluster.cluster_id.startswith("fi:PrototypeCluster_")
