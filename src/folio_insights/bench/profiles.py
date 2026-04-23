"""Phase-profile configs for the bench generator (D-16).

Each profile tunes:
- Subtype ratio (D-03 — matches v1 real-corpus ratios by default)
- Named-graph composition (advocacy / fre / restatement for gate profile;
  adversarial-skewed subgraphs for phase-16 profile)
- Bitemporal-edit replay depth (deeper for phase-13-storage to stress
  supersession cascades)
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PhaseProfile:
    """Frozen configuration knob set for a single phase-profile."""

    name: str
    # Subtype ratios (sum to 1.0) — D-03 real-corpus-derived defaults
    simple_assertion: float
    disputed: float
    conflicting: float
    gloss: float
    hypothesis: float
    # Corpus mix (sum to 1.0) — named graphs in output N-Quads
    advocacy_share: float
    fre_share: float
    restatement_share: float
    # Replay depth — number of bitemporal-edit rounds per shard
    edit_rounds: int
    # Adversarial-density multiplier (Phase 16 profile cranks this up)
    adversarial_density: float

    @property
    def subtype_weights(self) -> dict[str, float]:
        """Return subtype → weight map (sorted-iteration done at call site)."""
        return {
            "SimpleAssertion": self.simple_assertion,
            "DisputedProposition": self.disputed,
            "ConflictingAuthorities": self.conflicting,
            "Gloss": self.gloss,
            "Hypothesis": self.hypothesis,
        }


# D-03: "Match real-corpus ratios from v1 re-extracted output (expected:
# SimpleAssertion-dominant, ~5-10% Disputed, smaller Conflicting/Gloss/Hypothesis)"
PHASE_0_GATE_PROFILE = PhaseProfile(
    name="phase-0-gate",
    simple_assertion=0.72,
    disputed=0.08,
    conflicting=0.06,
    gloss=0.08,
    hypothesis=0.06,
    advocacy_share=0.50,  # v1 advocacy dominates (real-corpus derived)
    fre_share=0.25,
    restatement_share=0.25,
    edit_rounds=2,
    adversarial_density=0.0,  # zero adversarial at gate baseline
)

PHASE_13_STORAGE_PROFILE = PhaseProfile(
    name="phase-13-storage",
    simple_assertion=0.60,
    disputed=0.15,  # stress supersession chains
    conflicting=0.10,
    gloss=0.08,
    hypothesis=0.07,
    advocacy_share=0.40,
    fre_share=0.30,
    restatement_share=0.30,
    edit_rounds=5,  # deeper bitemporal chains
    adversarial_density=0.0,
)

PHASE_16_ADVERSARIAL_PROFILE = PhaseProfile(
    name="phase-16-sparql-adversarial",
    simple_assertion=0.50,
    disputed=0.20,
    conflicting=0.20,  # high conflicting density for adversarial queries
    gloss=0.05,
    hypothesis=0.05,
    advocacy_share=0.34,
    fre_share=0.33,
    restatement_share=0.33,
    edit_rounds=3,
    adversarial_density=0.10,  # 10% adversarial-shaped triples
)

PROFILES: dict[str, PhaseProfile] = {
    "phase-0-gate": PHASE_0_GATE_PROFILE,
    "phase-13-storage": PHASE_13_STORAGE_PROFILE,
    "phase-16-sparql-adversarial": PHASE_16_ADVERSARIAL_PROFILE,
}
