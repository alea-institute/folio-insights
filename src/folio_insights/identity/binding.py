"""OAuth→DID binding contract + ``bind()`` rules (D-10, SEC-06, F3, F7).

Ships the **backend / CLI** binding contract the deferred post-Phase-14 web
phase will render (D-02). The CLI ``folio-insights did bind`` exercises
``bind()`` end-to-end; the SEC-06 rules locked here are the same rules the
post-design-system OAuth flow will enforce — Phase 6 just doesn't ship the
web UI for them.

Defense rules — every one is a contract test in
``tests/identity/test_binding_proof.py``:

* **Bind to the immutable OAuth ``sub`` claim, NEVER email/username** (F7,
  GitHub-username-takeover defense). A binding record's ``sub`` is the OAuth
  provider's stable subject identifier; helpers refuse to build a record from
  an email/username-shaped value (any string containing ``@`` or matching
  a username heuristic).
* **Signed proof-of-control** carries a single-use server-issued nonce
  (5-min TTL, atomic ``consume`` get-delete), a timestamp within ±2 min of
  the server clock, and the binding-endpoint URL (F3 — replay defense).
  Replay → ``NonceReused``; stale → ``StaleProof``; URL mismatch →
  ``EndpointMismatch``.
* **Subject-change detection** (F7): if a later bind sees the same DID under
  a DIFFERENT ``sub``, the old binding is unbound and a fresh signed proof is
  required. Surfaced as ``SubjectChanged``.
* **Idempotency:** a repeat bind for the same ``(sub, did)`` is a no-op —
  return the existing record unchanged. A DIFFERENT ``did`` for the same
  ``sub`` is also a ``SubjectChanged`` conflict; we NEVER silently overwrite.
* **did:web domain-control proof:** binding a ``did:web`` additionally
  requires the resolver to confirm ``.well-known/did.json`` lists the bound
  verification key (Plan 02 ``resolve_did`` already does this — we just
  invoke it as a side gate).

Seams (defer with the web phase, D-02):

* ``NonceStore`` Protocol + ``InMemoryNonceStore`` mirror Phase 5's
  ``ShardStore`` (D-02) and the Plan-02 ``DidDocCache`` (D-11): in-memory
  for Phase 6, Redis (``GETDEL`` for atomic consume) in the deferred web
  phase. The Protocol is the seam the web phase swaps without touching
  callers.
* No ``authlib`` ``Starlette`` OAuth flow here — that's the deferred web
  surface. ``authlib`` is a Plan-01 dep purely for ``sub``-claim semantics
  documentation; this module references those semantics in docstrings only.
* No ``redis`` import. The atomic ``get-delete`` discipline lives in the
  Protocol contract; the in-memory implementation uses ``dict.pop`` which
  IS atomic in CPython's GIL.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Awaitable, Callable, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from folio_insights.identity.cache import DidDocCache
from folio_insights.identity.resolver import resolve_did as _default_resolve_did
from folio_insights.identity.verifier import verify_attestation
from folio_insights.shards.envelope import AttestedSignature


# ── Typed errors — replay/F3/F7 defenses (never raise a bare ValueError) ────


class BindingError(Exception):
    """Base class for all binding-rule failures (F3 / F7 / SEC-06)."""


class NonceReused(BindingError):
    """The proof's nonce was already consumed (replay defense, F3)."""


class StaleProof(BindingError):
    """The proof's timestamp is more than ±2 min skewed from server time (F3)."""


class EndpointMismatch(BindingError):
    """The proof's ``binding_endpoint`` does not match the server-expected URL (F3)."""


class SubjectChanged(BindingError):
    """A bind attempt presents a different sub for the same DID (F7) — re-bind required."""


class InvalidSubject(BindingError):
    """A binding subject must be the OAuth ``sub`` claim — refused email/username (F7)."""


class InvalidProofSignature(BindingError):
    """The proof's DID-signed signature does not verify (replay defense / DID-04)."""


class DomainControlFailed(BindingError):
    """did:web binding requires .well-known/did.json domain-control proof (SEC-06)."""


# ── Constants — the locked defense rules ────────────────────────────────────


NONCE_TTL = timedelta(minutes=5)
"""Single-use nonce TTL (5 min per RESEARCH §5). Consume is atomic get-delete."""

PROOF_CLOCK_SKEW = timedelta(minutes=2)
"""Allowed clock skew between proof timestamp and server (±2 min, F3 / RESEARCH §5)."""


# ── ProofPayload + BindingRecord (Pydantic, extra=forbid) ───────────────────


class ProofPayload(BaseModel):
    """Signed proof-of-control payload the DID-holder produces during binding.

    The payload is canonicalized + signed by the DID's private key; the
    resulting signature accompanies the payload to ``bind()``. The payload
    fields are EXACTLY the four F3 ingredients (RESEARCH §5):

    * ``sub`` — the OAuth ``sub`` claim (immutable subject identifier).
      NOT email, NOT username (F7). The ``bind()`` rules refuse a value that
      looks like an email (contains ``@``) — see ``_assert_sub_is_oauth_sub``.
    * ``nonce`` — the server-issued single-use nonce (5-min TTL). Consumed
      atomically by ``NonceStore.consume`` on each bind attempt; a replayed
      nonce raises ``NonceReused``.
    * ``issued_at`` — UTC timestamp the proof was issued by the DID-holder.
      Must be within ±2 min of server clock at ``bind()`` (``PROOF_CLOCK_SKEW``).
    * ``binding_endpoint`` — the URL the proof was issued AGAINST. Pinning
      this in the signed payload defeats a cross-endpoint replay (F3).
    * ``did`` — the DID being bound, included in the signed payload so the
      signature itself binds the (sub, nonce, endpoint, did) tuple.
    """

    model_config = ConfigDict(extra="forbid")

    sub: str
    nonce: str
    issued_at: datetime
    binding_endpoint: str
    did: str


class BindingRecord(BaseModel):
    """Result of a successful ``bind()``: ``(sub, did, bound_at, proof)``.

    The record is keyed by the immutable OAuth ``sub`` (NEVER email/username,
    F7). A ``binding_store`` mapping ``sub -> BindingRecord`` is the
    persistence seam the web phase swaps Redis-or-similar behind; in Phase 6
    a plain ``dict[str, BindingRecord]`` IS the store (mirrors the Plan-02
    ``InMemoryDidDocCache`` shape).

    Idempotency: a repeat ``bind(sub, did, ...)`` for the SAME (sub, did)
    returns the SAME ``BindingRecord`` instance from the store — never a
    silently-updated copy (T-06-12).
    """

    model_config = ConfigDict(extra="forbid")

    sub: str
    did: str
    bound_at: datetime
    proof: ProofPayload


# ── NonceStore Protocol + in-memory seam (D-10 / Plan-02 cache mirror) ──────


@runtime_checkable
class NonceStore(Protocol):
    """Single-use nonce seam (5-min TTL, atomic consume).

    Mirrors ``DidDocCache`` (Plan 02) and ``ShardStore`` (Phase 5): a thin
    async Protocol over an in-memory dict in Phase 6, a Redis ``GETDEL``
    backend in the deferred web phase. The atomic ``consume`` is what defeats
    a replay (F3) — Redis ``GETDEL`` is the canonical atomic primitive; in
    CPython, ``dict.pop`` under the GIL is the equivalent guarantee.
    """

    async def issue(self) -> str:
        """Mint a fresh nonce, record its expiry (now + 5 min), and return it."""
        ...

    async def consume(self, nonce: str) -> bool:
        """Atomically remove ``nonce`` from the store.

        Returns ``True`` if the nonce was present AND not expired (caller
        should treat that as "use accepted"); ``False`` if the nonce was
        absent (never issued OR already consumed OR expired). A second
        ``consume`` of the same nonce returns ``False`` — that's the F3
        replay-defense gate.
        """
        ...


class InMemoryNonceStore:
    """In-memory ``NonceStore`` for Phase 6 (D-02 seam pattern).

    Stdlib + ``secrets`` only — the dict IS the seam Phase 14's web phase
    swaps with a Redis-backed implementation that uses ``GETDEL`` for the
    atomic consume. Each ``issue`` records ``(nonce, expiry)`` where
    ``expiry = now + 5 min``; ``consume`` ``dict.pop``s the entry atomically
    (CPython GIL guarantee) and rejects expired entries.

    The ``now`` callable is injectable so tests can advance clocks for the
    "replay 6 minutes later" scenario without monkey-patching ``datetime``.
    """

    def __init__(self, *, now: Callable[[], datetime] | None = None) -> None:
        # secrets is imported lazily so importing this module doesn't pay
        # the CSPRNG initialization cost when the in-memory store isn't used.
        import secrets

        self._secrets = secrets
        self._store: dict[str, datetime] = {}
        self._now: Callable[[], datetime] = now or (lambda: datetime.now(UTC))

    async def issue(self) -> str:
        nonce = self._secrets.token_urlsafe(32)
        self._store[nonce] = self._now() + NONCE_TTL
        return nonce

    async def consume(self, nonce: str) -> bool:
        # dict.pop is atomic under the CPython GIL — the same guarantee
        # Redis GETDEL gives in the web phase.
        expiry = self._store.pop(nonce, None)
        if expiry is None:
            return False  # never issued OR already consumed
        if self._now() > expiry:
            return False  # expired — TTL is 5 minutes (NONCE_TTL)
        return True


# ── F7 helper — sub must be an OAuth ``sub`` claim, never email/username ────


# WR-03: a short, plain-alphanumeric subject (no provider prefix, no ``:``,
# no digits-only form) is the typical shape of a USERNAME — exactly the F7
# GitHub-takeover vector this function is supposed to catch. Accepting these
# silently means an operator who passes a GitHub username instead of the
# numeric id (a common F7 mistake) gets a binding the design says to refuse.
#
# Accepted "looks like an opaque sub" shapes:
#   * Provider-prefixed:    ``github:12345``, ``google:117_...``, ``auth0|abc...``
#   * Numeric-only id:      ``12345``, ``117345678``
#   * Opaque ≥16 chars:     ``abc123def456ghi7…`` (treated as an opaque id)
#
# Refused as username-shaped:
#   * Plain alpha 1–15 chars w/o ``:``: ``alice``, ``bob``, ``corp-admin``,
#     ``user_name`` — these are the F7 GitHub-username form.
_SUSPECT_USERNAME = __import__("re").compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,14}$")


def _assert_sub_is_oauth_sub(sub: str) -> None:
    """Refuse a binding subject that looks like an email or a bare username (F7).

    The OAuth ``sub`` claim is an opaque, provider-issued stable identifier
    (often a UUID, numeric id, or provider-prefixed string like
    ``github:12345``). It is NOT a username and it is NOT an email — both of
    which are mutable and the F7 GitHub-username-takeover vector exploits.

    Refuses (WR-03 strengthened heuristic):

    * Empty or all-whitespace — not a usable identifier.
    * Contains ``@`` — looks like an email (``alice@example.com``).
    * Plain alpha 1–15 chars without ``:`` or other provider-prefix marker
      — looks like a username (``alice``, ``bob``, ``corp-admin``).

    Accepts as "opaque sub-shaped": provider-prefixed (contains ``:`` or
    ``|``), numeric-only, or opaque length-≥16 strings.
    """
    if not sub or not sub.strip():
        raise InvalidSubject(
            "Binding subject must be the OAuth `sub` claim (non-empty); "
            "got empty/whitespace value."
        )
    if "@" in sub:
        raise InvalidSubject(
            f"Binding subject {sub!r} looks like an email — bind to the "
            "immutable OAuth `sub` claim, NEVER email (F7 / SEC-06 / "
            "GitHub-takeover defense)."
        )
    # WR-03: reject bare-username shapes. The provider-prefix markers ``:``
    # and ``|`` (auth0 style) are the well-known opaque-sub conventions;
    # presence of either is enough to accept the value as provider-issued.
    if (
        _SUSPECT_USERNAME.match(sub) is not None
        and ":" not in sub
        and "|" not in sub
    ):
        raise InvalidSubject(
            f"Binding subject {sub!r} looks like a bare username — bind to "
            "the provider-prefixed OAuth `sub` claim (e.g. 'github:12345'), "
            "NEVER a username (F7 / SEC-06 / GitHub-takeover defense — WR-03)."
        )


# ── bind() — the F3 / F7 / SEC-06 contract ──────────────────────────────────


async def bind(
    sub: str,
    did: str,
    proof: ProofPayload,
    signature: AttestedSignature,
    *,
    nonce_store: NonceStore,
    binding_store: dict[str, BindingRecord],
    expected_binding_endpoint: str,
    cache: DidDocCache,
    resolver: Callable[..., Awaitable[object]] = _default_resolve_did,
    http: Optional[Callable[[str], Awaitable[dict]]] = None,
    plc_resolver: Optional[Callable[[str, Optional[datetime]], Awaitable[dict]]] = None,
    now: Optional[Callable[[], datetime]] = None,
) -> BindingRecord:
    """Bind ``did`` to the OAuth ``sub`` after verifying the proof-of-control (SEC-06).

    Enforces, IN ORDER (the order matters — earlier gates are cheaper and
    block more attacker paths; irreversible state mutations run LAST among
    the proof-payload gates so a bad proof cannot burn a good nonce — WR-01):

    1. **F7 subject check** — ``sub`` must look like an OAuth ``sub`` claim
       (``_assert_sub_is_oauth_sub`` rejects emails / empty). The
       ``proof.sub`` must match ``sub`` (the signed payload binds the claim
       to the bind attempt).
    2. **Proof signature verifies** — ``verify_attestation`` against the
       proof's DID + the canonical payload-derived hash. A forged proof
       fails here (``InvalidProofSignature``). Includes the CR-01 gates:
       ``signature.did == did`` AND ``signature.over_content_hash ==
       SHA-256(JCS(proof))``.
    3. **F3 timestamp window** — ``|now - proof.issued_at| <= 2 min`` (pure
       compare, no state mutation). Outside the window raises ``StaleProof``.
    4. **F3 endpoint binding** — ``proof.binding_endpoint`` must match
       ``expected_binding_endpoint``. A captured-and-redirected proof raises
       ``EndpointMismatch``.
    5. **F3 single-use nonce** — ``nonce_store.consume(proof.nonce)`` must
       succeed (atomic get-delete). Runs LAST among proof-payload gates
       (WR-01) so a stale-timestamp / wrong-endpoint proof cannot burn a
       legitimate nonce. A replayed nonce raises ``NonceReused``.
    6. **Idempotency / subject-change (T-06-12 / F7)** — if
       ``binding_store[sub]`` already exists:
         * SAME ``did`` → return the existing record (no-op).
         * DIFFERENT ``did`` → ``SubjectChanged`` (NEVER silently overwrite).
       If ``did`` is already bound under a DIFFERENT ``sub`` anywhere in the
       store, also ``SubjectChanged`` — a sub change forces re-bind.
    7. **did:web domain control (SEC-06)** — for ``did:web:…``, call the
       resolver to confirm ``.well-known/did.json`` lists the bound key.
       Plan-02 ``resolve_did`` already does the fetch+vm-extract; a
       resolution failure raises ``DomainControlFailed``.

    On success: a fresh ``BindingRecord(sub, did, bound_at=now, proof)`` is
    inserted into ``binding_store[sub]`` and returned. The mapping is the
    seam Phase 14 swaps Redis behind.

    Note on the proof signature payload: the verifier expects an
    ``AttestedSignature`` whose ``over_content_hash`` matches the SHA-256 of
    the JCS-canonical proof payload. The CLI ``did bind`` command (Task 3)
    is responsible for producing the matching signature — this function
    only enforces that it verifies.
    """
    _now: Callable[[], datetime] = now or (lambda: datetime.now(UTC))
    current = _now()

    # 1. F7 subject — reject emails/empty BEFORE any signature math.
    _assert_sub_is_oauth_sub(sub)
    if proof.sub != sub:
        raise InvalidSubject(
            f"Proof payload `sub` {proof.sub!r} does not match the bind "
            f"attempt's `sub` {sub!r}; refusing to bind."
        )
    if proof.did != did:
        raise InvalidSubject(
            f"Proof payload `did` {proof.did!r} does not match the bind "
            f"attempt's `did` {did!r}; refusing to bind."
        )

    # CR-01 fix — F7 takeover defense closes two gaps in the previous
    # implementation. ``verify_attestation`` only proves "this signature is a
    # valid ed25519 over the recorded ``over_content_hash`` using the key
    # embedded in ``signature.did``". That alone does NOT prove the signature
    # attests to THIS proof payload (an attacker could submit a signature over
    # an unrelated hash), nor that the signer DID equals the bound DID (an
    # attacker could sign with their own DID's key while claiming the victim's
    # ``sub``). Both gaps are closed below BEFORE the verifier runs — fail
    # fast, and don't waste CPU on a signature we already know cannot prove
    # what we need.

    # CR-01 (a) — Signer DID must equal the bound DID. ``proof.did`` is
    # unauthenticated input (it's an unverified field of an unverified
    # payload); only the ``AttestedSignature`` carries cryptographic provenance,
    # so the signer-DID equality check has to live on the signature side.
    if signature.did != did:
        raise InvalidProofSignature(
            f"Proof signature.did {signature.did!r} does not match bound did "
            f"{did!r}; the signature does not attest to THIS DID. Refusing "
            "to bind (CR-01 / F7 GitHub-username-takeover defense)."
        )

    # CR-01 (b) — The signature's ``over_content_hash`` must equal the SHA-256
    # of the JCS-canonical proof payload presented to ``bind()``. Without this
    # check, an attacker could submit a signature over an unrelated hash; the
    # verifier would accept the ed25519 math, but the signature would not be
    # attesting to the (sub, nonce, endpoint, did) tuple of THIS bind attempt.
    import hashlib

    from folio_insights.revision.content_edit import _jcs_canonical_bytes

    expected_hash = hashlib.sha256(
        _jcs_canonical_bytes(proof.model_dump(mode="json"))
    ).hexdigest()
    if signature.over_content_hash != expected_hash:
        raise InvalidProofSignature(
            f"Proof signature.over_content_hash "
            f"{signature.over_content_hash!r} does not match SHA-256 of the "
            f"JCS-canonical proof payload {expected_hash!r}; the signature "
            "does not attest to THIS proof. Refusing to bind (CR-01 / F7)."
        )

    # 2. Proof signature must verify against the DID's signing-time key.
    #    The verifier resolves the DID doc via the same cache/resolver/http
    #    seams the rest of identity/ uses (Plan 02).  A tampered/forged
    #    proof signature fails closed — verify_attestation returns False on
    #    any failure mode, never raises (T-06-03 anti-spoofing default).
    sig_ok = await verify_attestation(
        signature.over_content_hash,
        signature,
        cache=cache,
        resolver=resolver,
        http=http,
        plc_resolver=plc_resolver,
    )
    if not sig_ok:
        raise InvalidProofSignature(
            f"Proof signature for sub={sub!r} did={did!r} failed verification."
        )

    # WR-01 fix — gate ordering: cheap, stateless checks (timestamp window,
    # endpoint pin) run BEFORE the irreversible nonce consume. Before the fix
    # the order was nonce-consume → timestamp → endpoint, which let a captured
    # signed proof carrying a stale timestamp or wrong endpoint burn a valid
    # nonce — the legitimate user would then hit ``NonceReused`` on a fresh
    # bind. Timestamp + endpoint are pure compares; nonce consume mutates
    # store state and must run LAST among the proof-payload gates.

    # 3. F3 timestamp ±2 min — pure compare, no state mutation.
    skew = abs(current - proof.issued_at)
    if skew > PROOF_CLOCK_SKEW:
        raise StaleProof(
            f"Proof issued_at {proof.issued_at!r} is {skew} from server time "
            f"{current!r}; max allowed skew is ±{PROOF_CLOCK_SKEW} (F3)."
        )

    # 4. F3 endpoint binding — the signed payload pins the endpoint. Pure
    #    compare; runs before the nonce consume so a captured proof issued
    #    against a different endpoint cannot burn a good nonce.
    if proof.binding_endpoint != expected_binding_endpoint:
        raise EndpointMismatch(
            f"Proof binding_endpoint {proof.binding_endpoint!r} does not "
            f"match expected {expected_binding_endpoint!r} (F3 / cross-"
            "endpoint replay defense)."
        )

    # 5. F3 single-use nonce — atomic get-delete via NonceStore.consume.
    #    IRREVERSIBLE; runs LAST among the proof-payload gates (WR-01) so a
    #    bad proof doesn't burn a good nonce.
    consumed = await nonce_store.consume(proof.nonce)
    if not consumed:
        raise NonceReused(
            f"Proof nonce {proof.nonce!r} was already consumed (or never "
            "issued / expired). Single-use replay defense (F3)."
        )

    # 6. Idempotency / subject-change.
    existing = binding_store.get(sub)
    if existing is not None:
        if existing.did == did:
            # T-06-12: idempotent no-op for repeat (sub, did) bind.
            return existing
        # Different did under the same sub — explicit conflict, NEVER a
        # silent overwrite.
        raise SubjectChanged(
            f"sub={sub!r} is already bound to {existing.did!r}; refusing to "
            f"silently rebind to {did!r}. The old binding must be unbound "
            "before a new one is accepted (F7 / SEC-06)."
        )
    # F7 reverse check — same did under a DIFFERENT sub already in the store.
    for other_sub, rec in binding_store.items():
        if rec.did == did and other_sub != sub:
            raise SubjectChanged(
                f"did={did!r} is already bound to sub={other_sub!r}; the "
                "subject changed (or a duplicate bind was attempted). "
                "Unbind the old record before re-binding (F7 / SEC-06)."
            )

    # 7. did:web domain-control side gate. The resolver does the
    #    .well-known/did.json fetch and key extraction; a failure means the
    #    domain does NOT publish the bound key, so the bind is rejected.
    if did.startswith("did:web:"):
        try:
            await resolver(
                did,
                at=None,
                cache=cache,
                http=http,
                plc_resolver=plc_resolver,
            )
        except Exception as exc:
            raise DomainControlFailed(
                f"did:web domain-control proof for {did!r} failed: {exc}"
            ) from exc

    # All gates green — record the binding and return it.
    record = BindingRecord(sub=sub, did=did, bound_at=current, proof=proof)
    binding_store[sub] = record
    return record


__all__ = [
    # Models
    "BindingRecord",
    "ProofPayload",
    # NonceStore seam
    "NonceStore",
    "InMemoryNonceStore",
    # Public surface
    "bind",
    # Constants
    "NONCE_TTL",
    "PROOF_CLOCK_SKEW",
    # Typed errors
    "BindingError",
    "NonceReused",
    "StaleProof",
    "EndpointMismatch",
    "SubjectChanged",
    "InvalidSubject",
    "InvalidProofSignature",
    "DomainControlFailed",
]
