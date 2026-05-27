"""Phase 03 hypothesis property tests (REQ SHARD-02..06; CONTEXT D-09).

Per-subtype generative coverage with example budgets locked in 03-CONTEXT.md D-09:
  SimpleAssertion: 100 examples (envelope inheritance under discriminator)
  DisputedProposition: 300 examples (most fields + nested models + invariants)
  ConflictingAuthorities: 200 examples (8-value + AuthorityPosition coverage)
  Gloss: 200 examples (5-value + IRI format edge cases)
  Hypothesis: 200 examples (3-value + ttl_days boundaries)

Total ≤ 1000 examples; CI runtime budget < 2s. Pattern matches
test_minting_determinism.py:26 (deadline=None for CI flake protection).
"""
from __future__ import annotations

from typing import get_args

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from folio_insights.shards import (
    DISPUTED_EPISTEMIC_STATUS_SUBSET,
    AuthorityPosition,
    ConflictingAuthoritiesShard,
    DisputedPropositionShard,
    GenerationMethod,
    GlossKind,
    GlossShard,
    HypothesisShard,
    Objection,
    ReconciliationStrategy,
    Reply,
    SimpleAssertionShard,
)

from tests.shards.conftest import _sample_shard

pytestmark = pytest.mark.shards


# ── SimpleAssertion: 100 examples (envelope inheritance under discriminator) ──


@settings(max_examples=100, deadline=None)
@given(
    sense=st.text(min_size=1, max_size=200),
    confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
)
def test_simple_assertion_constructs_round_trips(sense: str, confidence: float) -> None:
    """SimpleAssertion: envelope-only round-trip across 100 random shards."""
    shard = _sample_shard(SimpleAssertionShard, sense=sense, confidence=confidence)
    rehydrated = SimpleAssertionShard.model_validate(shard.model_dump())
    assert rehydrated == shard


# ── DisputedProposition: 300 examples (highest — most fields + invariants) ──


# REVIEW IN-03 (Phase 03): derive from the public source-of-truth constant
# rather than hand-typing the 4-tuple. ``sorted`` pins shrink ordering for
# Hypothesis to a deterministic value sequence.
_IN_SUBSET = sorted(DISPUTED_EPISTEMIC_STATUS_SUBSET)


@settings(max_examples=300, deadline=None)
@given(
    utrum=st.text(min_size=1, max_size=200),
    n_objections=st.integers(min_value=1, max_value=5),
    respondeo=st.text(min_size=1, max_size=500),
    epistemic_status=st.sampled_from(_IN_SUBSET),
    # REVIEW IN-04 (Phase 03): draw a list of strengths with size matching
    # n_objections so each Objection gets an INDEPENDENT strength rather than a
    # single homogeneous value. Future invariants depending on cross-objection
    # strength variation (e.g., "≥1 strength > 0.5") will now be exercisable.
    data=st.data(),
)
def test_disputed_proposition_constructs_round_trips(
    utrum: str,
    n_objections: int,
    respondeo: str,
    epistemic_status: str,
    data: st.DataObject,
) -> None:
    """DisputedProposition: round-trip across 300 random shards within D-03 subset."""
    strengths = data.draw(
        st.lists(
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
            min_size=n_objections,
            max_size=n_objections,
        ),
        label="objection_strengths",
    )
    objections = [
        Objection(cites=f"urn:x:{i}", argues=f"objection {i}", strength=strengths[i])
        for i in range(n_objections)
    ]
    sed_contra = Objection(cites="urn:x:sed", argues="sed contra", strength=0.8)
    replies = [
        Reply(objection_index=i, replies_via="distinguo", argument=f"reply {i}")
        for i in range(n_objections)
    ]
    shard = _sample_shard(
        DisputedPropositionShard,
        utrum=utrum,
        objections=objections,
        sed_contra=sed_contra,
        respondeo=respondeo,
        replies=replies,
        epistemic_status=epistemic_status,
    )
    rehydrated = DisputedPropositionShard.model_validate(shard.model_dump())
    assert rehydrated == shard
    assert rehydrated.epistemic_status in _IN_SUBSET


# ── ConflictingAuthorities: 200 examples (8-strategy + AuthorityPosition) ──


# REVIEW IN-03 (Phase 03): derive from the public Literal alias.
_RECONCILIATION_STRATEGIES = list(get_args(ReconciliationStrategy))
# AuthorityPosition.weight is an inline Literal[4] on the nested model (no public
# alias). Hand-typed mirror is acceptable per IN-03 scope.
_AUTHORITY_WEIGHTS = ["binding", "persuasive", "minority", "majority"]


@settings(max_examples=200, deadline=None)
@given(
    strategy=st.sampled_from(_RECONCILIATION_STRATEGIES),
    weight_a=st.sampled_from(_AUTHORITY_WEIGHTS),
    weight_b=st.sampled_from(_AUTHORITY_WEIGHTS),
    note=st.text(min_size=1, max_size=200).filter(lambda s: s.strip() != ""),
)
def test_conflicting_authorities_constructs_round_trips(
    strategy: str, weight_a: str, weight_b: str, note: str,
) -> None:
    """ConflictingAuthorities: round-trip across 200 random shards covering 8 strategies."""
    sic = [AuthorityPosition(authority_iri="urn:x:A", position="A", jurisdiction="us.A", weight=weight_a)]
    non = [AuthorityPosition(authority_iri="urn:x:B", position="B", jurisdiction="us.B", weight=weight_b)]
    shard = _sample_shard(
        ConflictingAuthoritiesShard,
        sic=sic,
        non=non,
        reconciliation_strategy=strategy,
        reconciliation_note=note,
    )
    rehydrated = ConflictingAuthoritiesShard.model_validate(shard.model_dump())
    assert rehydrated == shard
    assert rehydrated.reconciliation_strategy == strategy


# ── Gloss: 200 examples (5-value + IRI format edge cases) ──


# REVIEW IN-03 (Phase 03): derive from the public Literal alias.
_GLOSS_KINDS = list(get_args(GlossKind))


@settings(max_examples=200, deadline=None)
@given(
    kind=st.sampled_from(_GLOSS_KINDS),
    # Generate 32-hex IRI bodies (Phase 04 D-01 hex32 width) that DO NOT collide
    # with the fixture's own shard_iri (which uses a different deterministic hash).
    hex_body=st.text(alphabet="0123456789abcdef", min_size=32, max_size=32),
    gloss_text=st.text(min_size=1, max_size=300).filter(lambda s: s.strip() != ""),
)
def test_gloss_constructs_round_trips(kind: str, hex_body: str, gloss_text: str) -> None:
    """Gloss: round-trip across 200 random shards covering 5 GlossKind values."""
    iri = f"urn:folio:shard/{hex_body}"
    shard = _sample_shard(GlossShard, glosses=iri, gloss_kind=kind, gloss_text=gloss_text)
    # REVIEW WR-02: Discard self-gloss collisions via assume() so Hypothesis
    # generates a replacement (rather than counting the example as a silent
    # pass via bare return, which can mask shrink-driven failures).
    assume(iri != shard.shard_iri)
    rehydrated = GlossShard.model_validate(shard.model_dump())
    assert rehydrated == shard
    assert rehydrated.gloss_kind == kind


# ── Hypothesis: 200 examples (3-value + ttl_days boundaries) ──


# REVIEW IN-03 (Phase 03): derive from the public Literal alias.
_GENERATION_METHODS = list(get_args(GenerationMethod))


@settings(max_examples=200, deadline=None)
@given(
    method=st.sampled_from(_GENERATION_METHODS),
    ttl=st.integers(min_value=1, max_value=10000),
    citation_required=st.booleans(),
)
def test_hypothesis_constructs_round_trips(
    method: str, ttl: int, citation_required: bool,
) -> None:
    """Hypothesis: round-trip across 200 random shards covering 3 methods + ttl boundary."""
    shard = _sample_shard(
        HypothesisShard,
        generation_method=method,
        ttl_days=ttl,
        citation_required=citation_required,
    )
    rehydrated = HypothesisShard.model_validate(shard.model_dump())
    assert rehydrated == shard
    assert rehydrated.ttl_days == ttl
    assert rehydrated.citation_required is citation_required
