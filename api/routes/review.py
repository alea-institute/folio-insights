"""Review workflow endpoints: approve, reject, edit, bulk-approve, stats.

Proposed-class decisions are the exception to review.db: they live in the
append-only proposal ledger of the corpus storage root, which these routes
write through ``ProposalStore.record_decisions`` and read from the folded
registry (``api/services/proposals.py``). The review.db table
``proposed_class_decisions`` is read-only legacy; its rows reach the ledger
only through ``scripts/apply_approvals.py import-legacy``.

Signed decisions (drain plan U9, R16, KTD11). Every decision route accepts an optional
``signature`` object in its body: a signed decision (``folio-insights proposals
sign-decision``) verified before anything is stored (``api/services/decision_signatures.py``).
Unit decisions record ``signer_did``, ``signature_verified`` and the authenticated
operator in ``review.db``; proposed-class decisions record them in the proposal ledger.
The signed body must describe the request exactly:

* ``POST /units/{unit_id}/review``: kind ``unit_review``, target the unit ID, verdict the
  status, rationale the note, detail ``{"edited_text": ...}`` when given;
* ``POST /units/bulk-approve``: kind ``unit_bulk_approve``, target ``"*"``, verdict
  ``approved``, detail ``{"unit_ids": [...]}`` or ``{"confidence_min": x}``;
* ``POST /review/reset``: kind ``unit_review_reset``, target ``"*"``, verdict ``reset``;
* ``POST /proposed-classes/{label}/review``: kind ``proposed_class``, target the
  proposal ID, verdict the status, rationale the note, detail ``{"merge_into": ...}`` for
  a merge.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict

from api.auth import WRITE_GUARD
from api.services import decision_signatures as signing
from api.services import proposals as proposal_svc
from folio_insights.persistence.review_db import decision_signature_columns
from folio_insights.proposals.signed_decisions import (
    CORPUS_WIDE_TARGET,
    KIND_UNIT_BULK_APPROVE,
    KIND_UNIT_REVIEW,
    KIND_UNIT_REVIEW_RESET,
    ExpectedDecision,
)

router = APIRouter(dependencies=WRITE_GUARD)


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------

class ReviewRequest(BaseModel):
    status: str  # "approved" | "rejected" | "edited"
    edited_text: str | None = None
    note: str | None = None
    signature: dict[str, Any] | None = None  # optional signed decision (module docstring)


class BulkApproveRequest(BaseModel):
    unit_ids: list[str] | None = None
    confidence_min: float | None = None
    signature: dict[str, Any] | None = None  # optional signed decision (module docstring)


class ResetRequest(BaseModel):
    """Optional body of ``POST /review/reset``: only a signed decision."""

    model_config = ConfigDict(extra="forbid")

    signature: dict[str, Any] | None = None


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
    signature: dict[str, Any] | None = None  # optional signed decision (module docstring)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_SIGNER_COLUMNS = ("decided_by", "signer_did", "signature_verified", "operator")


async def _get_review_status(
    db, unit_id: str, *, signed_columns: bool | None = None
) -> dict[str, Any] | None:
    """Fetch review decision row for a unit. The signed-decision columns are read only
    when the database already has them (reading never migrates)."""
    if signed_columns is None:
        signed_columns = await decision_signature_columns(db, "review_decisions")
    extra = "".join(f", {c}" for c in _SIGNER_COLUMNS) if signed_columns else ""
    cursor = await db.execute(
        "SELECT unit_id, status, edited_text, reviewer_note, reviewed_at" + extra
        + " FROM review_decisions WHERE unit_id = ?",
        (unit_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    review = {
        "unit_id": row[0],
        "status": row[1],
        "edited_text": row[2],
        "reviewer_note": row[3],
        "reviewed_at": row[4],
    }
    if signed_columns:
        review.update(dict(zip(_SIGNER_COLUMNS, row[5:])))
        review["signature_verified"] = bool(review["signature_verified"])
    return review


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
    review = review or {}
    # Who authored the decision (a verified signer) and who submitted it (the operator).
    result["decided_by"] = review.get("decided_by")
    result["signer_did"] = review.get("signer_did")
    result["signature_verified"] = bool(review.get("signature_verified", False))
    result["operator"] = review.get("operator")
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
        signed_columns = await decision_signature_columns(db, "review_decisions")
        results = []
        for unit in units:
            review = await _get_review_status(db, unit["id"], signed_columns=signed_columns)
            results.append(_merge_review(unit, review))
        return results
    finally:
        await db.close()


@router.post("/units/{unit_id}/review")
async def review_unit(
    unit_id: str,
    body: ReviewRequest,
    request: Request,
    corpus: str = Query("default"),
) -> dict[str, Any]:
    """Submit a review decision for a knowledge unit (optionally signed)."""
    from api.main import get_db_for_corpus, get_extraction_data

    # Validate unit exists
    data = get_extraction_data(corpus)
    unit = next((u for u in data.get("units", []) if u["id"] == unit_id), None)
    if unit is None:
        raise HTTPException(status_code=404, detail=f"Unit {unit_id} not found")

    if body.status not in ("approved", "rejected", "edited"):
        raise HTTPException(status_code=400, detail=f"Invalid status: {body.status}")

    verified = await signing.verify_or_refuse(
        body.signature,
        expected=ExpectedDecision(
            kind=KIND_UNIT_REVIEW, corpus=corpus, target=unit_id, verdict=body.status,
            rationale=body.note or "", detail={"edited_text": body.edited_text},
        ),
        policy=signing.policy_or_503(),
    )
    cols = signing.signature_columns(verified, signing.operator_handle(request))

    db = await get_db_for_corpus(corpus)
    try:
        now = _now_iso()
        await signing.prepare_write(db, verified, corpus=corpus, now_iso=now)
        await db.execute(
            """
            INSERT INTO review_decisions (unit_id, corpus_name, status, edited_text, original_text, reviewer_note, reviewed_at, updated_at,
                                          decided_by, signer_did, decision_signature, signature_verified, operator)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(unit_id) DO UPDATE SET
                status = excluded.status,
                edited_text = excluded.edited_text,
                reviewer_note = excluded.reviewer_note,
                reviewed_at = excluded.reviewed_at,
                updated_at = excluded.updated_at,
                decided_by = excluded.decided_by,
                signer_did = excluded.signer_did,
                decision_signature = excluded.decision_signature,
                signature_verified = excluded.signature_verified,
                operator = excluded.operator
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
                cols["decided_by"],
                cols["signer_did"],
                cols["decision_signature"],
                cols["signature_verified"],
                cols["operator"],
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
    request: Request,
    corpus: str = Query("default"),
) -> dict[str, Any]:
    """Batch-approve units by ID list or confidence threshold (optionally signed)."""
    from api.main import get_db_for_corpus, get_extraction_data

    data = get_extraction_data(corpus)
    units = data.get("units", [])

    target_ids: list[str] = []
    if body.unit_ids:
        target_ids = body.unit_ids
        selector: dict[str, Any] = {"unit_ids": list(body.unit_ids)}
    elif body.confidence_min is not None:
        target_ids = [u["id"] for u in units if u.get("confidence", 0) >= body.confidence_min]
        selector = {"confidence_min": body.confidence_min}
    else:
        raise HTTPException(status_code=400, detail="Provide unit_ids or confidence_min")

    verified = await signing.verify_or_refuse(
        body.signature,
        expected=ExpectedDecision(
            kind=KIND_UNIT_BULK_APPROVE, corpus=corpus, target=CORPUS_WIDE_TARGET,
            verdict="approved", detail=selector,
        ),
        policy=signing.policy_or_503(),
    )
    operator = signing.operator_handle(request)
    cols = signing.signature_columns(verified, operator)

    db = await get_db_for_corpus(corpus)
    try:
        now = _now_iso()
        await signing.prepare_write(db, verified, corpus=corpus, now_iso=now)
        for uid in target_ids:
            unit = next((u for u in units if u["id"] == uid), None)
            original_text = unit["text"] if unit else ""
            await db.execute(
                """
                INSERT INTO review_decisions (unit_id, corpus_name, status, original_text, reviewer_note, reviewed_at, updated_at,
                                              decided_by, signer_did, decision_signature, signature_verified, operator)
                VALUES (?, ?, 'approved', ?, '', ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(unit_id) DO UPDATE SET
                    status = 'approved',
                    reviewer_note = '',
                    reviewed_at = excluded.reviewed_at,
                    updated_at = excluded.updated_at,
                    decided_by = excluded.decided_by,
                    signer_did = excluded.signer_did,
                    decision_signature = excluded.decision_signature,
                    signature_verified = excluded.signature_verified,
                    operator = excluded.operator
                """,
                (uid, corpus, original_text, now, now, cols["decided_by"], cols["signer_did"],
                 cols["decision_signature"], cols["signature_verified"], cols["operator"]),
            )
        await db.commit()
        return {"approved_count": len(target_ids), "unit_ids": target_ids,
                **signing.signer_view(verified, operator)}
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
    request: Request,
    corpus: str = Query("default"),
) -> dict[str, Any]:
    """Record a review decision for a proposed new FOLIO class in the proposal ledger.

    The label resolves to the corpus's proposal ID through the registry. The decision is
    recorded by the configured human reviewer through ``ProposalStore.record_decisions``
    (whole-item validation, the PII gate, decision history), so it reaches the
    approved-only backlog. Every refusal writes nothing.

    A ``signature`` (signed decision) is verified by the store before anything is
    appended; a verified signer registered in the signers file is the decision's author
    (``decided_by`` is its handle), otherwise the configured reviewer is. The
    authenticated operator is recorded with the decision either way.
    """
    from folio_insights.proposals import ProposalStore
    from folio_insights.proposals.decisions import INPUT_STATUSES, DecisionInvalid
    from folio_insights.proposals.signed_decisions import DecisionSignatureRefused
    from folio_insights.proposals.store import ReviewerRequired
    from folio_insights.storage.errors import (
        JournalStateChanged,
        OperationIdConflict,
        PiiRejected,
    )
    from folio_insights.storage.proposals import ProposalPayloadRefused

    reviewer_refusal: HTTPException | None = None
    try:
        decided_by: str | None = proposal_svc.configured_reviewer()
    except HTTPException as exc:
        # A signed decision by a registered signer is attributed to that signer and needs
        # no configured reviewer; anything else still gets this refusal (below).
        if body.signature is None:
            raise
        decided_by, reviewer_refusal = None, exc
    policy = signing.policy_or_503()
    if body.signature is None:
        try:
            policy.check_unsigned()
        except DecisionSignatureRefused as exc:
            raise signing.http_refusal(exc) from None
    operator = signing.operator_handle(request)
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
        if body.signature is not None:
            item["signature"] = body.signature
        op_id = explicit_op_id or proposal_svc.derived_op_id(
            ledger, decided_by or "signed", item, registry.head
        )
        try:
            result = await store.record_decisions(
                [item], op_id=op_id, decided_by=decided_by, operator=operator, policy=policy
            )
        except ReviewerRequired:
            raise reviewer_refusal or HTTPException(status_code=403, detail="no reviewer") from None
        except DecisionSignatureRefused as exc:
            raise signing.http_refusal(exc) from None
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
        # Who authored this operation's decision (a verified signer DID, if any) and who
        # submitted it (the authenticated operator).
        "signer_did": current.decision.get("signer_did")
        if pid not in result["superseded_since"] else None,
        "operator": operator,
    }


@router.post("/review/reset")
async def reset_reviews(
    request: Request,
    corpus: str = Query("default"),
    body: ResetRequest | None = Body(None),
) -> dict[str, Any]:
    """Delete all unit review decisions for a corpus (destructive; optionally signed).

    Proposed-class decisions are not reset: they live in the append-only proposal
    ledger, and the legacy ``proposed_class_decisions`` table is read-only. A signed
    reset consumes its nonce in ``review.db`` (the record that it happened, and by whom)."""
    from api.main import get_db_for_corpus

    signature = None if body is None else body.signature
    verified = await signing.verify_or_refuse(
        signature,
        expected=ExpectedDecision(
            kind=KIND_UNIT_REVIEW_RESET, corpus=corpus, target=CORPUS_WIDE_TARGET,
            verdict="reset",
        ),
        policy=signing.policy_or_503(),
    )
    operator = signing.operator_handle(request)

    db = await get_db_for_corpus(corpus)
    try:
        await signing.prepare_write(db, verified, corpus=corpus, now_iso=_now_iso())
        cursor = await db.execute(
            "DELETE FROM review_decisions WHERE corpus_name = ?",
            (corpus,),
        )
        deleted = cursor.rowcount
        await db.commit()
        return {"deleted": deleted, "corpus": corpus, **signing.signer_view(verified, operator)}
    finally:
        await db.close()
