"""BFO coverage and distribution report (Phase 9 U7, R10).

Per source: how many shards fall in each of the four envelope categories,
with ``occurrent_event`` also reported as a sub-count of processes (the
Phase 8 fold: events project as ``fi:Process``), and how many assignments were
rules, LLM answers or documented defaults. Coverage is the share of
NON-default assignments; defaults never count.

Provenance persists per corpus as ledger rows (kind ``bfo_assignment``,
latest per shard wins) because the envelope records only the category (KTD2).
A stored shard with no matching assignment row reads ``unrecorded``.
"""
from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import jcs

from folio_insights.bfo.classifier import BFO_CATEGORIES, BfoAssignment

if TYPE_CHECKING:
    from folio_insights.storage.context import CorpusStorageContext

LEDGER_KIND = "bfo_assignment"
PROVENANCE = ("rule", "llm", "default", "unrecorded")


@dataclass(frozen=True)
class BfoRecord:
    shard_iri: str
    source_uri: str
    category: str
    provenance: str  # rule | llm | default | unrecorded


@dataclass
class SourceDistribution:
    source_uri: str
    total: int = 0
    categories: Counter[str] = field(default_factory=Counter)
    provenance: Counter[str] = field(default_factory=Counter)

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_uri": self.source_uri,
            "total": self.total,
            "categories": {c: self.categories.get(c, 0) for c in BFO_CATEGORIES},
            "process_total": self.categories.get("occurrent_process", 0)
            + self.categories.get("occurrent_event", 0),
            "event_subcount": self.categories.get("occurrent_event", 0),
            "provenance": {p: self.provenance.get(p, 0) for p in PROVENANCE},
            "default_share": _share(self.provenance.get("default", 0), self.total),
        }


def _share(part: int, whole: int) -> float:
    return round(part / whole, 6) if whole else 0.0


@dataclass
class BfoReport:
    sources: list[SourceDistribution]

    @property
    def total(self) -> int:
        return sum(s.total for s in self.sources)

    def provenance_count(self, kind: str) -> int:
        return sum(s.provenance.get(kind, 0) for s in self.sources)

    @property
    def coverage(self) -> float:
        """Share of shards typed by a rule or the LLM (defaults excluded)."""
        return _share(self.provenance_count("rule") + self.provenance_count("llm"), self.total)

    @property
    def default_share(self) -> float:
        return _share(self.provenance_count("default"), self.total)

    def as_dict(self) -> dict[str, Any]:
        categories: Counter[str] = Counter()
        for s in self.sources:
            categories.update(s.categories)
        return {
            "total": self.total,
            "coverage": self.coverage,
            "default_share": self.default_share,
            "unrecorded": self.provenance_count("unrecorded"),
            "categories": {c: categories.get(c, 0) for c in BFO_CATEGORIES},
            "event_subcount": categories.get("occurrent_event", 0),
            "sources": [s.as_dict() for s in self.sources],
        }


def build_report(records: Iterable[BfoRecord]) -> BfoReport:
    by_source: dict[str, SourceDistribution] = {}
    for r in records:
        dist = by_source.setdefault(r.source_uri, SourceDistribution(r.source_uri))
        dist.total += 1
        dist.categories[r.category] += 1
        dist.provenance[r.provenance] += 1
    return BfoReport([by_source[k] for k in sorted(by_source)])


def assignment_payload(shard_iri: str, assignment: BfoAssignment) -> dict[str, Any]:
    """The ledger payload of one assignment (no source text)."""
    return {
        "shard_iri": shard_iri,
        "category": assignment.category,
        "spine_class": assignment.spine_class,
        "source": assignment.source,
        "branch": assignment.branch,
        "evidence": list(assignment.evidence),
    }


async def record_assignment(
    ctx: CorpusStorageContext, shard_iri: str, assignment: BfoAssignment
) -> None:
    """Persist an assignment's provenance (idempotent for an identical row)."""
    payload = assignment_payload(shard_iri, assignment)
    digest = hashlib.sha256(jcs.canonicalize(payload)).hexdigest()[:16]
    await ctx.proposals.append(LEDGER_KIND, payload, op_id=f"bfo:{shard_iri}:{digest}")


async def corpus_records(ctx: CorpusStorageContext) -> list[BfoRecord]:
    latest: dict[str, dict[str, Any]] = {}
    for entry in await ctx.proposals.entries():
        if entry.kind == LEDGER_KIND:
            latest[entry.payload["shard_iri"]] = entry.payload
    out: list[BfoRecord] = []
    async for shard in ctx.shards.iter_shards():
        row = latest.get(shard.shard_iri)
        provenance = (
            row["source"] if row is not None and row["category"] == shard.bfo_category
            else "unrecorded"
        )
        out.append(BfoRecord(shard.shard_iri, shard.source_uri, shard.bfo_category, provenance))
    return out


async def corpus_report(ctx: CorpusStorageContext) -> BfoReport:
    return build_report(await corpus_records(ctx))


__all__ = [
    "BfoRecord",
    "BfoReport",
    "LEDGER_KIND",
    "SourceDistribution",
    "assignment_payload",
    "build_report",
    "corpus_records",
    "corpus_report",
    "record_assignment",
]
