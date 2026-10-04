"""Import legacy ``review.db`` proposed-class decisions into the proposal ledger.

Before the proposal ledger, the review API upserted proposed-class decisions
into the ``proposed_class_decisions`` table of the per-corpus ``review.db``,
keyed by label. That table is now read-only legacy (``persistence.review_db``),
and the ledger is the only store of record. ``import_legacy_decisions`` is the
explicit, idempotent bridge. It never runs on startup, and it never changes or
deletes a legacy row.

Rules, per legacy row of the corpus (rows of other corpora are counted only):

* ``pending`` rows decided nothing and are skipped.
* Rows with any other status than ``approved`` or ``rejected``, a note the
  ledger would refuse, or a malformed timestamp are reported as invalid.
* The label resolves to a proposal through the registry
  (``ProposalRegistry.by_label``). A label that resolves to no proposal of the
  corpus is reported as unresolved: the ledger only decides known proposals.
* Several rows that resolve to one proposal (labels that differ only in case or
  punctuation) keep the latest ``reviewed_at`` (then the highest row ID); the
  others are reported as superseded.
* A row already imported (its digest is in a ledger decision's provenance) is
  skipped, so a second run imports nothing.
* A proposal that already has a ledger decision is never overridden: the ledger
  is newer than the legacy table.
* A row that the PII gate refuses is reported and skipped, so one bad note does
  not block the rest.

Everything else is recorded as ONE decision batch through
``ProposalStore.record_decisions`` with ``decided_by`` ``human:legacy-review-db``
and an explicit op_id ``legacy-review-db:<digest of the batch>``. Each item
carries provenance: the legacy source, row ID, row digest and the original
``reviewed_at`` (the ledger's ``decided_at`` is the import's commit time).

Reports name legacy row IDs, never labels or notes.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

import jcs

from folio_insights.proposals.decisions import (
    MAX_PROVENANCE_VALUE_CHARS,
    STATUS_PENDING,
    DecisionInvalid,
    validate_decision,
)
from folio_insights.proposals.registry import KIND_DECISION
from folio_insights.proposals.store import ProposalStore
from folio_insights.storage.errors import PiiRejected

if TYPE_CHECKING:
    from folio_insights.storage import CorpusStorageContext

LEGACY_REVIEWER = "human:legacy-review-db"
LEGACY_SOURCE = "review.db:proposed_class_decisions"
LEGACY_OP_PREFIX = "legacy-review-db:"
LEGACY_STATUSES = frozenset({"approved", "rejected"})


def _digest(data: Any) -> str:
    return hashlib.sha256(jcs.canonicalize(data)).hexdigest()[:32]


def legacy_row_digest(row: Mapping[str, Any]) -> str:
    """A stable digest of one legacy row's decision content (not its row ID)."""
    return _digest({
        "corpus_name": row.get("corpus_name"),
        "concept_label": row.get("concept_label"),
        "status": row.get("status"),
        "reviewer_note": row.get("reviewer_note") or "",
        "reviewed_at": row.get("reviewed_at"),
    })


def imported_legacy_digests(entries: Iterable[Any]) -> set[str]:
    """The legacy row digests already recorded in the ledger's decision provenance."""
    found: set[str] = set()
    for entry in entries:
        if entry.kind != KIND_DECISION:
            continue
        for item in entry.payload.get("decisions", []):
            prov = item.get("provenance") if isinstance(item, Mapping) else None
            if isinstance(prov, Mapping) and prov.get("source") == LEGACY_SOURCE:
                digest = prov.get("legacy_row_digest")
                if isinstance(digest, str):
                    found.add(digest)
    return found


def _sort_key(row: Mapping[str, Any]) -> tuple[str, int]:
    reviewed = row.get("reviewed_at")
    return (reviewed if isinstance(reviewed, str) else "", int(row.get("id") or 0))


async def import_legacy_decisions(
    ctx: CorpusStorageContext,
    rows: Iterable[Mapping[str, Any]],
    *,
    legacy_corpus: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Import the decided legacy rows of ``legacy_corpus`` (default: the context's
    corpus) into the ledger of ``ctx``. Returns a report of row IDs per outcome."""
    legacy_corpus = legacy_corpus or ctx.corpus
    store = ProposalStore(ctx)
    registry = await store.load()
    already = imported_legacy_digests(await ctx.proposals.entries())
    report: dict[str, Any] = {
        "corpus": ctx.corpus,
        "legacy_corpus": legacy_corpus,
        "dry_run": dry_run,
        "rows": 0,
        "other_corpus_rows": 0,
        "imported": [],
        "would_import": [],
        "already_imported": [],
        "already_decided": [],
        "skipped_pending": [],
        "invalid_rows": [],
        "unresolved_rows": [],
        "superseded_rows": [],
        "pii_refused_rows": [],
        "op_id": None,
        "position": None,
        "replayed": False,
    }
    candidates: dict[str, list[tuple[Mapping[str, Any], dict[str, Any]]]] = {}
    for row in rows:
        report["rows"] += 1
        if row.get("corpus_name") != legacy_corpus:
            report["other_corpus_rows"] += 1
            continue
        row_id = row.get("id")
        status = row.get("status")
        if status in (None, "", STATUS_PENDING):
            report["skipped_pending"].append(row_id)
            continue
        reviewed_at = row.get("reviewed_at")
        if (
            status not in LEGACY_STATUSES
            or not isinstance(row_id, int)
            or not isinstance(row.get("concept_label"), str)
            or (reviewed_at is not None and (
                not isinstance(reviewed_at, str) or len(reviewed_at) > MAX_PROVENANCE_VALUE_CHARS
            ))
        ):
            report["invalid_rows"].append(row_id)
            continue
        proposal = registry.by_label(row["concept_label"])
        if proposal is None:
            report["unresolved_rows"].append(row_id)
            continue
        try:
            item = validate_decision(
                {"proposal_id": proposal.proposal_id, "status": status,
                 "note": row.get("reviewer_note") or ""},
                index=0, known=registry.proposals, decided_by=LEGACY_REVIEWER,
            )
        except DecisionInvalid:
            report["invalid_rows"].append(row_id)
            continue
        candidates.setdefault(proposal.proposal_id, []).append((row, item))

    items: list[dict[str, Any]] = []
    provenance: dict[str, dict[str, Any]] = {}
    for pid in sorted(candidates):
        group = sorted(candidates[pid], key=lambda c: _sort_key(c[0]))
        row, item = group[-1]
        report["superseded_rows"].extend(r["id"] for r, _ in group[:-1])
        digest = legacy_row_digest(row)
        if digest in already:
            report["already_imported"].append(row["id"])
            continue
        if registry.proposals[pid].decision.get("status") != STATUS_PENDING:
            report["already_decided"].append(row["id"])
            continue
        prov = {
            "source": LEGACY_SOURCE,
            "legacy_row_id": row["id"],
            "legacy_row_digest": digest,
            "legacy_reviewed_at": row.get("reviewed_at"),
        }
        try:
            ctx.config.pii_gate.check({"decision": item, "provenance": prov})
        except PiiRejected:
            report["pii_refused_rows"].append(row["id"])
            continue
        items.append({k: item[k] for k in ("proposal_id", "status", "note")})
        provenance[pid] = prov
        report["would_import" if dry_run else "imported"].append(row["id"])

    for key in ("imported", "would_import", "already_imported", "already_decided", "skipped_pending",
                "invalid_rows", "unresolved_rows", "superseded_rows", "pii_refused_rows"):
        report[key] = sorted(
            report[key], key=lambda v: (0, v, "") if isinstance(v, int) else (1, 0, str(v))
        )
    if dry_run or not items:
        return report
    op_id = LEGACY_OP_PREFIX + _digest({
        "corpus": ctx.corpus,
        "decisions": items,
        "provenance": provenance,
    })
    result = await store.record_decisions(
        items, op_id=op_id, decided_by=LEGACY_REVIEWER, provenance=provenance
    )
    report.update(op_id=op_id, position=result["position"], replayed=result["replayed"])
    return report


__all__ = [
    "LEGACY_OP_PREFIX",
    "LEGACY_REVIEWER",
    "LEGACY_SOURCE",
    "LEGACY_STATUSES",
    "import_legacy_decisions",
    "imported_legacy_digests",
    "legacy_row_digest",
]
