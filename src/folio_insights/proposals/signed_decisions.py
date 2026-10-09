"""Signed review decisions (drain plan U9, R16, KTD11).

A review decision (a proposed-class verdict, a unit review, a task review, a bulk
approval or a review reset) may carry a signature by a DID key. A signed decision is
verified before it is stored, and the store records the verified signer
(``signer_did``) next to ``signature_verified``. ``FOLIO_INSIGHTS_REQUIRE_SIGNED_DECISIONS=1``
makes a server refuse every unsigned decision.

Wire format (``SignedDecision``)::

    {"body": {"format": "folio-insights/review-decision/v1",
              "kind": "proposed_class", "corpus": "C", "target": "PC-...",
              "verdict": "approved", "rationale": "...", "detail": {},
              "decided_by": "did:key:z...", "nonce": "<32 hex>",
              "issued_at": "2026-10-09T12:00:00.000000Z"},
     "signature": {"did": "did:key:z...", "signed_at": "2026-10-09T12:00:00Z",
                   "signature": "<base64url ed25519>",
                   "over_content_hash": "<sha256 hex of the JCS body>",
                   "signing_key_id": "did:key:z...#z...",
                   "did_doc_snapshot_at": null}}

* The signed bytes are the SHA-256 hex of the RFC 8785 (JCS) canonical ``body``,
  exactly as ``governance.events._BaseEvent.signature_payload`` hashes an event. The
  body's ``format`` marker separates a decision signature from every other signed
  payload of this code base. Signing and verification go through the governance stack's
  own primitives, ``identity.signer.sign_attestation`` and
  ``identity.verifier.verify_attestation``; nothing here implements a signature scheme.
* ``DecisionSignature`` carries the ``AttestedSignature`` fields except ``action``. No
  ``SignedAction`` value names a review decision, and adding one would change the shard
  envelope's public ``AttestedSignature.action`` literal (the same reason
  ``frameworks.registry`` keeps framework registrations out of it). The ``action`` an
  ``AttestedSignature`` needs to reach the primitives (``_CARRIER_ACTION``) is not part
  of the signed bytes, and a decision signature can never be mistaken for a shard
  attestation: it signs the hash of a decision body, never a shard's content hash.
* **Authorship.** ``body.decided_by`` must be the signer DID, so the signer asserts
  authorship of exactly this decision. Only ``did:key`` signers are accepted: they
  verify offline, and a server never fetches a DID document named by request input.
* **Freshness and replay.** ``issued_at`` must sit within
  ``governance.clock.SIGNING_SKEW`` (the governance signing skew) of server time when the decision is recorded,
  and the ``nonce`` is single-use per signer: each store records the nonces it has
  consumed and refuses a second use (``DecisionReplayed``). The proposal ledger checks
  freshness against the very commit time its row records, inside the write transaction,
  which is the instant its fold re-checks: a decision the store accepted is never dropped
  on read-back.
* **Binding to the request.** The verifier compares the signed body with the decision
  the server is about to store (kind, corpus, target, verdict, rationale and the
  kind's detail fields), so a signature cannot be moved to another unit, proposal,
  corpus or verdict.
* **Binding a server-side selection.** A bulk approval by threshold selects its targets
  on the server. Its signed detail carries ``selection_sha256`` (``selection_digest`` of
  the exact selected IDs) next to the threshold, the server computes the digest of the
  selection it is about to approve, and a different selection is refused with
  ``DecisionSelectionChanged`` (HTTP 409): a signature never approves items the signer
  did not see.

Registered signers (``FOLIO_INSIGHTS_DECISION_SIGNERS_FILE``): one ``<did:key> <handle>``
line per reviewer key (``#`` comments and blank lines allowed). The file holds public
DIDs only; it is refused when it is not a regular file owned by this user (or root), or
when other users may write it. With a signers file, a signed decision must come from a
listed DID, and it is attributed to ``human:<handle>`` (the handle mapped to the DID).
Without one, any did:key verifies, the signer DID is recorded, and the decision keeps
the server's reviewer attribution. Stores and API views keep the two facts apart:
``signature_verified`` means the signature is cryptographically valid for its did:key,
``signer_registered`` that a signers file listed that DID when the decision was recorded
(always ``false`` without a signers file). Requiring signatures without a signers file would
accept a key anyone can generate, so that configuration refuses every decision
(``DecisionPolicyMisconfigured``) instead of pretending to authenticate reviewers.

Error messages name the rule that failed, never a submitted value.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import stat
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import jcs
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from folio_insights.governance.clock import SIGNING_SKEW, GovernanceClockSkew

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from folio_insights.shards.envelope import AttestedSignature

DECISION_BODY_FORMAT = "folio-insights/review-decision/v1"

KIND_PROPOSED_CLASS = "proposed_class"
KIND_UNIT_REVIEW = "unit_review"
KIND_UNIT_BULK_APPROVE = "unit_bulk_approve"
KIND_UNIT_REVIEW_RESET = "unit_review_reset"
KIND_TASK_REVIEW = "task_review"
KIND_TASK_BULK_APPROVE = "task_bulk_approve"
KIND_TASK_CREATE = "task_create"
KIND_TASK_DELETE = "task_delete"
KIND_HIERARCHY_EDIT = "hierarchy_edit"
KIND_CONTRADICTION_RESOLVE = "contradiction_resolve"
DecisionKind = Literal[
    "proposed_class",
    "unit_review",
    "unit_bulk_approve",
    "unit_review_reset",
    "task_review",
    "task_bulk_approve",
    "task_create",
    "task_delete",
    "hierarchy_edit",
    "contradiction_resolve",
]
DECISION_KINDS: frozenset[str] = frozenset(DecisionKind.__args__)  # type: ignore[attr-defined]

#: Target of a corpus-wide decision (a bulk approval by confidence, a review reset) and of
#: a decision whose subject has no ID yet (a task created by the decision).
CORPUS_WIDE_TARGET = "*"

#: Detail key binding a server-side selection (``selection_digest``).
SELECTION_DIGEST_KEY = "selection_sha256"

#: The ``action`` handed to ``sign_attestation`` / ``verify_attestation``. Not signed (the
#: primitives sign ``over_content_hash`` only) and never stored with a decision.
_CARRIER_ACTION = "content_edit"

MAX_TARGET_CHARS = 512
MAX_RATIONALE_CHARS = 10_000
MAX_VERDICT_CHARS = 32
MAX_DETAIL_KEYS = 8
MAX_DETAIL_LIST_ITEMS = 10_000
MAX_BODY_BYTES = 256 * 1024
_MAX_SIGNERS_FILE_BYTES = 256 * 1024

_CORPUS = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_NONCE = re.compile(r"[A-Za-z0-9_-]{16,128}")
_ISSUED_AT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z")
_DID_KEY = re.compile(r"did:key:z[1-9A-HJ-NP-Za-km-z]{40,64}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_DETAIL_KEY = re.compile(r"[a-z][a-z0-9_]{0,63}")
_SIG_B64URL = re.compile(r"[A-Za-z0-9_-]{86}")
_HANDLE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class DecisionSignatureRefused(ValueError):
    """A signed decision was refused. ``code`` names the rule; the message never
    contains a submitted value."""

    code = "refused"


class DecisionSignatureMalformed(DecisionSignatureRefused):
    """The signature object is not a well-formed ``SignedDecision``."""

    code = "malformed"


class DecisionSignatureMismatch(DecisionSignatureRefused):
    """The signed body does not describe the decision being recorded."""

    code = "mismatch"


class DecisionSignatureInvalid(DecisionSignatureRefused):
    """The signature does not verify for the signer DID (tampered body, wrong key)."""

    code = "invalid"


class DecisionSignatureStale(DecisionSignatureRefused, GovernanceClockSkew):
    """``issued_at`` is not within ``SIGNING_SKEW`` of server time (the governance
    clock-skew refusal, applied to a decision signature)."""

    code = "stale"


class DecisionSelectionChanged(DecisionSignatureMismatch):
    """The signed selection digest is not the digest of what the server would select now
    (the items matching a bulk threshold changed after the reviewer signed)."""

    code = "selection_changed"


class DecisionReplayed(DecisionSignatureRefused):
    """The signer's nonce was already consumed by this store."""

    code = "replayed"


class DecisionSignerUnregistered(DecisionSignatureRefused):
    """The signer DID is not listed in the configured signers file."""

    code = "unregistered"


class DecisionSignatureRequired(DecisionSignatureRefused):
    """This server requires signed decisions and the decision carried none."""

    code = "required"


class DecisionPolicyMisconfigured(RuntimeError):
    """The signed-decision configuration is unusable (refuse every decision)."""


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def _check_detail(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or len(value) > MAX_DETAIL_KEYS:
        raise ValueError(f"detail must be an object of at most {MAX_DETAIL_KEYS} fields")
    out: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not _DETAIL_KEY.fullmatch(key):
            raise ValueError("detail keys must be short snake_case names")
        if item is None or isinstance(item, (bool, str)):
            pass
        elif isinstance(item, int):
            pass
        elif isinstance(item, float):
            if item != item or item in (float("inf"), float("-inf")):
                raise ValueError("detail numbers must be finite")
        elif isinstance(item, list):
            if len(item) > MAX_DETAIL_LIST_ITEMS or not all(isinstance(x, str) for x in item):
                raise ValueError(
                    f"detail lists must hold at most {MAX_DETAIL_LIST_ITEMS} strings"
                )
            item = list(item)
        else:
            raise ValueError("detail values must be null, a boolean, a number, a string "
                             "or a list of strings")
        out[key] = item
    return out


def parse_issued_at(text: str) -> datetime:
    """The UTC instant of an ``issued_at`` string (``YYYY-MM-DDTHH:MM:SS[.ffffff]Z``)."""
    if not isinstance(text, str) or not _ISSUED_AT.fullmatch(text):
        raise ValueError("issued_at must be an RFC 3339 UTC time ending in 'Z'")
    return datetime.fromisoformat(text[:-1]).replace(tzinfo=UTC)


def format_issued_at(when: datetime) -> str:
    """The canonical ``issued_at`` string of ``when`` (UTC, microseconds, ``Z``)."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class DecisionBody(BaseModel):
    """The canonical decision body a reviewer signs.

    ``issued_at`` is a string (not a ``datetime``) so the signed bytes are exactly the
    bytes the signer produced; ``parse_issued_at`` reads the instant from it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    format: Literal["folio-insights/review-decision/v1"] = DECISION_BODY_FORMAT
    kind: DecisionKind
    corpus: str
    target: str
    verdict: str
    rationale: str = ""
    detail: dict[str, Any] = {}
    decided_by: str
    nonce: str
    issued_at: str

    @field_validator("corpus")
    @classmethod
    def _corpus(cls, v: str) -> str:
        if not _CORPUS.fullmatch(v):
            raise ValueError("corpus must be a corpus ID of letters, digits, '.', '_' or '-'")
        return v

    @field_validator("target")
    @classmethod
    def _target(cls, v: str) -> str:
        if not v or len(v) > MAX_TARGET_CHARS:
            raise ValueError(f"target must be 1 to {MAX_TARGET_CHARS} characters")
        return v

    @field_validator("verdict")
    @classmethod
    def _verdict(cls, v: str) -> str:
        if not v or len(v) > MAX_VERDICT_CHARS:
            raise ValueError(f"verdict must be 1 to {MAX_VERDICT_CHARS} characters")
        return v

    @field_validator("rationale")
    @classmethod
    def _rationale(cls, v: str) -> str:
        if len(v) > MAX_RATIONALE_CHARS:
            raise ValueError(f"rationale must be at most {MAX_RATIONALE_CHARS} characters")
        return v

    @field_validator("detail", mode="before")
    @classmethod
    def _detail(cls, v: Any) -> dict[str, Any]:
        return _check_detail(v)

    @field_validator("decided_by")
    @classmethod
    def _decided_by(cls, v: str) -> str:
        if not _DID_KEY.fullmatch(v):
            raise ValueError("decided_by must be the signer's did:key")
        return v

    @field_validator("nonce")
    @classmethod
    def _nonce(cls, v: str) -> str:
        if not _NONCE.fullmatch(v):
            raise ValueError("nonce must be 16 to 128 characters of [A-Za-z0-9_-]")
        return v

    @field_validator("issued_at")
    @classmethod
    def _issued_at(cls, v: str) -> str:
        parse_issued_at(v)
        return v

    def canonical_hash(self) -> str:
        """SHA-256 hex of the JCS-canonical body: the bytes the signature covers."""
        canonical = jcs.canonicalize(self.model_dump(mode="json"))
        if len(canonical) > MAX_BODY_BYTES:
            raise DecisionSignatureMalformed(
                f"the decision body is larger than {MAX_BODY_BYTES} bytes"
            )
        return hashlib.sha256(canonical).hexdigest()


class DecisionSignature(BaseModel):
    """An ``AttestedSignature`` without ``action`` (see the module docstring)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    did: str
    signed_at: datetime
    signature: str
    over_content_hash: str
    signing_key_id: str
    did_doc_snapshot_at: None = None

    @field_validator("did")
    @classmethod
    def _did(cls, v: str) -> str:
        if not _DID_KEY.fullmatch(v):
            raise ValueError("did must be a did:key (the only accepted decision signer method)")
        return v

    @field_validator("signed_at")
    @classmethod
    def _signed_at(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("signed_at must carry a time zone")
        return v

    @field_validator("signature")
    @classmethod
    def _signature(cls, v: str) -> str:
        if not _SIG_B64URL.fullmatch(v):
            raise ValueError("signature must be a base64url (no padding) ed25519 signature")
        return v

    @field_validator("over_content_hash")
    @classmethod
    def _hash(cls, v: str) -> str:
        if not _HEX64.fullmatch(v):
            raise ValueError("over_content_hash must be a SHA-256 hex digest")
        return v


class SignedDecision(BaseModel):
    """A decision body with its signature: the ``signature`` object of a review request,
    the output of ``folio-insights proposals sign-decision`` and what a store records."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    body: DecisionBody
    signature: DecisionSignature

    def to_record(self) -> dict[str, Any]:
        """The JSON-safe stored form (``model_dump(mode="json")``)."""
        return self.model_dump(mode="json")


def parse_signed_decision(value: Any) -> SignedDecision:
    """A ``SignedDecision`` from request JSON, or ``DecisionSignatureMalformed`` naming
    the offending field paths (never their values)."""
    if isinstance(value, SignedDecision):
        return value
    if not isinstance(value, Mapping):
        raise DecisionSignatureMalformed(
            "signature must be an object with 'body' and 'signature' (a signed decision)"
        )
    try:
        return SignedDecision.model_validate(dict(value))
    except ValidationError as exc:
        fields = sorted({".".join(str(p) for p in err["loc"]) or "<root>" for err in exc.errors()})
        raise DecisionSignatureMalformed(
            "signature is not a valid signed decision; check field(s): " + ", ".join(fields[:8])
        ) from None


# ---------------------------------------------------------------------------
# Signing (client side: the CLI helper and tests)
# ---------------------------------------------------------------------------


def did_key_of(signing_key: Ed25519PrivateKey) -> str:
    """The did:key of an ed25519 private key."""
    from cryptography.hazmat.primitives import serialization

    from folio_insights.identity.keys import did_key_from_public

    raw = signing_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    return did_key_from_public(raw)


def did_key_signing_key_id(did: str) -> str:
    """The verificationMethod id of a did:key (``<did>#<multibase>``)."""
    return f"{did}#{did.removeprefix('did:key:')}"


def selection_digest(ids: Iterable[str]) -> str:
    """SHA-256 hex of the JCS-canonical sorted, de-duplicated list of ``ids``.

    The ``selection_sha256`` a signer puts in the detail of a bulk approval by threshold,
    and the digest the server computes over the IDs it is about to approve. Order and
    repetition do not change it; any added or removed ID does."""
    items = sorted({str(i) for i in ids})
    return hashlib.sha256(jcs.canonicalize(items)).hexdigest()


def new_nonce() -> str:
    """A fresh 128-bit nonce (32 lowercase hex characters)."""
    return secrets.token_hex(16)


#: Fields a caller supplies to ``sign_decision``; the signer adds the rest.
SIGNABLE_FIELDS = frozenset({"kind", "corpus", "target", "verdict", "rationale", "detail"})


def sign_decision(
    fields: Mapping[str, Any],
    *,
    signing_key: Ed25519PrivateKey,
    now: datetime | None = None,
    nonce: str | None = None,
) -> SignedDecision:
    """Sign a decision ``{kind, corpus, target, verdict, rationale?, detail?}``.

    ``decided_by`` becomes the key's did:key, ``nonce`` a fresh random value and
    ``issued_at`` the current time (``now`` and ``nonce`` exist for tests). Any other
    input field is refused, so a caller can never re-sign an old nonce by accident.
    The signature is produced by ``identity.signer.sign_attestation`` over the body's
    JCS hash.
    """
    from folio_insights.identity.signer import sign_attestation

    extra = set(fields) - SIGNABLE_FIELDS
    if extra:
        raise DecisionSignatureMalformed(
            f"a decision to sign may only name {sorted(SIGNABLE_FIELDS)}; "
            f"{len(extra)} other field(s) given (decided_by, nonce and issued_at are "
            "set by the signer)"
        )
    did = did_key_of(signing_key)
    when = now or datetime.now(UTC)
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    issued_at = format_issued_at(when)
    try:
        body = DecisionBody.model_validate({
            **dict(fields),
            "decided_by": did,
            "nonce": nonce or new_nonce(),
            "issued_at": issued_at,
        })
    except ValidationError as exc:
        names = sorted({".".join(str(p) for p in err["loc"]) or "<root>" for err in exc.errors()})
        raise DecisionSignatureMalformed(
            "the decision to sign is invalid; check field(s): " + ", ".join(names[:8])
        ) from None
    content_hash = body.canonical_hash()
    attested = sign_attestation(
        content_hash,
        signing_key,
        did,
        _CARRIER_ACTION,
        signing_key_id=did_key_signing_key_id(did),
        did_doc_snapshot_at=None,
        now=parse_issued_at(issued_at),
    )
    return SignedDecision(
        body=body,
        signature=DecisionSignature(
            did=attested.did,
            signed_at=attested.signed_at,
            signature=attested.signature,
            over_content_hash=attested.over_content_hash,
            signing_key_id=attested.signing_key_id,
        ),
    )


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExpectedDecision:
    """What the server is about to store, for comparison with the signed body.

    ``verdict`` is compared after ``normalize_verdict`` maps both sides (the proposed-class
    paste-back verbs ``approve``/``approved`` are one verdict); ``rationale`` is compared
    after stripping surrounding whitespace, as stores keep notes.
    """

    kind: str
    corpus: str
    target: str
    verdict: str
    rationale: str = ""
    detail: Mapping[str, Any] | None = None


def normalize_verdict(kind: str, verdict: str) -> str:
    if kind == KIND_PROPOSED_CLASS:
        from folio_insights.proposals.decisions import INPUT_STATUSES

        return INPUT_STATUSES.get(verdict, verdict)
    return verdict


def _normalized_detail(detail: Mapping[str, Any] | None) -> dict[str, Any]:
    # A JSON round trip so 1 and 1.0, tuples and lists compare as the wire would.
    return jcs.canonicalize({k: v for k, v in (detail or {}).items() if v is not None})


def check_matches(body: DecisionBody, expected: ExpectedDecision) -> None:
    """Refuse (``DecisionSignatureMismatch``) a body that does not describe ``expected``.
    The message names the differing fields, never their values."""
    differing: list[str] = []
    if body.kind != expected.kind:
        differing.append("kind")
    if body.corpus != expected.corpus:
        differing.append("corpus")
    if body.target != expected.target:
        differing.append("target")
    if normalize_verdict(body.kind, body.verdict) != normalize_verdict(
        expected.kind, expected.verdict
    ):
        differing.append("verdict")
    if (body.rationale or "").strip() != (expected.rationale or "").strip():
        differing.append("rationale")
    if _normalized_detail(body.detail) != _normalized_detail(expected.detail):
        differing.append("detail")
        if not differing[:-1] and _only_selection_differs(body.detail, expected.detail):
            raise DecisionSelectionChanged(
                "the signed selection is not what this request would approve now (the "
                "items matching the threshold changed after signing); review the current "
                "selection and sign it again. Nothing was recorded"
            )
    if differing:
        raise DecisionSignatureMismatch(
            "the signed decision does not match this request (" + ", ".join(differing)
            + " differ); sign exactly the decision being submitted. Nothing was recorded"
        )


def _only_selection_differs(
    signed: Mapping[str, Any], expected: Mapping[str, Any] | None
) -> bool:
    """True when the expected detail binds a selection digest, the signed detail names one
    too, and the two details agree on every other field."""
    expected = dict(expected or {})
    signed = dict(signed)
    if SELECTION_DIGEST_KEY not in expected or SELECTION_DIGEST_KEY not in signed:
        return False
    if signed[SELECTION_DIGEST_KEY] == expected[SELECTION_DIGEST_KEY]:
        return False
    signed.pop(SELECTION_DIGEST_KEY)
    expected.pop(SELECTION_DIGEST_KEY)
    return _normalized_detail(signed) == _normalized_detail(expected)


def _structural_checks(signed: SignedDecision) -> tuple[str, datetime]:
    """Checks that need no cryptography. Returns the recomputed body hash and the
    ``issued_at`` instant."""
    body, sig = signed.body, signed.signature
    if body.decided_by != sig.did:
        raise DecisionSignatureMismatch(
            "decided_by must be the signer DID: a signed decision is attributed to its signer"
        )
    if sig.signing_key_id != did_key_signing_key_id(sig.did):
        raise DecisionSignatureInvalid("signing_key_id is not the signer did:key's key")
    issued = parse_issued_at(body.issued_at)
    if sig.signed_at != issued:
        raise DecisionSignatureMismatch("signature.signed_at must equal body.issued_at")
    content_hash = body.canonical_hash()
    if content_hash != sig.over_content_hash:
        raise DecisionSignatureInvalid(
            "the signature does not cover this decision body (it was changed after signing)"
        )
    return content_hash, issued


def _carrier(sig: DecisionSignature) -> AttestedSignature:
    from folio_insights.shards.envelope import AttestedSignature

    return AttestedSignature(
        did=sig.did,
        action=_CARRIER_ACTION,
        signed_at=sig.signed_at,
        signature=sig.signature,
        over_content_hash=sig.over_content_hash,
        signing_key_id=sig.signing_key_id,
        did_doc_snapshot_at=None,
    )


def check_fresh(issued: datetime, now: datetime) -> None:
    """Refuse (``DecisionSignatureStale``) an ``issued`` instant more than
    ``SIGNING_SKEW`` away from server time ``now``. The single freshness rule: the
    verifier, the proposal ledger's in-transaction commit check and its fold all apply
    exactly this comparison."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    if abs(now - issued) > SIGNING_SKEW:
        raise DecisionSignatureStale(
            f"the signed decision's issued_at is not within {SIGNING_SKEW} of server time; "
            "sign it again. Nothing was recorded"
        )


@dataclass(frozen=True)
class VerifiedDecision:
    """A signed decision that verified, with what a store records."""

    signed: SignedDecision
    body_hash: str
    signer_did: str
    #: ``human:<handle>`` when a signers file maps the DID, else ``None``.
    signer_handle: str | None
    #: Whether a signers file listed the DID (``False`` when none is configured).
    #: Distinct from verification: every ``VerifiedDecision`` is cryptographically valid.
    signer_registered: bool = False

    @property
    def nonce(self) -> str:
        return self.signed.body.nonce


async def verify_signed_decision(
    value: Any,
    *,
    expected: ExpectedDecision,
    policy: DecisionSignaturePolicy,
    now: datetime | None = None,
    check_freshness: bool = True,
) -> VerifiedDecision:
    """Verify a signed decision for recording ``expected`` at server time ``now``.

    In order: well-formed; ``decided_by`` is the signer; the recomputed JCS hash is the
    signed hash; ``identity.verifier.verify_attestation`` accepts the signature (did:key
    resolution, ed25519); ``issued_at`` is fresh; the body matches ``expected``; the
    signer is registered when the policy has a signers file. Replay (nonce reuse) is the
    store's check, because only the store knows which nonces it consumed.

    ``check_freshness=False`` is for a store replaying an operation it already committed
    (the same op_id and request): the signature was fresh when it was first recorded, and
    the replay returns that committed result without recording anything new.
    """
    from folio_insights.identity.cache import InMemoryDidDocCache
    from folio_insights.identity.verifier import verify_attestation

    signed = parse_signed_decision(value)
    content_hash, issued = _structural_checks(signed)
    ok = await verify_attestation(
        content_hash, _carrier(signed.signature), cache=InMemoryDidDocCache()
    )
    if not ok:
        raise DecisionSignatureInvalid(
            "the decision signature does not verify for the signer DID. Nothing was recorded"
        )
    if check_freshness:
        check_fresh(issued, now or datetime.now(UTC))
    check_matches(signed.body, expected)
    handle = policy.signer_handle(signed.signature.did)
    return VerifiedDecision(
        signed=signed, body_hash=content_hash, signer_did=signed.signature.did,
        signer_handle=handle, signer_registered=handle is not None,
    )


def stored_signature_problem(
    value: Any,
    *,
    expected: ExpectedDecision,
    signer_did: Any,
    committed_at: str | None = None,
) -> str | None:
    """Why a STORED signed decision is not valid, or ``None`` (fold-time re-check).

    A store writes ``signature_verified: true`` only after ``verify_signed_decision``;
    this re-check lets a reader trust that flag even for a row that bypassed the store
    (a raw ledger append). It repeats the structural checks, verifies the ed25519
    signature against the did:key with the same libraries the verifier uses, compares
    the body with the stored decision and, given ``committed_at``, checks the signing
    time against the ledger's commit time (``SIGNING_SKEW``).
    """
    from cryptography.exceptions import InvalidSignature

    from folio_insights.identity._b64 import _b64url_nopad_decode
    from folio_insights.identity.keys import public_key_from_did_key

    try:
        signed = parse_signed_decision(value)
        content_hash, issued = _structural_checks(signed)
        check_matches(signed.body, expected)
    except (DecisionSignatureRefused, ValueError):
        return "stored signature does not describe this decision"
    if signer_did != signed.signature.did:
        return "signer_did is not the signature's DID"
    try:
        public_key_from_did_key(signed.signature.did).verify(
            _b64url_nopad_decode(signed.signature.signature), content_hash.encode("utf-8")
        )
    except (InvalidSignature, ValueError, TypeError):
        return "stored signature does not verify"
    if committed_at is not None:
        try:
            committed = datetime.fromisoformat(committed_at)
        except (TypeError, ValueError):
            return "ledger commit time is unreadable"
        try:
            check_fresh(issued, committed)
        except DecisionSignatureStale:
            return "stored signature was not issued within the signing skew of its commit"
    return None


_OPERATOR_PLAIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_OPERATOR_DIGEST = re.compile(r"sha256:[0-9a-f]{16}")


def operator_record(handle: str | None) -> str | None:
    """How a store records the authenticated operator (``api.auth.Operator.handle``).

    Operator authentication is not decision authorship: a store records both, the
    operator who submitted the write and the signer who authored the decision. An
    operator handle may be an e-mail address; stores are append-only and must not
    keep one, so such a handle is recorded as ``sha256:<16 hex>`` of it instead."""
    if handle is None:
        return None
    if _OPERATOR_PLAIN.fullmatch(handle):
        return handle
    return "sha256:" + hashlib.sha256(handle.encode("utf-8")).hexdigest()[:16]


def operator_record_problem(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and (
        _OPERATOR_PLAIN.fullmatch(value) or _OPERATOR_DIGEST.fullmatch(value)
    ):
        return None
    return "operator is not an operator handle or its digest"


# ---------------------------------------------------------------------------
# Policy: required signatures and registered signers
# ---------------------------------------------------------------------------


class SignersFileError(DecisionPolicyMisconfigured):
    """The signers file is missing, unsafe or malformed (named by line number only)."""


def parse_signers(text: str, source: str = "signers file") -> dict[str, str]:
    """``{did: "human:<handle>"}`` from signers-file text. A malformed line is reported
    by its number only."""
    out: dict[str, str] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 2 or not _DID_KEY.fullmatch(parts[0]):
            raise SignersFileError(
                f"{source}: line {number} is not '<did:key> <handle>'"
            )
        did, handle = parts
        handle = handle.removeprefix("human:")
        if not _HANDLE.fullmatch(handle):
            raise SignersFileError(
                f"{source}: line {number} has an invalid handle (letters, digits, '.', '_' "
                "or '-')"
            )
        if did in out:
            raise SignersFileError(f"{source}: line {number} repeats a DID")
        try:
            from folio_insights.identity.keys import public_key_from_did_key

            public_key_from_did_key(did)
        except ValueError:
            raise SignersFileError(
                f"{source}: line {number} names a did:key that is not an ed25519 key"
            ) from None
        out[did] = f"human:{handle}"
    return out


def load_signers_file(path: Path | str) -> dict[str, str]:
    """Read the signers file through one descriptor (the checked mode is the mode of the
    bytes read). Refused unless it is a regular file owned by this user or root that
    other users cannot write."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOCTTY", 0))
    except OSError as exc:
        raise SignersFileError(f"{path}: cannot open ({exc.strerror})") from None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise SignersFileError(f"{path}: not a regular file")
        if st.st_uid not in {os.geteuid(), 0}:
            raise SignersFileError(f"{path}: owned by another user (uid {st.st_uid})")
        if stat.S_IMODE(st.st_mode) & 0o022:
            raise SignersFileError(
                f"{path}: mode {stat.S_IMODE(st.st_mode):04o} lets other users write it; "
                f"run: chmod 644 {path}"
            )
    except BaseException:
        os.close(fd)
        raise
    with os.fdopen(fd, "rb") as handle:
        data = handle.read(_MAX_SIGNERS_FILE_BYTES + 1)
    if len(data) > _MAX_SIGNERS_FILE_BYTES:
        raise SignersFileError(f"{path}: larger than {_MAX_SIGNERS_FILE_BYTES} bytes")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise SignersFileError(f"{path}: not UTF-8 text") from None
    return parse_signers(text, str(path))


class _SignersCache:
    """The parsed signers file, reloaded when its identity, size, mode or mtime change."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._key: tuple | None = None
        self._signers: dict[str, str] = {}

    def get(self, path: Path) -> dict[str, str]:
        try:
            st = os.stat(path)
        except OSError as exc:
            raise SignersFileError(f"{path}: cannot stat ({exc.strerror})") from None
        key = (str(path), st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_mode, st.st_uid)
        with self._lock:
            if key != self._key:
                self._signers = load_signers_file(path)
                self._key = key
            return dict(self._signers)

    def clear(self) -> None:
        with self._lock:
            self._key = None
            self._signers = {}


_signers_cache = _SignersCache()


def reset_signers_cache() -> None:
    """Forget the cached signers file (tests, or after replacing the file in place)."""
    _signers_cache.clear()


@dataclass(frozen=True)
class DecisionSignaturePolicy:
    """Whether unsigned decisions are refused, and the registered signers (if any)."""

    require_signed: bool = False
    #: ``{did: "human:<handle>"}``; ``None`` when no signers file is configured.
    signers: Mapping[str, str] | None = None

    def check_unsigned(self) -> None:
        """Refuse an unsigned decision when signatures are required."""
        if self.require_signed:
            raise DecisionSignatureRequired(
                "this server requires signed decisions (FOLIO_INSIGHTS_REQUIRE_SIGNED_DECISIONS"
                "=1); sign the decision with 'folio-insights proposals sign-decision' and send "
                "it as 'signature'. Nothing was recorded"
            )

    def signer_handle(self, did: str) -> str | None:
        """The handle mapped to ``did``; refuses an unlisted DID when a signers file is set."""
        if self.signers is None:
            return None
        handle = self.signers.get(did)
        if handle is None:
            raise DecisionSignerUnregistered(
                "the signer DID is not a registered decision signer "
                "(FOLIO_INSIGHTS_DECISION_SIGNERS_FILE). Nothing was recorded"
            )
        return handle


def load_policy() -> DecisionSignaturePolicy:
    """The policy from settings (``FOLIO_INSIGHTS_REQUIRE_SIGNED_DECISIONS``,
    ``FOLIO_INSIGHTS_DECISION_SIGNERS_FILE``). Raises ``DecisionPolicyMisconfigured``
    when signatures are required without a signers file, or the file is refused."""
    from folio_insights.config import get_settings

    settings = get_settings()
    path = settings.decision_signers_file
    signers = None if path is None else _signers_cache.get(Path(path).expanduser())
    if settings.require_signed_decisions and signers is None:
        raise DecisionPolicyMisconfigured(
            "FOLIO_INSIGHTS_REQUIRE_SIGNED_DECISIONS=1 needs FOLIO_INSIGHTS_DECISION_SIGNERS_FILE "
            "listing the reviewers' did:key DIDs (a signature by an unregistered key "
            "authenticates nobody); refusing every decision until it is configured"
        )
    return DecisionSignaturePolicy(require_signed=settings.require_signed_decisions,
                                   signers=signers)


__all__ = [
    "CORPUS_WIDE_TARGET",
    "DECISION_BODY_FORMAT",
    "DECISION_KINDS",
    "KIND_CONTRADICTION_RESOLVE",
    "KIND_HIERARCHY_EDIT",
    "KIND_PROPOSED_CLASS",
    "KIND_TASK_BULK_APPROVE",
    "KIND_TASK_CREATE",
    "KIND_TASK_DELETE",
    "KIND_TASK_REVIEW",
    "KIND_UNIT_BULK_APPROVE",
    "KIND_UNIT_REVIEW",
    "KIND_UNIT_REVIEW_RESET",
    "SELECTION_DIGEST_KEY",
    "SIGNABLE_FIELDS",
    "DecisionBody",
    "DecisionPolicyMisconfigured",
    "DecisionReplayed",
    "DecisionSelectionChanged",
    "DecisionSignature",
    "DecisionSignatureInvalid",
    "DecisionSignatureMalformed",
    "DecisionSignatureMismatch",
    "DecisionSignaturePolicy",
    "DecisionSignatureRefused",
    "DecisionSignatureRequired",
    "DecisionSignatureStale",
    "DecisionSignerUnregistered",
    "ExpectedDecision",
    "SignedDecision",
    "SignersFileError",
    "VerifiedDecision",
    "check_fresh",
    "check_matches",
    "did_key_of",
    "did_key_signing_key_id",
    "format_issued_at",
    "load_policy",
    "load_signers_file",
    "new_nonce",
    "normalize_verdict",
    "operator_record",
    "operator_record_problem",
    "parse_issued_at",
    "parse_signed_decision",
    "parse_signers",
    "reset_signers_cache",
    "selection_digest",
    "sign_decision",
    "stored_signature_problem",
    "verify_signed_decision",
]
