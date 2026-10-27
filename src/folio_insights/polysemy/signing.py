"""Bind polysemy review evidence to the existing offline decision signature stack.

The scalar decision detail contains a digest of the complete semantic payload.
Historical readers verify identity and binding again, without expiring a stored
approval against today's clock. Portable certificates have no server commit time.
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import jcs

from folio_insights.proposals.signed_decisions import (
    KIND_POLYSEMY_CERTIFICATION,
    KIND_POLYSEMY_DISPOSITION,
    DecisionSignatureInvalid,
    DecisionSignatureMismatch,
    DecisionSignaturePolicy,
    DecisionSignatureRequired,
    DecisionSignerUnregistered,
    ExpectedDecision,
    SignedDecision,
    check_fresh,
    parse_issued_at,
    parse_signed_decision,
    resolve_policy,
    stored_signature_problem,
    validate_corpus_id,
)

if TYPE_CHECKING:
    from folio_insights.polysemy.dispositions import DispositionRecord
    from folio_insights.polysemy.fp_audit import Certification


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(jcs.canonicalize(value)).hexdigest()


def disposition_fields(record: DispositionRecord) -> dict[str, Any]:
    """Exact input for ``proposals sign-decision``; contains no approval by itself."""
    corpus = validate_corpus_id(record.corpus)
    payload = record.model_dump(mode="json", exclude={
        "signed_decision", "signature", "audit_agreement",
    })
    return {
        "kind": KIND_POLYSEMY_DISPOSITION, "corpus": corpus,
        "target": record.cluster_id, "verdict": record.decision,
        "rationale": record.rationale, "detail": {"payload_sha256": _digest(payload)},
    }


def certification_fields(certification: Certification) -> dict[str, Any]:
    """Bind the certifier, cases, reviewed sample, corpus, time and note."""
    corpus = validate_corpus_id(certification.corpus)
    payload = certification.model_dump(mode="json", exclude={"signed_decision"})
    return {
        "kind": KIND_POLYSEMY_CERTIFICATION, "corpus": corpus,
        "target": certification.cases_sha256, "verdict": "certify",
        "rationale": certification.note, "detail": {"payload_sha256": _digest(payload)},
    }


def _verify(
    evidence: SignedDecision | None, fields: dict[str, Any], author: str,
    policy: DecisionSignaturePolicy | None,
) -> SignedDecision:
    if evidence is None:
        raise DecisionSignatureRequired("a registered reviewer signature is required")
    signed = parse_signed_decision(evidence)
    if author != signed.body.decided_by:
        raise DecisionSignatureMismatch("review author is not the signature's DID")
    problem = stored_signature_problem(
        signed, expected=ExpectedDecision(**fields), signer_did=author,
    )
    if problem:
        raise DecisionSignatureInvalid(problem)
    effective = resolve_policy(fields["corpus"], policy)
    if effective.signer_handle(author) is None:
        raise DecisionSignerUnregistered("the signature is not by a registered reviewer")
    return signed


def verify_disposition(
    record: DispositionRecord, *, policy: DecisionSignaturePolicy | None = None,
    now: datetime | None = None, check_freshness: bool = False,
) -> SignedDecision:
    """Verify registered authority; admission additionally checks freshness."""
    if record.signed_decision is None:
        raise DecisionSignatureRequired("a registered reviewer signature is required")
    signed = _verify(record.signed_decision, disposition_fields(record), record.reviewer_did, policy)
    if check_freshness:
        check_fresh(parse_issued_at(signed.body.issued_at), now or datetime.now(UTC))
    return signed


def disposition_integrity_problem(record: DispositionRecord) -> str | None:
    """Check stored bytes without asserting current reviewer registration."""
    if record.signed_decision is None:
        return None
    try:
        return stored_signature_problem(
            record.signed_decision, expected=ExpectedDecision(**disposition_fields(record)),
            signer_did=record.reviewer_did,
        )
    except ValueError:
        return "stored disposition signature is invalid"


def verify_certification(
    certification: Certification, *, corpus: str | None,
    policy: DecisionSignaturePolicy | None = None,
) -> SignedDecision:
    """Repeatable verification of portable evidence; no nonce is consumed."""
    if certification.signed_decision is None:
        raise DecisionSignatureRequired("a registered reviewer signature is required")
    if corpus is None or certification.corpus != corpus:
        raise DecisionSignatureMismatch("the certificate is not for this corpus")
    return _verify(certification.signed_decision, certification_fields(certification),
                   certification.certified_by, policy)
