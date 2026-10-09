"""Signed review decisions for the API routes (drain plan U9, R16, KTD11).

The review routes (``api/routes/review.py``) and the discovery task-review routes
(``api/routes/discovery.py``) accept an optional ``signature`` object in their body: a
``folio_insights.proposals.signed_decisions.SignedDecision``. This module turns the
library's policy and verification into HTTP answers and writes the signed-decision
columns of ``review.db`` (``folio_insights.persistence.review_db``).

Operator authentication (``api/auth.py``, ``request.state.operator``) and decision
authorship are different facts and both are recorded: the operator handle is who
submitted the write, the signer DID is who authored the decision. Two more facts are kept
apart in every view: ``signature_verified`` (the signature is cryptographically valid for
its did:key) and ``signer_registered`` (a signers file listed that DID when the decision
was recorded; always false without a signers file, where any self-generated key
verifies).

Which routes need a signature when ``FOLIO_INSIGHTS_REQUIRE_SIGNED_DECISIONS=1``: every
route that changes review or task decision state. That is the unit routes (review,
bulk approve, reset) and proposed-class reviews (``api/routes/review.py``) and the
discovery routes that review, bulk-approve, create or delete a task, edit the task
hierarchy or resolve a contradiction (``api/routes/discovery.py``, kinds
``task_review``, ``task_bulk_approve``, ``task_create``, ``task_delete``,
``hierarchy_edit``, ``contradiction_resolve``). Out of scope, because they record no
reviewer verdict: ``PUT /source-authority`` (source metadata an operator configures,
not a decision about a unit or task), discovery and processing runs (``persist_discovery``
inserts tasks, links and contradictions but never sets a review status or a resolution,
and keeps existing decisions), uploads, and ``DELETE /corpora/{id}`` (removes the whole
corpus directory, an operator administration action guarded by operator
authentication; it records no decision a signature could attest).

Status codes (every refusal writes nothing):

* 400: the signature object is malformed, or the signed body does not describe this
  request (another unit, verdict, note, corpus or kind);
* 403: the signature does not verify, was issued outside the signing skew of server
  time, comes from a DID the signers file does not list, or the server requires signed
  decisions and the request carried none;
* 409: the signed decision's nonce was already used (a replay), or the signed selection
  of a bulk approval by threshold is not what the server would approve now
  (``DecisionSelectionChanged``);
* 503: the signed-decision configuration is unusable (signatures required without a
  signers file, or a refused signers file); the server log names the problem.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, Request

from folio_insights.persistence.review_db import (
    DecisionNonceReused,
    claim_decision_nonce,
    ensure_decision_signature_schema,
)
from folio_insights.proposals.signed_decisions import (
    DecisionPolicyMisconfigured,
    DecisionReplayed,
    DecisionSelectionChanged,
    DecisionSignatureMalformed,
    DecisionSignatureMismatch,
    DecisionSignaturePolicy,
    DecisionSignatureRefused,
    ExpectedDecision,
    VerifiedDecision,
    load_policy,
    operator_record,
    verify_signed_decision,
)

logger = logging.getLogger(__name__)

_MISCONFIGURED_DETAIL = (
    "Signed-decision configuration is unusable on this server; the server log names the "
    "problem. Nothing was recorded."
)


def policy_or_503() -> DecisionSignaturePolicy:
    """The signed-decision policy, or a 503 refusal when its configuration is unusable."""
    try:
        return load_policy()
    except DecisionPolicyMisconfigured as exc:
        logger.error("signed decisions: %s", exc)
        raise HTTPException(status_code=503, detail=_MISCONFIGURED_DETAIL) from None


def http_refusal(exc: DecisionSignatureRefused) -> HTTPException:
    """The HTTP answer for a refused (or missing required) signature."""
    if isinstance(exc, (DecisionReplayed, DecisionSelectionChanged)):
        status = 409
    elif isinstance(exc, (DecisionSignatureMalformed, DecisionSignatureMismatch)):
        status = 400
    else:
        status = 403
    return HTTPException(status_code=status, detail=str(exc))


def operator_handle(request: Request) -> str | None:
    """How the authenticated operator of this request is recorded (or ``None``)."""
    operator = getattr(request.state, "operator", None)
    return operator_record(getattr(operator, "handle", None))


async def verify_or_refuse(
    signature: Any,
    *,
    expected: ExpectedDecision,
    policy: DecisionSignaturePolicy,
) -> VerifiedDecision | None:
    """``None`` for an allowed unsigned decision, the verified decision for a valid
    signature, or an ``HTTPException``. Server time is the current UTC time."""
    try:
        if signature is None:
            policy.check_unsigned()
            return None
        return await verify_signed_decision(
            signature, expected=expected, policy=policy, now=datetime.now(UTC)
        )
    except DecisionSignatureRefused as exc:
        raise http_refusal(exc) from None


def signature_columns(
    verified: VerifiedDecision | None, operator: str | None
) -> dict[str, Any]:
    """The signed-decision column values of one decision row (unsigned: verified 0,
    registered 0), keyed like ``review_db.DECISION_SIGNATURE_COLUMNS``."""
    if verified is None:
        return {"decided_by": None, "signer_did": None, "decision_signature": None,
                "signature_verified": 0, "signer_registered": 0, "operator": operator}
    return {
        "decided_by": verified.signer_handle,
        "signer_did": verified.signer_did,
        "decision_signature": json.dumps(verified.signed.to_record(), sort_keys=True),
        "signature_verified": 1,
        "signer_registered": 1 if verified.signer_registered else 0,
        "operator": operator,
    }


#: Every signed-decision column a write sets, in ``review_db.DECISION_SIGNATURE_COLUMNS``
#: order: ``", ".join(WRITE_COLUMNS)`` for an INSERT, ``set_clause()`` for an UPDATE and
#: ``write_args(cols)`` for the values.
WRITE_COLUMNS = ("decided_by", "signer_did", "decision_signature", "signature_verified",
                 "signer_registered", "operator")


def set_clause() -> str:
    """``"decided_by = ?, ..., operator = ?"`` for an UPDATE of every signed column."""
    return ", ".join(f"{c} = ?" for c in WRITE_COLUMNS)


def write_args(cols: dict[str, Any]) -> tuple[Any, ...]:
    """The values of ``signature_columns(...)`` in ``WRITE_COLUMNS`` order."""
    return tuple(cols[c] for c in WRITE_COLUMNS)


#: The signed-decision columns a read view exposes (the stored signature JSON is not).
VIEW_COLUMNS = ("decided_by", "signer_did", "signature_verified", "signer_registered",
                "operator")


def authorship_view(row: Any, present: tuple[str, ...]) -> dict[str, Any]:
    """The authorship fields of a stored decision row for an API read.

    ``present`` is ``review_db.present_signature_columns`` of the row's table; a column
    the database does not have yet reads as unsigned (``None`` / ``False``)."""
    def get(name: str) -> Any:
        return row[name] if name in present else None

    return {
        "decided_by": get("decided_by"),
        "signer_did": get("signer_did"),
        "signature_verified": bool(get("signature_verified") or 0),
        "signer_registered": bool(get("signer_registered") or 0),
        "operator": get("operator"),
    }


async def prepare_write(
    db: Any, verified: VerifiedDecision | None, *, corpus: str, now_iso: str
) -> None:
    """Inside the decision write's transaction: migrate the signed-decision columns and,
    for a signed decision, consume its nonce. A reused nonce rolls the transaction back
    and answers 409."""
    await ensure_decision_signature_schema(db)
    if verified is None:
        return
    body = verified.signed.body
    try:
        await claim_decision_nonce(
            db,
            signer_did=verified.signer_did,
            nonce=body.nonce,
            body_hash=verified.body_hash,
            corpus_name=corpus,
            kind=body.kind,
            target=body.target,
            used_at=now_iso,
        )
    except DecisionNonceReused as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail=f"{exc}. Sign it again. Nothing was recorded"
        ) from None


def signer_view(verified: VerifiedDecision | None, operator: str | None) -> dict[str, Any]:
    """The authorship fields a write route returns."""
    return {
        "signer_did": None if verified is None else verified.signer_did,
        "signature_verified": verified is not None,
        "signer_registered": verified is not None and verified.signer_registered,
        "decided_by": None if verified is None else verified.signer_handle,
        "operator": operator,
    }


__all__ = [
    "VIEW_COLUMNS",
    "WRITE_COLUMNS",
    "set_clause",
    "write_args",
    "authorship_view",
    "http_refusal",
    "operator_handle",
    "policy_or_503",
    "prepare_write",
    "signature_columns",
    "signer_view",
    "verify_or_refuse",
]
