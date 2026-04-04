"""Review workflow endpoints: approve, reject, edit, bulk-approve, stats."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter()


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
    status: str  # "approved" | "rejected"
    note: str | None = None


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

    db = await get_db_for_corpus(corpus)
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

    db = await get_db_for_corpus(corpus)
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


@router.post("/proposed-classes/{label}/review")
async def review_proposed_class(
    label: str,
    body: ProposedClassReviewRequest,
    corpus: str = Query("default"),
) -> dict[str, Any]:
    """Submit a review decision for a proposed new FOLIO class."""
    from api.main import get_db_for_corpus

    if body.status not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail=f"Invalid status: {body.status}")

    db = await get_db_for_corpus(corpus)
    try:
        now = _now_iso()
        await db.execute(
            """
            INSERT INTO proposed_class_decisions (concept_label, corpus_name, status, reviewer_note, reviewed_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(concept_label, corpus_name) DO UPDATE SET
                status = excluded.status,
                reviewer_note = excluded.reviewer_note,
                reviewed_at = excluded.reviewed_at
            """,
            (label, corpus, body.status, body.note or "", now),
        )
        await db.commit()
        return {"label": label, "status": body.status, "reviewed_at": now}
    finally:
        await db.close()


@router.post("/review/reset")
async def reset_reviews(
    corpus: str = Query("default"),
) -> dict[str, Any]:
    """Delete all review decisions for a corpus (destructive)."""
    from api.main import get_db_for_corpus

    db = await get_db_for_corpus(corpus)
    try:
        cursor = await db.execute(
            "DELETE FROM review_decisions WHERE corpus_name = ?",
            (corpus,),
        )
        deleted = cursor.rowcount
        await db.execute(
            "DELETE FROM proposed_class_decisions WHERE corpus_name = ?",
            (corpus,),
        )
        await db.commit()
        return {"deleted": deleted, "corpus": corpus}
    finally:
        await db.close()
