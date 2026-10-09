"""Review workflow endpoints: approve, reject, edit, bulk-approve, stats.

Proposed-class decisions are the exception to review.db: they live in the
append-only proposal ledger of the corpus storage root, which these routes
write through ``ProposalStore.record_decisions`` and read from the folded
registry (``api/services/proposals.py``). The review.db table
``proposed_class_decisions`` is read-only legacy; its rows reach the ledger
only through ``scripts/apply_approvals.py import-legacy``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from api.auth import WRITE_GUARD
from api.services import proposals as proposal_svc

router = APIRouter(dependencies=WRITE_GUARD)


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------

class ReviewRequest(BaseModel):
    status: str  # "approved" | "rejected" | "edited"
    edited_text: str | None = None
    note: str | None = None


class BulkApproveRequest(BaseModel):
    unit_ids: list[str] | None = None
    confidence_min: float | None = None


class ProposedClassReviewRequest(BaseModel):
    """A decision on one proposed class. The reviewer is server configuration, so a
    body that names ``decided_by`` (or any other extra field) is refused."""

    model_config = ConfigDict(extra="forbid")

    # "approve"/"approved", "reject"/"rejected", "merge"/"merged" (with merge_into),
    # or "needs_work".
    status: str
    note: str | None = None
    merge_into: str | None = None  # the surviving proposal ID of a merge
    op_id: str | None = None  # client idempotency key; a retry with it replays


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _get_review_status(db, unit_id: str) -> dict[str, Any] | None:
    """Fetch review decision row for a unit."""
    cursor = await db.execute(
        "SELECT unit_id, status, edited_text, reviewer_note, reviewed_at "
        "FROM review_decisions WHERE unit_id = ?",
        (unit_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return {
        "unit_id": row[0],
        "status": row[1],
        "edited_text": row[2],
        "reviewer_note": row[3],
        "reviewed_at": row[4],
    }


def _merge_review(unit: dict[str, Any], review: dict[str, Any] | None) -> dict[str, Any]:
    """Merge review decision into unit dict."""
    result = dict(unit)
    if review:
        result["review_status"] = review["status"]
        result["edited_text"] = review.get("edited_text")
        result["reviewer_note"] = review.get("reviewer_note", "")
        result["reviewed_at"] = review.get("reviewed_at")
    else:
        result["review_status"] = "unreviewed"
        result["edited_text"] = None
        result["reviewer_note"] = ""
        result["reviewed_at"] = None
    return result


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/units")
async def list_units(
    corpus: str = Query("default"),
    concept_iri: str | None = Query(None),
    confidence: str | None = Query(None),
) -> list[dict[str, Any]]:
    """Return knowledge units, optionally filtered by concept IRI and confidence band."""
    from api.main import get_db_for_corpus, get_extraction_data

    data = get_extraction_data(corpus)
    units = data.get("units", [])

    # Filter by concept IRI (with special virtual IRIs)
    if concept_iri:
        if concept_iri == "__all__":
            pass  # Return all units - no filtering
        elif concept_iri == "__untagged__":
            units = [
                u for u in units
                if not u.get("folio_tags")
            ]
        else:
            units = [
                u for u in units
                if any(t["iri"] == concept_iri for t in u.get("folio_tags", []))
            ]

    # Filter by confidence band
    if confidence:
        if confidence == "high":
            units = [u for u in units if u.get("confidence", 0) >= 0.8]
        elif confidence == "medium":
            units = [u for u in units if 0.5 <= u.get("confidence", 0) < 0.8]
        elif confidence == "low":
            units = [u for u in units if u.get("confidence", 0) < 0.5]

    # Merge review status from SQLite
    db = await get_db_for_corpus(corpus)
    try:
        results = []
        for unit in units:
            review = await _get_review_status(db, unit["id"])
            results.append(_merge_review(unit, review))
        return results
    finally:
        await db.close()


@router.post("/units/{unit_id}/review")
async def review_unit(
    unit_id: str,
    body: ReviewRequest,
    corpus: str = Query("default"),
) -> dict[str, Any]:
    """Submit a review decision for a knowledge unit."""
    from api.main import get_db_for_corpus, get_extraction_data

    # Validate unit exists
    data = get_extraction_data(corpus)
    unit = next((u for u in data.get("units", []) if u["id"] == unit_id), None)
    if unit is None:
        raise HTTPException(status_code=404, detail=f"Unit {unit_id} not found")

    if body.status not in ("approved", "rejected", "edited"):
        raise HTTPException(status_code=400, detail=f"Invalid status: {body.status}")

    db = await get_db_for_corpus(corpus, writable=True)
    try:
        now = _now_iso()
        await db.execute(
            """
            INSERT INTO review_decisions (unit_id, corpus_name, status, edited_text, original_text, reviewer_note, reviewed_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(unit_id) DO UPDATE SET
                status = excluded.status,
                edited_text = excluded.edited_text,
                reviewer_note = excluded.reviewer_note,
                reviewed_at = excluded.reviewed_at,
                updated_at = excluded.updated_at
            """,
            (
                unit_id,
                corpus,
                body.status,
                body.edited_text,
                unit["text"],
                body.note or "",
                now,
                now,
            ),
        )
        await db.commit()

        review = await _get_review_status(db, unit_id)
        return _merge_review(unit, review)
    finally:
        await db.close()


@router.post("/units/bulk-approve")
async def bulk_approve(
    body: BulkApproveRequest,
    corpus: str = Query("default"),
) -> dict[str, Any]:
    """Batch-approve units by ID list or confidence threshold."""
    from api.main import get_db_for_corpus, get_extraction_data

    data = get_extraction_data(corpus)
    units = data.get("units", [])

    target_ids: list[str] = []
    if body.unit_ids:
        target_ids = body.unit_ids
    elif body.confidence_min is not None:
        target_ids = [u["id"] for u in units if u.get("confidence", 0) >= body.confidence_min]
    else:
        raise HTTPException(status_code=400, detail="Provide unit_ids or confidence_min")

    db = await get_db_for_corpus(corpus, writable=True)
    try:
        now = _now_iso()
        for uid in target_ids:
            unit = next((u for u in units if u["id"] == uid), None)
            original_text = unit["text"] if unit else ""
            await db.execute(
                """
                INSERT INTO review_decisions (unit_id, corpus_name, status, original_text, reviewer_note, reviewed_at, updated_at)
                VALUES (?, ?, 'approved', ?, '', ?, ?)
                ON CONFLICT(unit_id) DO UPDATE SET
                    status = 'approved',
                    reviewer_note = '',
                    reviewed_at = excluded.reviewed_at,
                    updated_at = excluded.updated_at
                """,
                (uid, corpus, original_text, now, now),
            )
        await db.commit()
        return {"approved_count": len(target_ids), "unit_ids": target_ids}
    finally:
        await db.close()


@router.get("/review/stats")
async def review_stats(
    corpus: str = Query("default"),
) -> dict[str, Any]:
    """Return review progress statistics."""
    from api.main import get_db_for_corpus, get_extraction_data

    data = get_extraction_data(corpus)
    units = data.get("units", [])
    total = len(units)

    db = await get_db_for_corpus(corpus)
    try:
        cursor = await db.execute(
            "SELECT status, COUNT(*) FROM review_decisions WHERE corpus_name = ? GROUP BY status",
            (corpus,),
        )
        rows = await cursor.fetchall()
        counts = {row[0]: row[1] for row in rows}

        approved = counts.get("approved", 0)
        rejected = counts.get("rejected", 0)
        edited = counts.get("edited", 0)
        reviewed = approved + rejected + edited
        unreviewed = total - reviewed

        # Counts by confidence band
        high = len([u for u in units if u.get("confidence", 0) >= 0.8])
        medium = len([u for u in units if 0.5 <= u.get("confidence", 0) < 0.8])
        low = len([u for u in units if u.get("confidence", 0) < 0.5])

        return {
            "total": total,
            "approved": approved,
            "rejected": rejected,
            "edited": edited,
            "unreviewed": unreviewed,
            "by_confidence": {"high": high, "medium": medium, "low": low},
        }
    finally:
        await db.close()


# Every proposed-class route needs the operator's explicit opt-in and a local request
# (api/services/proposals.py, require_local_opt_in), in addition to the router's operator
# token check on writes (api/auth.py): decisions are attributed to the configured reviewer.
_LOCAL_ONLY = [Depends(proposal_svc.require_local_opt_in)]


@router.get("/proposed-classes", dependencies=_LOCAL_ONLY)
async def list_proposed_classes(
    corpus: str = Query("default"),
) -> dict[str, Any]:
    """Every proposed class of the corpus with its current decision, from the ledger
    (read-only connection; no storage context or projection)."""
    ledger = proposal_svc.ledger_corpus(corpus)
    registry = await proposal_svc.load_registry_readonly(ledger)
    return proposal_svc.registry_view(ledger, registry)


@router.get("/proposed-classes/{label:path}", dependencies=_LOCAL_ONLY)
async def get_proposed_class(
    label: str,
    corpus: str = Query("default"),
) -> dict[str, Any]:
    """One proposed class (resolved by label) with its current decision, from the ledger."""
    ledger = proposal_svc.ledger_corpus(corpus)
    registry = await proposal_svc.load_registry_readonly(ledger)
    proposal = None if registry is None else registry.by_label(label)
    if proposal is None:
        raise HTTPException(
            status_code=404, detail="no proposed class with this label in this corpus"
        )
    return {"corpus": ledger, **proposal_svc.proposal_view(proposal)}


@router.post("/proposed-classes/{label:path}/review", dependencies=_LOCAL_ONLY)
async def review_proposed_class(
    label: str,
    body: ProposedClassReviewRequest,
    corpus: str = Query("default"),
) -> dict[str, Any]:
    """Record a review decision for a proposed new FOLIO class in the proposal ledger.

    The label resolves to the corpus's proposal ID through the registry. The decision is
    recorded by the configured human reviewer through ``ProposalStore.record_decisions``
    (whole-item validation, the PII gate, decision history), so it reaches the
    approved-only backlog. Every refusal writes nothing.
    """
    from folio_insights.proposals import ProposalStore
    from folio_insights.proposals.decisions import INPUT_STATUSES, DecisionInvalid
    from folio_insights.storage.errors import (
        JournalStateChanged,
        OperationIdConflict,
        PiiRejected,
    )
    from folio_insights.storage.proposals import ProposalPayloadRefused

    decided_by = proposal_svc.configured_reviewer()
    ledger = proposal_svc.ledger_corpus(corpus)
    if body.status not in INPUT_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status: must be one of {sorted(INPUT_STATUSES)}; nothing was recorded",
        )
    explicit_op_id = None if body.op_id is None else proposal_svc.client_op_id(body.op_id)
    # Resolve the label read-only first: an unknown label (or corpus) never opens the
    # storage context or the projection.
    known = await proposal_svc.load_registry_readonly(ledger)
    if known is None or known.by_label(label) is None:
        raise HTTPException(
            status_code=404,
            detail="no proposed class with this label in this corpus; nothing was recorded",
        )

    async with proposal_svc.open_ledger(ledger) as ctx:
        if ctx is None:
            raise HTTPException(
                status_code=404,
                detail="no proposed class with this label in this corpus; nothing was recorded",
            )
        store = ProposalStore(ctx)
        registry = await store.load()
        proposal = registry.by_label(label)
        if proposal is None:
            raise HTTPException(
                status_code=404,
                detail="no proposed class with this label in this corpus; nothing was recorded",
            )
        pid = proposal.proposal_id
        item: dict[str, Any] = {"proposal_id": pid, "status": body.status,
                                "note": body.note or ""}
        if body.merge_into is not None:
            item["merge_into"] = body.merge_into
        op_id = explicit_op_id or proposal_svc.derived_op_id(
            ledger, decided_by, item, registry.head
        )
        try:
            result = await store.record_decisions([item], op_id=op_id, decided_by=decided_by)
        except DecisionInvalid as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except (PiiRejected, ProposalPayloadRefused) as exc:
            raise HTTPException(
                status_code=422, detail=f"refused: {exc}; nothing was recorded"
            ) from None
        except OperationIdConflict:
            raise HTTPException(
                status_code=409,
                detail="op_id was already used for a different decision; nothing was recorded",
            ) from None
        except JournalStateChanged:
            raise HTTPException(
                status_code=409,
                detail="the proposal ledger changed during the request; retry. Nothing was recorded",
            ) from None
        current = (await store.load()).get(pid)

    outcome = result["results"][pid]
    return {
        "label": label,
        "corpus": ledger,
        "proposal_id": pid,
        # The decision as of this operation (the original outcome on a replay).
        "status": outcome["status"],
        "decided_at": outcome["decided_at"],
        "reviewed_at": outcome["decided_at"],
        # The current decision, which a later operation may have changed since.
        "current_status": outcome["current_status"],
        "current_decided_at": outcome["current_decided_at"],
        "superseded": pid in result["superseded_since"],
        "decision": proposal_svc.decision_view(current.decision),
        "recorded": bool(result["recorded"]),
        "replayed": result["replayed"],
        "op_id": op_id,
        "ledger_position": result["position"],
    }


@router.post("/review/reset")
async def reset_reviews(
    corpus: str = Query("default"),
) -> dict[str, Any]:
    """Delete all unit review decisions for a corpus (destructive).

    Proposed-class decisions are not reset: they live in the append-only proposal
    ledger, and the legacy ``proposed_class_decisions`` table is read-only."""
    from api.main import get_db_for_corpus

    db = await get_db_for_corpus(corpus, writable=True)
    try:
        cursor = await db.execute(
            "DELETE FROM review_decisions WHERE corpus_name = ?",
            (corpus,),
        )
        deleted = cursor.rowcount
        await db.commit()
        return {"deleted": deleted, "corpus": corpus}
    finally:
        await db.close()
