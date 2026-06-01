"""Phase 8 WR-02 regression: _pick_subtype must never select a zero-weight key.

Before the fix, ``_pick_subtype`` used ``if r <= cw`` in its cumulative-weight
loop. When ``r == 0.0`` (which Mersenne Twister can produce) and the first key
had weight 0.0, ``cumweights[0] == 0.0`` and ``0.0 <= 0.0`` was True, so the
zero-weight key was returned. Strict ``r < cw`` excludes that case.

All production profiles use non-zero weights so this was latent, but a future
profile that uses 0.0 as a deactivation flag would silently violate the
weight-proportional selection contract.
"""

from __future__ import annotations

from unittest.mock import patch

from folio_insights.bench.generator import BenchGenerator
from folio_insights.bench.profiles import PhaseProfile


def _make_zero_weight_profile() -> PhaseProfile:
    """A PhaseProfile whose first sorted subtype key has weight 0.0.

    Sorted keys: ConflictingAuthorities, DisputedProposition, Gloss,
    Hypothesis, SimpleAssertion. ConflictingAuthorities is first; set its
    weight to 0.0 and put the remaining mass on Gloss so the loop's
    cumweights start with 0.0 and the zero-weight branch is unambiguous.
    """
    return PhaseProfile(
        name="test-zero-weight",
        simple_assertion=0.0,
        disputed=0.0,
        conflicting=0.0,  # FIRST sorted key, weight 0
        gloss=1.0,
        hypothesis=0.0,
        advocacy_share=1.0,
        fre_share=0.0,
        restatement_share=0.0,
        edit_rounds=1,
        adversarial_density=0.0,
    )


def test_pick_subtype_never_returns_zero_weight_key_when_rng_yields_zero() -> None:
    """WR-02: with r == 0.0 and first-key weight == 0.0, the loop must skip
    that key under strict ``r < cw``. Before the fix, it returned the
    zero-weight key.
    """
    gen = BenchGenerator(seed=42, profile_name="phase-0-gate")
    # Inject a zero-weight profile (PhaseProfile is frozen dataclass, so
    # rebind the private attribute directly).
    object.__setattr__(gen, "_profile", _make_zero_weight_profile())

    # Force rng.random() to return exactly 0.0 — the worst-case input that
    # historically triggered the bug.
    with patch.object(gen._rng, "random", return_value=0.0):
        result = gen._pick_subtype()

    assert result != "ConflictingAuthorities", (
        "WR-02 regression: a zero-weight key MUST NOT be selected even when "
        f"rng.random() returns 0.0 (got {result!r})"
    )
    # Positive assertion: the only non-zero-weight key is Gloss.
    assert result == "Gloss", (
        f"With Gloss=1.0 and all other weights=0.0, _pick_subtype must "
        f"return 'Gloss' for any rng output (got {result!r})"
    )


def test_pick_subtype_never_returns_zero_weight_across_many_draws() -> None:
    """Belt-and-braces: 1000 draws against the zero-weight profile must
    never produce a zero-weight key.
    """
    gen = BenchGenerator(seed=42, profile_name="phase-0-gate")
    object.__setattr__(gen, "_profile", _make_zero_weight_profile())

    zero_keys = {"ConflictingAuthorities", "DisputedProposition",
                 "Hypothesis", "SimpleAssertion"}
    for _ in range(1000):
        result = gen._pick_subtype()
        assert result not in zero_keys, (
            f"Zero-weight key {result!r} was selected — WR-02 regression"
        )
