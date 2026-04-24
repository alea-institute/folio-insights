"""Phase 2 v2.0 Shard subtype stubs (§6.2) — 5 discriminated-union variants; subtype-specific fields land in Phase 3."""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import Field

from folio_insights.shards.envelope import ShardEnvelope


class SimpleAssertionShard(ShardEnvelope):
    """PRD §6.2.1 — bare triple + envelope. Subtype-specific fields land in Phase 3."""
    shard_type: Literal["simple_assertion"] = "simple_assertion"


class DisputedPropositionShard(ShardEnvelope):
    """PRD §6.2.2 — Summa-article stub. utrum/objections/sed_contra/respondeo/replies in Phase 3."""
    shard_type: Literal["disputed_proposition"] = "disputed_proposition"


class ConflictingAuthoritiesShard(ShardEnvelope):
    """PRD §6.2.3 — sic-et-non stub. sic/non/reconciliation_strategy in Phase 3."""
    shard_type: Literal["conflicting_authorities"] = "conflicting_authorities"


class GlossShard(ShardEnvelope):
    """PRD §6.2.4 — layered commentary stub. glosses/gloss_kind/gloss_text in Phase 3."""
    shard_type: Literal["gloss"] = "gloss"


class HypothesisShard(ShardEnvelope):
    """PRD §6.2.5 — candidate stub. generation_method/promotion_requirements/ttl_days in Phase 3."""
    shard_type: Literal["hypothesis"] = "hypothesis"


Shard = Annotated[
    Union[
        SimpleAssertionShard,
        DisputedPropositionShard,
        ConflictingAuthoritiesShard,
        GlossShard,
        HypothesisShard,
    ],
    Field(discriminator="shard_type"),
]


__all__ = [
    "ConflictingAuthoritiesShard",
    "DisputedPropositionShard",
    "GlossShard",
    "HypothesisShard",
    "Shard",
    "SimpleAssertionShard",
]
