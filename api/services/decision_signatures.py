"""Signed review decisions for the API routes (drain plan U9, R16, KTD11).

The review routes (``api/routes/review.py``) and the discovery task-review routes
(``api/routes/discovery.py``) accept an optional ``signature`` object in their body: a
``folio_insights.proposals.signed_decisions.SignedDecision``. This module turns the
library's policy and verification into HTTP answers and writes the signed-decision
columns of ``review.db`` (``folio_insights.persistence.review_db``).

Operator authentication (``api/auth.py``, ``request.state.operator``) and decision
authorship are different facts and both are recorded: the operator handle is who
submitted the write, the signer DID is who authored the decision.

Status codes (every refusal writes nothing):

* 400: the signature object is malformed, or the signed body does not describe this
  request (another unit, verdict, note, corpus or kind);
* 403: the signature does not verify, was issued outside the signing skew of server
  time, comes from a DID the signers file does not list, or the server requires signed
  decisions and the request carried none;
* 409: the signed decision's nonce was already used (a replay);
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
    if isinstance(exc, (DecisionSignatureMalformed, DecisionSignatureMismatch)):
        status = 400
    elif isinstance(exc, DecisionReplayed):
        status = 409
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
    """The signed-decision column values of one decision row (unsigned: verified 0)."""
    if verified is None:
        return {"decided_by": None, "signer_did": None, "decision_signature": None,
                "signature_verified": 0, "operator": operator}
    return {
        "decided_by": verified.signer_handle,
        "signer_did": verified.signer_did,
        "decision_signature": json.dumps(verified.signed.to_record(), sort_keys=True),
        "signature_verified": 1,
        "operator": operator,
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
        "decided_by": None if verified is None else verified.signer_handle,
        "operator": operator,
    }


__all__ = [
    "http_refusal",
    "operator_handle",
    "policy_or_503",
    "prepare_write",
    "signature_columns",
    "signer_view",
    "verify_or_refuse",
]
