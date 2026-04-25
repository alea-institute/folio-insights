"""Phase 2 shards test fixture builder — mirrors tests/polysemy/ conftest patterns.

Provides:
  * ``_sample_shard(cls, **overrides)`` — keyword-only fixture-builder returning
    a valid ShardEnvelope subtype instance with sensible defaults for every
    non-defaulted field. Mirrors Phase 1 tests/polysemy/test_fp_rate.py
    ``_sample_record`` idiom.
  * ``_SUBTYPE_TABLE`` — list of (tag, cls) tuples for parametrized tests
    over the 5 discriminated-union subtypes.

Defaults use valid Literal values for every enum-typed field so construction
succeeds without further ceremony; callers pass ``**overrides`` to customize.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from folio_insights.shards import (
    AuthorityPosition,
    ConflictingAuthoritiesShard,
    DisputedPropositionShard,
    GlossShard,
    HypothesisShard,
    Objection,
    Reply,
    ShardEnvelope,
    SimpleAssertionShard,
    Triple,
    mint_shard_iri,
)


# Phase 3 D-02..D-06: required subtype-specific defaults so _sample_shard(cls)
# constructs without callers passing every required field. Callers can still
# override any value via **overrides.
_SUBTYPE_DEFAULTS: dict[type[ShardEnvelope], dict[str, Any]] = {
    SimpleAssertionShard: {},
    DisputedPropositionShard: {
        "utrum": "Whether the default fixture utrum holds?",
        "objections": [
            Objection(
                cites="urn:x:authority/1",
                argues="It seems that the proposition does not hold, because ...",
                strength=0.5,
            ),
        ],
        "sed_contra": Objection(
            cites="urn:x:authority/2",
            argues="On the contrary, the authority states ...",
            strength=0.8,
        ),
        "respondeo": "I respond that the proposition holds, for the following reasons ...",
        "uses_distinctions": [],
        "replies": [
            Reply(
                objection_index=0,
                replies_via="distinguo",
                argument="To the first objection, we reply by distinguishing ...",
            ),
        ],
        # D-03: epistemic_status must be one of the 4-subset; envelope default
        # ("authority_only") is already in-subset, so no override needed here.
    },
    ConflictingAuthoritiesShard: {
        "sic": [
            AuthorityPosition(
                authority_iri="urn:x:authority/A",
                position="Position A holds.",
                jurisdiction="us.federal",
                weight="binding",
            ),
        ],
        "non": [
            AuthorityPosition(
                authority_iri="urn:x:authority/B",
                position="Position B holds.",
                jurisdiction="us.federal",
                weight="persuasive",
            ),
        ],
        "reconciliation_strategy": "sense_distinction",
        "reconciliation_note": "The two authorities use the term in distinct senses.",
    },
    GlossShard: {
        # Use a urn:folio:shard/<16-hex> different from the fixture's own shard_iri
        # so the no-self-glossing check passes (D-05).
        "glosses": "urn:folio:shard/0123456789abcdef",
        "gloss_kind": "clarificatoria",
        "gloss_text": "This gloss clarifies the prior shard's intended scope.",
    },
    HypothesisShard: {
        "generation_method": "combinatorial",
        "promotion_requirements": [],
        # ttl_days defaults to 90, citation_required defaults to True — no override needed.
    },
}


def _sample_shard(
    cls: type[ShardEnvelope] = SimpleAssertionShard,
    **overrides: Any,
) -> ShardEnvelope:
    """Build a valid subtype instance with overridable defaults.

    Keyword-only + explicit defaults + kwargs-override pattern (matches
    tests/polysemy/test_fp_rate.py ``_sample_record``).

    ``shard_iri`` + ``provenance_hash`` are derived from a real
    ``mint_shard_iri`` call so the fixture mirrors the D-02 recipe —
    downstream tests that re-mint will get matching values.
    """
    iri, h = mint_shard_iri("urn:x:fixture", "sample span")
    defaults: dict[str, Any] = {
        "shard_iri": iri,
        "provenance_hash": h,
        "source_uri": "urn:x:fixture",
        "source_span": "sample span",
        "extracted_at": datetime(2026, 4, 24, 12, 0, 0, tzinfo=UTC),
        "first_extractor_did": "did:key:zFixtureExtractor",
        "triple": Triple(subject="s", predicate="p", object="o"),
        "elaborates": [],
        "sense": "default sense",
        "reference": "urn:folio:concept/default",
        "logical_form_imputed": "DEFAULT(s, p, o)",
        "layer": "L3_jurisdictional",
        "predication_mode": "per_se",
        "fork": "analytic",
        "epistemic_status": "authority_only",
        "verification_method": "extractor_assertion",
        "depends_on_axioms": [],
        "depends_on_definitions": [],
        "depends_on_precedents": [],
        "depends_on_shards": [],
        "framework_id": "us.federal.fixture",
        "speech_act": "holding",
        "extractor_version": "0.1.0",
        "extraction_prompt_hash": "0" * 64,
        "extractor_model": "claude-opus-4-7",
        "signatures": [],
        "content_edits": [],
        "confidence": 0.9,
        "bfo_category": "continuant_independent",
        # valid_time_start / valid_time_end / transaction_time / supersedes /
        # superseded_by / contested / contest_votes use model defaults.
    }
    # Phase 3: merge subtype-specific required-field defaults BEFORE caller overrides.
    defaults.update(_SUBTYPE_DEFAULTS.get(cls, {}))
    defaults.update(overrides)
    # shard_type is pinned by each subtype's Literal default; cls() takes it.
    return cls(**defaults)


_SUBTYPE_TABLE: list[tuple[str, type[ShardEnvelope]]] = [
    ("simple_assertion", SimpleAssertionShard),
    ("disputed_proposition", DisputedPropositionShard),
    ("conflicting_authorities", ConflictingAuthoritiesShard),
    ("gloss", GlossShard),
    ("hypothesis", HypothesisShard),
]
