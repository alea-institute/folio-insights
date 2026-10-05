"""``ExtractionHypothesis``: competing extractions of one source span (Phase 9 U3).

PRD §8 P3: "ExtractionHypothesis model; competing extractions coexist". When
extraction yields more than one candidate reading of the same span, each
candidate is a ``HypothesisShard`` and the container keeps them side by side
until review promotes one. Shard IRIs are minted from ``(source_uri,
source_span)`` (D-02), so competing readings of one span share an IRI; the
container therefore distinguishes candidates by their canonical content hash,
never by IRI, and never stores or rewrites a shard itself.

Stdlib + Pydantic only.
"""
from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from folio_insights.revision.content_edit import canonical_content_hash
from folio_insights.shards import HypothesisShard, ShardEnvelope


class ExtractionHypothesis(BaseModel):
    """Competing ``HypothesisShard`` candidates for one source span, ordered by
    canonical content hash (deterministic)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_uri: str = Field(min_length=1)
    source_span: str = Field(min_length=1)
    candidates: tuple[HypothesisShard, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _one_span_distinct_readings(self) -> ExtractionHypothesis:
        for c in self.candidates:
            if (c.source_uri, c.source_span) != (self.source_uri, self.source_span):
                raise ValueError(
                    f"candidate {c.shard_iri} is from a different source span; every "
                    "candidate of an ExtractionHypothesis shares one (source_uri, source_span)"
                )
        hashes = [canonical_content_hash(c) for c in self.candidates]
        if len(set(hashes)) != len(hashes):
            raise ValueError("ExtractionHypothesis candidates must be distinct readings")
        if hashes != sorted(hashes):
            raise ValueError("ExtractionHypothesis candidates must be ordered by content hash")
        return self

    @property
    def content_hashes(self) -> tuple[str, ...]:
        return tuple(canonical_content_hash(c) for c in self.candidates)

    @property
    def competing(self) -> bool:
        """True when more than one reading competes for the span."""
        return len(self.candidates) > 1

    def candidate(self, content_hash: str) -> HypothesisShard:
        """The candidate with ``content_hash`` (what review would promote)."""
        for c in self.candidates:
            if canonical_content_hash(c) == content_hash:
                return c
        raise KeyError(content_hash)

    @classmethod
    def of(cls, shards: Iterable[HypothesisShard]) -> ExtractionHypothesis:
        """Group candidate readings that share one source span; identical
        readings collapse to one."""
        items = list(shards)
        if not items:
            raise ValueError("an ExtractionHypothesis needs at least one HypothesisShard")
        for s in items:
            if not isinstance(s, HypothesisShard):
                raise TypeError(f"{s.shard_iri} is a {s.shard_type} shard, not a hypothesis")
        spans = {(s.source_uri, s.source_span) for s in items}
        if len(spans) != 1:
            raise ValueError("every hypothesis in a group must share one (source_uri, source_span)")
        unique = {canonical_content_hash(s): s for s in items}
        (uri, span), = spans
        return cls(
            source_uri=uri,
            source_span=span,
            candidates=tuple(unique[h] for h in sorted(unique)),
        )


def group_hypotheses(
    shards: Iterable[ShardEnvelope], *, competing_only: bool = False
) -> list[ExtractionHypothesis]:
    """Group every ``HypothesisShard`` in ``shards`` by source span, sorted by
    ``(source_uri, source_span)``; other shard types are ignored."""
    groups: dict[tuple[str, str], list[HypothesisShard]] = {}
    for shard in shards:
        if isinstance(shard, HypothesisShard):
            groups.setdefault((shard.source_uri, shard.source_span), []).append(shard)
    out = [ExtractionHypothesis.of(groups[key]) for key in sorted(groups)]
    return [g for g in out if g.competing] if competing_only else out


__all__ = ["ExtractionHypothesis", "group_hypotheses"]
