"""Phase 9 U6 (KTD9): Rule 3 thresholds — Option B now, Option C typed but empty."""
from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from folio_insights.polysemy import whitelists
from folio_insights.polysemy.detector import RuleVerdict, detect_polysemy
from folio_insights.polysemy.fixture_loader import ShardFixture
from folio_insights.polysemy.prototype_cluster import PrototypeCluster
from folio_insights.polysemy.thresholds import (
    DEFAULT_THRESHOLDS,
    FrameworkPairThreshold,
    ThresholdConfig,
)

pytestmark = pytest.mark.polysemy_spike

CL, LA = "us.common_law", "us.louisiana.civil_code"


def test_terms_of_art_threshold_is_option_b() -> None:
    assert whitelists.TERMS_OF_ART_THRESHOLD == 0.75
    assert whitelists.DEFAULT_DISTINGUO_THRESHOLD == 0.6


def test_pair_override_config_ships_empty() -> None:
    """Option C is deferred: no per-pair override ships."""
    assert DEFAULT_THRESHOLDS.overrides == ()
    assert DEFAULT_THRESHOLDS.threshold_for("consideration", CL, LA) == 0.75
    assert DEFAULT_THRESHOLDS.threshold_for("lease", CL, LA) == 0.6


def _override(**kw) -> FrameworkPairThreshold:  # noqa: ANN003
    fields = {"framework_a": CL, "framework_b": LA, "threshold": 0.5, "rationale": "tuned on N pairs"}
    fields.update(kw)
    return FrameworkPairThreshold(**fields)


def test_overrides_are_typed_and_unordered() -> None:
    config = ThresholdConfig(overrides=(
        _override(threshold=0.5),
        _override(threshold=0.4, term="consideration"),
    ))
    assert config.threshold_for("lease", LA, CL) == 0.5           # pair is unordered
    assert config.threshold_for("consideration", CL, LA) == 0.4   # the term-specific one wins
    assert config.threshold_for("lease", CL, "us.ucc") == 0.6     # other pairs untouched


@pytest.mark.parametrize("bad", [
    {"framework_a": "CommonLaw"},              # not a framework ID
    {"framework_b": CL},                       # same framework twice
    {"threshold": 2.5},                        # outside cosine-distance range
    {"rationale": ""},                         # an override says why
])
def test_override_validation(bad: dict) -> None:
    with pytest.raises(ValidationError):
        _override(**bad)


def test_duplicate_override_refused() -> None:
    with pytest.raises(ValidationError):
        ThresholdConfig(overrides=(_override(), _override(framework_a=LA, framework_b=CL)))


def _cluster(distance: float) -> PrototypeCluster:
    shards = {
        fw: [ShardFixture(iri=f"urn:x:{fw}:{i}", framework=fw, source_doc="s",
                          extracted_text="t", axiom_summary=f"a {i}", term="lease") for i in range(3)]
        for fw in (CL, LA)
    }
    return PrototypeCluster(
        cluster_id="fi:PrototypeCluster_t", term="lease", shards_by_framework=shards,
        centroids={fw: np.zeros(384) for fw in shards},
        cross_framework_cosine_distance={(CL, LA): distance, (LA, CL): distance},
    )


def test_detector_applies_the_pair_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "folio_insights.polysemy.detector.has_framework_conflicting_axiom", lambda *a, **k: True
    )
    cluster = _cluster(0.55)
    default = detect_polysemy(cluster, None)
    assert isinstance(default, RuleVerdict) and default.matched_rules == ["R3-below-threshold"]
    lowered = detect_polysemy(cluster, None, thresholds=ThresholdConfig(overrides=(_override(),)))
    assert lowered.decision == "polysemy"
