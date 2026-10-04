"""Import legacy ``review.db`` proposed-class decisions into the proposal ledger.

Before the proposal ledger, the review API upserted proposed-class decisions
into the ``proposed_class_decisions`` table of the per-corpus ``review.db``,
keyed by label. That table is now read-only legacy (``persistence.review_db``),
and the ledger is the only store of record. ``import_legacy_decisions`` is the
explicit, idempotent bridge. It never runs on startup, and it never changes or
deletes a legacy row.

Rules. Rows of other corpora are counted only. Every row of the corpus is first
grouped by the proposal its label resolves to (``ProposalRegistry.by_label``),
whatever its status, and only the LATEST row of each proposal (by
``reviewed_at``, then row ID) can be imported; the older rows are reported as
superseded. So a reviewer's later reversal is never lost to an older decision:

* A label that resolves to no proposal of the corpus is reported as
  unresolved (the ledger only decides known proposals). A row without an
  integer ID or a text label is invalid and cannot be grouped.
* If the latest row is ``pending``, invalid (a status other than ``approved``
  or ``rejected``, a note the ledger would refuse) or refused by the PII gate,
  the whole proposal is skipped: that row is reported in its category and the
  older rows as superseded. A row whose ``reviewed_at`` is not a short string
  cannot be ordered, so it counts as the latest (and as invalid).
* A latest row already imported (its digest is in a ledger decision's
  provenance) is skipped, so a second run imports nothing.
* A proposal that already has a ledger decision is never overridden: the ledger
  is newer than the legacy table.

Everything else is recorded as ONE decision batch through
``ProposalStore.record_decisions`` with ``decided_by`` ``human:legacy-review-db``,
an explicit op_id ``legacy-review-db:<digest of the batch>`` and
``expected_head`` set to the ledger head the rules were evaluated at. If another
writer moved the ledger in between, the import starts again once from a fresh
load (so a decision recorded meanwhile is respected); a second conflict raises
``LegacyImportConflict`` and nothing is appended. Each item carries provenance:
the legacy source, row ID, row digest and the original ``reviewed_at`` (the
ledger's ``decided_at`` is the import's commit time).

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
from folio_insights.storage.errors import JournalStateChanged, PiiRejected

if TYPE_CHECKING:
    from folio_insights.storage import CorpusStorageContext

LEGACY_REVIEWER = "human:legacy-review-db"
LEGACY_SOURCE = "review.db:proposed_class_decisions"
LEGACY_OP_PREFIX = "legacy-review-db:"
LEGACY_STATUSES = frozenset({"approved", "rejected"})
REPORT_LISTS = (
    "imported", "would_import", "already_imported", "already_decided", "skipped_pending",
    "invalid_rows", "unresolved_rows", "superseded_rows", "pii_refused_rows",
)


class LegacyImportConflict(RuntimeError):
    """Another writer kept moving the proposal ledger during the import; nothing
    was appended. Re-run the import when the ledger is quiet."""


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


def _orderable(reviewed_at: Any) -> bool:
    return reviewed_at is None or (
        isinstance(reviewed_at, str) and len(reviewed_at) <= MAX_PROVENANCE_VALUE_CHARS
    )


def _sort_key(row: Mapping[str, Any]) -> tuple[int, str, int]:
    """Order rows of one proposal: an unorderable timestamp counts as the latest."""
    reviewed = row.get("reviewed_at")
    if not _orderable(reviewed):
        return (1, "", row["id"])
    return (0, reviewed or "", row["id"])


def _classify(
    row: Mapping[str, Any], pid: str, registry: Any, ctx: CorpusStorageContext
) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None]:
    """``(outcome, item, provenance)`` for one resolved row: ``pending``, ``invalid``,
    ``pii`` or ``candidate``."""
    status = row.get("status")
    if status in (None, "", STATUS_PENDING):
        return "pending", None, None
    if status not in LEGACY_STATUSES or not _orderable(row.get("reviewed_at")):
        return "invalid", None, None
    try:
        item = validate_decision(
            {"proposal_id": pid, "status": status, "note": row.get("reviewer_note") or ""},
            index=0, known=registry.proposals, decided_by=LEGACY_REVIEWER,
        )
    except DecisionInvalid:
        return "invalid", None, None
    prov = {
        "source": LEGACY_SOURCE,
        "legacy_row_id": row["id"],
        "legacy_row_digest": legacy_row_digest(row),
        "legacy_reviewed_at": row.get("reviewed_at"),
    }
    try:
        ctx.config.pii_gate.check({"decision": item, "provenance": prov})
    except PiiRejected:
        return "pii", None, None
    return "candidate", {k: item[k] for k in ("proposal_id", "status", "note")}, prov


async def _import_once(
    ctx: CorpusStorageContext, rows: list[Mapping[str, Any]], legacy_corpus: str, dry_run: bool
) -> dict[str, Any]:
    store = ProposalStore(ctx)
    registry = await store.load()
    already = imported_legacy_digests(await ctx.proposals.entries())
    report: dict[str, Any] = {
        "corpus": ctx.corpus, "legacy_corpus": legacy_corpus, "dry_run": dry_run,
        "rows": 0, "other_corpus_rows": 0, **{key: [] for key in REPORT_LISTS},
        "op_id": None, "position": None, "replayed": False,
    }
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        report["rows"] += 1
        if row.get("corpus_name") != legacy_corpus:
            report["other_corpus_rows"] += 1
            continue
        row_id, label = row.get("id"), row.get("concept_label")
        if isinstance(row_id, bool) or not isinstance(row_id, int) or not isinstance(label, str):
            report["invalid_rows"].append(row_id)
            continue
        proposal = registry.by_label(label)
        if proposal is None:
            report["unresolved_rows"].append(row_id)
            continue
        groups.setdefault(proposal.proposal_id, []).append(row)

    category = {"pending": "skipped_pending", "invalid": "invalid_rows",
                "pii": "pii_refused_rows"}
    items: list[dict[str, Any]] = []
    provenance: dict[str, dict[str, Any]] = {}
    for pid in sorted(groups):
        group = sorted(groups[pid], key=_sort_key)
        latest = group[-1]
        report["superseded_rows"].extend(r["id"] for r in group[:-1])
        outcome, item, prov = _classify(latest, pid, registry, ctx)
        if outcome != "candidate":
            report[category[outcome]].append(latest["id"])
            continue
        if prov["legacy_row_digest"] in already:
            report["already_imported"].append(latest["id"])
            continue
        if registry.proposals[pid].decision.get("status") != STATUS_PENDING:
            report["already_decided"].append(latest["id"])
            continue
        items.append(item)
        provenance[pid] = prov
        report["would_import" if dry_run else "imported"].append(latest["id"])

    for key in REPORT_LISTS:
        report[key] = sorted(
            report[key], key=lambda v: (0, v, "") if isinstance(v, int) else (1, 0, str(v))
        )
    if dry_run or not items:
        return report
    op_id = LEGACY_OP_PREFIX + _digest({
        "corpus": ctx.corpus, "decisions": items, "provenance": provenance,
    })
    result = await store.record_decisions(
        items, op_id=op_id, decided_by=LEGACY_REVIEWER, provenance=provenance,
        expected_head=registry.head,
    )
    report.update(op_id=op_id, position=result["position"], replayed=result["replayed"])
    return report


async def import_legacy_decisions(
    ctx: CorpusStorageContext,
    rows: Iterable[Mapping[str, Any]],
    *,
    legacy_corpus: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Import the decided legacy rows of ``legacy_corpus`` (default: the context's
    corpus) into the ledger of ``ctx``. Returns a report of row IDs per outcome.
    Raises ``LegacyImportConflict`` when the ledger moved twice under the import."""
    rows = list(rows)
    legacy_corpus = legacy_corpus or ctx.corpus
    try:
        return await _import_once(ctx, rows, legacy_corpus, dry_run)
    except JournalStateChanged:
        pass  # another writer moved the ledger: evaluate the rules again on fresh state
    try:
        return await _import_once(ctx, rows, legacy_corpus, dry_run)
    except JournalStateChanged:
        raise LegacyImportConflict(
            "the proposal ledger changed twice while the legacy import ran; nothing was "
            "imported. Re-run it when no other writer is active."
        ) from None


__all__ = [
    "LEGACY_OP_PREFIX",
    "LEGACY_REVIEWER",
    "LEGACY_SOURCE",
    "LEGACY_STATUSES",
    "LegacyImportConflict",
    "import_legacy_decisions",
    "imported_legacy_digests",
    "legacy_row_digest",
]
