"""Rule 3 evidence thresholds, with typed per-framework-pair overrides (Phase 9 U6).

Rule 3 compares a cross-framework centroid distance with a threshold: the
terms-of-art threshold for a term on ``TERMS_OF_ART``, the default otherwise
(``whitelists.py``; Option B, KTD9). Phase 1's Option C, a tuned threshold per
framework pair, is deferred until enough labeled pairs exist to tune it, so
``DEFAULT_THRESHOLDS`` ships with NO overrides. The typed config is here so
that adding one is a reviewed data change, not a code change.

Resolution for one framework pair: the most specific override wins (one that
names the term over one that does not); with none, the whitelist threshold.
Pairs are unordered.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from folio_insights.models.framework import check_framework_id
from folio_insights.polysemy.whitelists import (
    DEFAULT_DISTINGUO_THRESHOLD,
    TERMS_OF_ART,
    TERMS_OF_ART_THRESHOLD,
)


class FrameworkPairThreshold(BaseModel):
    """One override: the Rule 3 threshold for a framework pair (optionally one term)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    framework_a: str
    framework_b: str
    # Cosine distance lives in [0, 2] (prototype_cluster).
    threshold: float = Field(ge=0.0, le=2.0)
    term: str | None = None
    # Why the override exists, and the labeled evidence it was tuned on.
    rationale: str = Field(min_length=1)

    @field_validator("framework_a", "framework_b")
    @classmethod
    def _framework_id(cls, value: str) -> str:
        return check_framework_id(value)

    @model_validator(mode="after")
    def _distinct(self) -> FrameworkPairThreshold:
        if self.framework_a == self.framework_b:
            raise ValueError("a threshold override names two different frameworks")
        return self

    @property
    def pair(self) -> frozenset[str]:
        return frozenset((self.framework_a, self.framework_b))


class ThresholdConfig(BaseModel):
    """The Rule 3 threshold policy: whitelist thresholds plus pair overrides."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    default_threshold: float = Field(default=DEFAULT_DISTINGUO_THRESHOLD, ge=0.0, le=2.0)
    terms_of_art_threshold: float = Field(default=TERMS_OF_ART_THRESHOLD, ge=0.0, le=2.0)
    overrides: tuple[FrameworkPairThreshold, ...] = ()

    @model_validator(mode="after")
    def _unique(self) -> ThresholdConfig:
        seen: set[tuple[frozenset[str], str | None]] = set()
        for override in self.overrides:
            key = (override.pair, override.term)
            if key in seen:
                raise ValueError(
                    f"duplicate threshold override for {sorted(override.pair)} "
                    f"(term {override.term!r})"
                )
            seen.add(key)
        return self

    def base_threshold(self, term: str) -> float:
        return self.terms_of_art_threshold if term in TERMS_OF_ART else self.default_threshold

    def threshold_for(self, term: str, framework_a: str, framework_b: str) -> float:
        """The threshold for one (unordered) framework pair."""
        pair = frozenset((framework_a, framework_b))
        general: float | None = None
        for override in self.overrides:
            if override.pair != pair:
                continue
            if override.term == term:
                return override.threshold
            if override.term is None:
                general = override.threshold
        return self.base_threshold(term) if general is None else general


# Option C deferred: ships EMPTY (tests/polysemy/test_thresholds.py pins this).
DEFAULT_THRESHOLDS = ThresholdConfig()


__all__ = ["DEFAULT_THRESHOLDS", "FrameworkPairThreshold", "ThresholdConfig"]
