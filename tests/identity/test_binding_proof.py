"""SEC-06 / F3 / F7 binding-proof tests (Plan 06-03 Task 1 + Task 4).

Covers the ``identity.binding.bind()`` rules — every gate has at least one
case here. Maps to the threat register (06-03-PLAN.md ``<threat_model>``):

* **T-06-10** F3 replay defense — single-use nonce + ±2-min window + endpoint
  pin. ``test_replayed_nonce_rejected``,
  ``test_skewed_timestamp_rejected``, ``test_endpoint_mismatch_rejected``.
* **T-06-11** F7 GitHub-username-takeover — bind to ``sub``, refuse
  email/username. ``test_email_sub_refused``.
* **T-06-12** silent re-bind — idempotency / subject-change.
  ``test_idempotent_repeat_bind``, ``test_subject_change_rejected``.
* **T-06-13** did:web domain control — covered indirectly via the resolver;
  not exercised in unit-binding tests (Plan 02 sign/verify tests cover it).

All tests use the ``InMemoryNonceStore`` + a controllable ``now`` callable so
the "replay 6 min later" / "skewed timestamp" cases don't monkey-patch
``datetime``.
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from folio_insights.identity import (
    EndpointMismatch,
    InMemoryDidDocCache,
    InMemoryNonceStore,
    InvalidProofSignature,
    InvalidSubject,
    NonceReused,
    ProofPayload,
    StaleProof,
    SubjectChanged,
    bind,
    did_key_from_public,
    sign_attestation,
)
from folio_insights.revision.content_edit import _jcs_canonical_bytes

pytestmark = pytest.mark.identity

_BINDING_ENDPOINT = "https://folio-insights.example/binding"
_VALID_SUB = "github:12345"  # an opaque OAuth sub value (numeric id w/ provider prefix)


# ── helpers ─────────────────────────────────────────────────────────────────


def _make_didkey() -> tuple[Ed25519PrivateKey, str]:
    """Generate an ed25519 keypair + its did:key form."""
    sk = Ed25519PrivateKey.generate()
    raw = sk.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return sk, did_key_from_public(raw)


def _sign_proof(
    proof: ProofPayload,
    sk: Ed25519PrivateKey,
    did: str,
    *,
    signed_at: datetime,
):
    """Sign the canonicalized proof payload with the DID's key.

    Returns the AttestedSignature carrying the proof-hash + ed25519 signature.
    The signed payload is the SHA-256 hex of the JCS-canonical proof dict —
    the verifier recomputes the same hash because we pass ``proof_hash`` as
    the verification payload to ``verify_attestation``.
    """
    payload = proof.model_dump(mode="json")
    canon = _jcs_canonical_bytes(payload)
    proof_hash = hashlib.sha256(canon).hexdigest()
    key_id = f"{did}#{did.removeprefix('did:key:')}"
    return sign_attestation(
        proof_hash,
        sk,
        did,
        "role_assertion",  # the proof-of-control is itself a role assertion
        signing_key_id=key_id,
        did_doc_snapshot_at=None,
        now=signed_at,
    )


async def _issue_nonce(store: InMemoryNonceStore) -> str:
    return await store.issue()


# ── happy path ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_valid_proof_binds(doc_cache) -> None:
    """A fresh nonce + in-window timestamp + matching endpoint + valid sig binds."""
    sk, did = _make_didkey()
    nonce_store = InMemoryNonceStore()
    nonce = await _issue_nonce(nonce_store)
    binding_store: dict = {}
    now = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
    proof = ProofPayload(
        sub=_VALID_SUB,
        nonce=nonce,
        issued_at=now,
        binding_endpoint=_BINDING_ENDPOINT,
        did=did,
    )
    sig = _sign_proof(proof, sk, did, signed_at=now)

    record = await bind(
        _VALID_SUB,
        did,
        proof,
        sig,
        nonce_store=nonce_store,
        binding_store=binding_store,
        expected_binding_endpoint=_BINDING_ENDPOINT,
        cache=doc_cache,
        now=lambda: now,
    )

    assert record.sub == _VALID_SUB
    assert record.did == did
    assert record.bound_at == now
    assert binding_store[_VALID_SUB] is record


# ── F3 — single-use nonce, replay rejected (T-06-10) ────────────────────────


@pytest.mark.asyncio
async def test_replayed_nonce_rejected(doc_cache) -> None:
    """A second bind reusing the same nonce raises NonceReused (F3)."""
    sk, did = _make_didkey()
    nonce_store = InMemoryNonceStore()
    nonce = await _issue_nonce(nonce_store)
    binding_store: dict = {}
    now = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
    proof = ProofPayload(
        sub=_VALID_SUB,
        nonce=nonce,
        issued_at=now,
        binding_endpoint=_BINDING_ENDPOINT,
        did=did,
    )
    sig = _sign_proof(proof, sk, did, signed_at=now)

    # First bind consumes the nonce successfully.
    await bind(
        _VALID_SUB, did, proof, sig,
        nonce_store=nonce_store, binding_store=binding_store,
        expected_binding_endpoint=_BINDING_ENDPOINT, cache=doc_cache,
        now=lambda: now,
    )

    # Second bind with the SAME nonce — replay — must raise NonceReused.
    # Use a fresh sub/did so the idempotency path doesn't short-circuit before
    # the nonce check; but the nonce check runs AFTER subject + signature
    # checks, so we need a fresh DID (and matching proof.did) to reach the
    # nonce gate. Easier: try to re-bind the SAME sub+did — but bind() returns
    # the existing record on (sub, did) match BEFORE consuming the nonce on
    # the second call... no, looking at the implementation: idempotency check
    # is step 6, AFTER nonce-consume (step 3). So the second consume fails
    # first. Confirmed correct.
    with pytest.raises(NonceReused):
        await bind(
            _VALID_SUB, did, proof, sig,
            nonce_store=nonce_store, binding_store={},  # fresh store
            expected_binding_endpoint=_BINDING_ENDPOINT, cache=doc_cache,
            now=lambda: now,
        )


@pytest.mark.asyncio
async def test_nonce_expired_after_6min(doc_cache) -> None:
    """A nonce older than the 5-min TTL fails consume → NonceReused at bind."""
    sk, did = _make_didkey()
    issue_at = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
    # The nonce store's `now` is independent of the bind's `now`; issue at T0,
    # then advance the store's clock 6 minutes for consume.
    store_clock = {"t": issue_at}
    nonce_store = InMemoryNonceStore(now=lambda: store_clock["t"])
    nonce = await _issue_nonce(nonce_store)

    # Advance the store clock 6 minutes — past the 5-min TTL.
    store_clock["t"] = issue_at + timedelta(minutes=6)

    binding_store: dict = {}
    # The proof's issued_at is "now" (same as bind's now) so the ±2-min
    # window passes; only the nonce TTL fails.
    bind_now = store_clock["t"]
    proof = ProofPayload(
        sub=_VALID_SUB, nonce=nonce, issued_at=bind_now,
        binding_endpoint=_BINDING_ENDPOINT, did=did,
    )
    sig = _sign_proof(proof, sk, did, signed_at=bind_now)
    with pytest.raises(NonceReused):
        await bind(
            _VALID_SUB, did, proof, sig,
            nonce_store=nonce_store, binding_store=binding_store,
            expected_binding_endpoint=_BINDING_ENDPOINT, cache=doc_cache,
            now=lambda: bind_now,
        )


# ── F3 — ±2-min timestamp window (T-06-10) ──────────────────────────────────


@pytest.mark.asyncio
async def test_skewed_timestamp_rejected(doc_cache) -> None:
    """A proof timestamp more than 2 min off server clock raises StaleProof (F3)."""
    sk, did = _make_didkey()
    nonce_store = InMemoryNonceStore()
    nonce = await _issue_nonce(nonce_store)
    binding_store: dict = {}
    server_now = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
    # Proof was issued 3 minutes ago — outside the ±2-min window.
    proof_issued = server_now - timedelta(minutes=3)
    proof = ProofPayload(
        sub=_VALID_SUB, nonce=nonce, issued_at=proof_issued,
        binding_endpoint=_BINDING_ENDPOINT, did=did,
    )
    sig = _sign_proof(proof, sk, did, signed_at=proof_issued)
    with pytest.raises(StaleProof):
        await bind(
            _VALID_SUB, did, proof, sig,
            nonce_store=nonce_store, binding_store=binding_store,
            expected_binding_endpoint=_BINDING_ENDPOINT, cache=doc_cache,
            now=lambda: server_now,
        )


# ── F3 — endpoint URL mismatch (T-06-10) ────────────────────────────────────


@pytest.mark.asyncio
async def test_endpoint_mismatch_rejected(doc_cache) -> None:
    """Cross-endpoint replay: proof endpoint != expected → EndpointMismatch (F3)."""
    sk, did = _make_didkey()
    nonce_store = InMemoryNonceStore()
    nonce = await _issue_nonce(nonce_store)
    binding_store: dict = {}
    now = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
    # Proof was issued against a DIFFERENT endpoint — a captured proof from
    # ANOTHER server cannot be replayed here.
    proof = ProofPayload(
        sub=_VALID_SUB, nonce=nonce, issued_at=now,
        binding_endpoint="https://attacker.example/binding",
        did=did,
    )
    sig = _sign_proof(proof, sk, did, signed_at=now)
    with pytest.raises(EndpointMismatch):
        await bind(
            _VALID_SUB, did, proof, sig,
            nonce_store=nonce_store, binding_store=binding_store,
            expected_binding_endpoint=_BINDING_ENDPOINT, cache=doc_cache,
            now=lambda: now,
        )


# ── F7 — bind to OAuth `sub`, refuse email/username (T-06-11) ───────────────


@pytest.mark.asyncio
async def test_email_sub_refused(doc_cache) -> None:
    """A binding subject that looks like an email raises InvalidSubject (F7)."""
    sk, did = _make_didkey()
    nonce_store = InMemoryNonceStore()
    nonce = await _issue_nonce(nonce_store)
    binding_store: dict = {}
    now = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
    email_sub = "alice@example.com"
    proof = ProofPayload(
        sub=email_sub, nonce=nonce, issued_at=now,
        binding_endpoint=_BINDING_ENDPOINT, did=did,
    )
    sig = _sign_proof(proof, sk, did, signed_at=now)
    with pytest.raises(InvalidSubject):
        await bind(
            email_sub, did, proof, sig,
            nonce_store=nonce_store, binding_store=binding_store,
            expected_binding_endpoint=_BINDING_ENDPOINT, cache=doc_cache,
            now=lambda: now,
        )


@pytest.mark.asyncio
async def test_empty_sub_refused(doc_cache) -> None:
    """An empty subject is refused with InvalidSubject (F7 defensive)."""
    sk, did = _make_didkey()
    nonce_store = InMemoryNonceStore()
    nonce = await _issue_nonce(nonce_store)
    binding_store: dict = {}
    now = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
    proof = ProofPayload(
        sub="", nonce=nonce, issued_at=now,
        binding_endpoint=_BINDING_ENDPOINT, did=did,
    )
    sig = _sign_proof(proof, sk, did, signed_at=now)
    with pytest.raises(InvalidSubject):
        await bind(
            "", did, proof, sig,
            nonce_store=nonce_store, binding_store=binding_store,
            expected_binding_endpoint=_BINDING_ENDPOINT, cache=doc_cache,
            now=lambda: now,
        )


# ── F7 — subject-change detection forces re-bind (T-06-11) ──────────────────


@pytest.mark.asyncio
async def test_subject_change_rejected(doc_cache) -> None:
    """The same DID under a DIFFERENT sub raises SubjectChanged (F7)."""
    sk, did = _make_didkey()
    nonce_store = InMemoryNonceStore()
    binding_store: dict = {}
    now = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)

    # First bind: sub-A, did.
    sub_a = "github:11111"
    nonce_a = await _issue_nonce(nonce_store)
    proof_a = ProofPayload(
        sub=sub_a, nonce=nonce_a, issued_at=now,
        binding_endpoint=_BINDING_ENDPOINT, did=did,
    )
    sig_a = _sign_proof(proof_a, sk, did, signed_at=now)
    await bind(
        sub_a, did, proof_a, sig_a,
        nonce_store=nonce_store, binding_store=binding_store,
        expected_binding_endpoint=_BINDING_ENDPOINT, cache=doc_cache,
        now=lambda: now,
    )

    # Second bind: same did, DIFFERENT sub-B — must raise SubjectChanged.
    sub_b = "github:22222"
    nonce_b = await _issue_nonce(nonce_store)
    proof_b = ProofPayload(
        sub=sub_b, nonce=nonce_b, issued_at=now,
        binding_endpoint=_BINDING_ENDPOINT, did=did,
    )
    sig_b = _sign_proof(proof_b, sk, did, signed_at=now)
    with pytest.raises(SubjectChanged):
        await bind(
            sub_b, did, proof_b, sig_b,
            nonce_store=nonce_store, binding_store=binding_store,
            expected_binding_endpoint=_BINDING_ENDPOINT, cache=doc_cache,
            now=lambda: now,
        )


@pytest.mark.asyncio
async def test_different_did_for_same_sub_rejected(doc_cache) -> None:
    """A DIFFERENT did under the SAME sub raises SubjectChanged (F7) — never silent."""
    sk_x, did_x = _make_didkey()
    sk_y, did_y = _make_didkey()
    nonce_store = InMemoryNonceStore()
    binding_store: dict = {}
    now = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)

    # First bind: sub, did_x.
    nonce_x = await _issue_nonce(nonce_store)
    proof_x = ProofPayload(
        sub=_VALID_SUB, nonce=nonce_x, issued_at=now,
        binding_endpoint=_BINDING_ENDPOINT, did=did_x,
    )
    sig_x = _sign_proof(proof_x, sk_x, did_x, signed_at=now)
    await bind(
        _VALID_SUB, did_x, proof_x, sig_x,
        nonce_store=nonce_store, binding_store=binding_store,
        expected_binding_endpoint=_BINDING_ENDPOINT, cache=doc_cache,
        now=lambda: now,
    )

    # Second bind: same sub, DIFFERENT did_y — must raise SubjectChanged.
    nonce_y = await _issue_nonce(nonce_store)
    proof_y = ProofPayload(
        sub=_VALID_SUB, nonce=nonce_y, issued_at=now,
        binding_endpoint=_BINDING_ENDPOINT, did=did_y,
    )
    sig_y = _sign_proof(proof_y, sk_y, did_y, signed_at=now)
    with pytest.raises(SubjectChanged):
        await bind(
            _VALID_SUB, did_y, proof_y, sig_y,
            nonce_store=nonce_store, binding_store=binding_store,
            expected_binding_endpoint=_BINDING_ENDPOINT, cache=doc_cache,
            now=lambda: now,
        )


# ── T-06-12 — idempotent repeat (sub, did) bind (no-op, never silent update) ─


@pytest.mark.asyncio
async def test_idempotent_repeat_bind(doc_cache) -> None:
    """A repeat (sub, did) bind returns the EXISTING record unchanged (T-06-12)."""
    sk, did = _make_didkey()
    nonce_store = InMemoryNonceStore()
    binding_store: dict = {}
    now = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)

    nonce_1 = await _issue_nonce(nonce_store)
    proof_1 = ProofPayload(
        sub=_VALID_SUB, nonce=nonce_1, issued_at=now,
        binding_endpoint=_BINDING_ENDPOINT, did=did,
    )
    sig_1 = _sign_proof(proof_1, sk, did, signed_at=now)
    first = await bind(
        _VALID_SUB, did, proof_1, sig_1,
        nonce_store=nonce_store, binding_store=binding_store,
        expected_binding_endpoint=_BINDING_ENDPOINT, cache=doc_cache,
        now=lambda: now,
    )

    # Second bind: same (sub, did), DIFFERENT nonce + later time (the proof
    # is "fresh" but the binding is already in place).
    later = now + timedelta(seconds=30)
    nonce_2 = await _issue_nonce(nonce_store)
    proof_2 = ProofPayload(
        sub=_VALID_SUB, nonce=nonce_2, issued_at=later,
        binding_endpoint=_BINDING_ENDPOINT, did=did,
    )
    sig_2 = _sign_proof(proof_2, sk, did, signed_at=later)
    second = await bind(
        _VALID_SUB, did, proof_2, sig_2,
        nonce_store=nonce_store, binding_store=binding_store,
        expected_binding_endpoint=_BINDING_ENDPOINT, cache=doc_cache,
        now=lambda: later,
    )

    # T-06-12: idempotency — same record, NOT a silent update with the new
    # proof or bound_at.
    assert second is first
    assert second.bound_at == now  # unchanged from first bind
    assert second.proof == proof_1  # original proof preserved


# ── Proof-signature verification (DID-04) ───────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_proof_signature_rejected(doc_cache) -> None:
    """A proof signed by a DIFFERENT key (not the DID's) raises InvalidProofSignature."""
    sk_bound, did_bound = _make_didkey()
    sk_other, _did_other = _make_didkey()
    nonce_store = InMemoryNonceStore()
    nonce = await _issue_nonce(nonce_store)
    binding_store: dict = {}
    now = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
    proof = ProofPayload(
        sub=_VALID_SUB, nonce=nonce, issued_at=now,
        binding_endpoint=_BINDING_ENDPOINT, did=did_bound,
    )
    # Sign with the WRONG key — the DID embeds did_bound's public key, but
    # we sign with sk_other. verify_attestation must reject this.
    sig = _sign_proof(proof, sk_other, did_bound, signed_at=now)
    with pytest.raises(InvalidProofSignature):
        await bind(
            _VALID_SUB, did_bound, proof, sig,
            nonce_store=nonce_store, binding_store=binding_store,
            expected_binding_endpoint=_BINDING_ENDPOINT, cache=doc_cache,
            now=lambda: now,
        )


# ── CR-01 — F7 takeover defense: signer DID + signed hash must match proof ──


@pytest.mark.asyncio
async def test_signature_did_mismatch_rejected(doc_cache) -> None:
    """CR-01: ``signature.did`` must equal the bound ``did`` (F7 takeover defense).

    A signature whose ``did`` is anything other than the DID being bound
    cannot attest to the bind — even if the ed25519 math over the proof hash
    is valid. ``bind()`` rejects the signature with ``InvalidProofSignature``
    BEFORE running ``verify_attestation``.
    """
    sk_attacker, did_attacker = _make_didkey()
    sk_victim, did_victim = _make_didkey()
    nonce_store = InMemoryNonceStore()
    nonce = await _issue_nonce(nonce_store)
    binding_store: dict = {}
    now = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)

    # The proof legitimately names did_victim — the attacker still wants to
    # bind did_victim, just under their own signature.
    proof = ProofPayload(
        sub=_VALID_SUB, nonce=nonce, issued_at=now,
        binding_endpoint=_BINDING_ENDPOINT, did=did_victim,
    )
    # The signature is over the right proof hash, with the right ed25519 key
    # for the attacker's DID — but ``signature.did`` is the attacker's, not
    # the bound did_victim.
    sig = _sign_proof(proof, sk_attacker, did_attacker, signed_at=now)
    with pytest.raises(InvalidProofSignature):
        await bind(
            _VALID_SUB, did_victim, proof, sig,
            nonce_store=nonce_store, binding_store=binding_store,
            expected_binding_endpoint=_BINDING_ENDPOINT, cache=doc_cache,
            now=lambda: now,
        )


@pytest.mark.asyncio
async def test_signature_hash_does_not_cover_proof_rejected(doc_cache) -> None:
    """CR-01: ``signature.over_content_hash`` must equal SHA-256(JCS(proof)).

    A signature over an unrelated hash — even one that ed25519-verifies
    against the bound DID's key — is not proof-of-control for THIS bind
    attempt. ``bind()`` recomputes the expected hash and rejects mismatch.
    """
    import hashlib as _hl

    sk, did = _make_didkey()
    nonce_store = InMemoryNonceStore()
    nonce = await _issue_nonce(nonce_store)
    binding_store: dict = {}
    now = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
    proof = ProofPayload(
        sub=_VALID_SUB, nonce=nonce, issued_at=now,
        binding_endpoint=_BINDING_ENDPOINT, did=did,
    )
    # Sign an UNRELATED hash with the bound DID's real key. ed25519 will
    # validate; the hash-mismatch gate must still reject.
    unrelated_hash = _hl.sha256(b"unrelated").hexdigest()
    key_id = f"{did}#{did.removeprefix('did:key:')}"
    sig = sign_attestation(
        unrelated_hash, sk, did, "role_assertion",
        signing_key_id=key_id, did_doc_snapshot_at=None, now=now,
    )
    with pytest.raises(InvalidProofSignature):
        await bind(
            _VALID_SUB, did, proof, sig,
            nonce_store=nonce_store, binding_store=binding_store,
            expected_binding_endpoint=_BINDING_ENDPOINT, cache=doc_cache,
            now=lambda: now,
        )


@pytest.mark.asyncio
async def test_attacker_cannot_bind_victim_sub_with_own_did(doc_cache) -> None:
    """CR-01: full F7 takeover scenario — attacker tries to bind victim_sub to did_atk.

    The attacker:
      1. Knows the victim's OAuth ``sub`` (e.g., from an enumerable GitHub id).
      2. Generates their own ed25519 keypair and derives ``did_atk``.
      3. Obtains a valid nonce from the public ``nonce_store.issue()``.
      4. Builds a proof claiming ``victim_sub`` for ``did_atk``.
      5. Signs ANY hash with their own key (e.g., the SHA-256 of unrelated
         bytes) and submits an ``AttestedSignature(did=did_atk, …)``.

    Before the CR-01 fix, ``bind()`` accepted this: the verifier confirmed
    "did_atk's key validly signed sig.over_content_hash", and bind's only
    other checks (subject sanity, nonce, timestamp, endpoint, proof.did ==
    did) all passed. The binding silently hijacked victim_sub → did_atk.

    After the fix: the hash-mismatch check (CR-01 b) rejects the signature
    BEFORE verify_attestation runs, because the attacker's signed hash is
    not the SHA-256 of THIS proof payload. Even if the attacker had also
    signed the correct proof hash, the CR-01 (a) DID-mismatch check would
    reject ``signature.did=did_atk != did_atk`` only if they tried to bind
    a *different* DID — which is the symmetric attack the (a) check closes.
    """
    import hashlib as _hl

    sk_atk, did_atk = _make_didkey()
    victim_sub = "github:99999"  # the victim's OAuth sub claim
    nonce_store = InMemoryNonceStore()
    nonce = await _issue_nonce(nonce_store)
    binding_store: dict = {}
    now = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)

    # Attacker builds a proof claiming victim_sub for THEIR did_atk.
    proof = ProofPayload(
        sub=victim_sub, nonce=nonce, issued_at=now,
        binding_endpoint=_BINDING_ENDPOINT, did=did_atk,
    )
    # The attacker signs an UNRELATED hash with their own key. The ed25519
    # math is fine (it's a valid signature by did_atk's key over that hash),
    # but the hash isn't the hash of THIS proof.
    unrelated_hash = _hl.sha256(b"attacker chosen prefix").hexdigest()
    key_id = f"{did_atk}#{did_atk.removeprefix('did:key:')}"
    sig = sign_attestation(
        unrelated_hash, sk_atk, did_atk, "role_assertion",
        signing_key_id=key_id, did_doc_snapshot_at=None, now=now,
    )

    # The bind MUST be rejected. Before CR-01, this scenario succeeded and the
    # attacker hijacked victim_sub → did_atk in binding_store.
    with pytest.raises(InvalidProofSignature):
        await bind(
            victim_sub, did_atk, proof, sig,
            nonce_store=nonce_store, binding_store=binding_store,
            expected_binding_endpoint=_BINDING_ENDPOINT, cache=doc_cache,
            now=lambda: now,
        )
    # And nothing was inserted into the binding store.
    assert victim_sub not in binding_store


# ── WR-01 — stale/wrong-endpoint proof must NOT consume the nonce ──────────


@pytest.mark.asyncio
async def test_stale_proof_does_not_consume_nonce(doc_cache) -> None:
    """WR-01: a StaleProof rejection must NOT burn the nonce.

    Order of gates: timestamp + endpoint (pure compares) run BEFORE the
    irreversible nonce consume. A captured proof with a stale timestamp must
    fail at the StaleProof gate without touching the nonce store, so a
    legitimate user can still consume the same nonce later.
    """
    sk, did = _make_didkey()
    nonce_store = InMemoryNonceStore()
    nonce = await _issue_nonce(nonce_store)
    binding_store: dict = {}
    server_now = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)

    # Stale proof — 5 min before server time (outside the ±2 min window).
    stale_issued = server_now - timedelta(minutes=5)
    proof = ProofPayload(
        sub=_VALID_SUB, nonce=nonce, issued_at=stale_issued,
        binding_endpoint=_BINDING_ENDPOINT, did=did,
    )
    sig = _sign_proof(proof, sk, did, signed_at=stale_issued)
    with pytest.raises(StaleProof):
        await bind(
            _VALID_SUB, did, proof, sig,
            nonce_store=nonce_store, binding_store=binding_store,
            expected_binding_endpoint=_BINDING_ENDPOINT, cache=doc_cache,
            now=lambda: server_now,
        )

    # Nonce must still be consumable — the stale-proof rejection didn't burn it.
    assert await nonce_store.consume(nonce) is True


@pytest.mark.asyncio
async def test_endpoint_mismatch_does_not_consume_nonce(doc_cache) -> None:
    """WR-01: an EndpointMismatch rejection must NOT burn the nonce."""
    sk, did = _make_didkey()
    nonce_store = InMemoryNonceStore()
    nonce = await _issue_nonce(nonce_store)
    binding_store: dict = {}
    now = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
    proof = ProofPayload(
        sub=_VALID_SUB, nonce=nonce, issued_at=now,
        binding_endpoint="https://attacker.example/binding", did=did,
    )
    sig = _sign_proof(proof, sk, did, signed_at=now)
    with pytest.raises(EndpointMismatch):
        await bind(
            _VALID_SUB, did, proof, sig,
            nonce_store=nonce_store, binding_store=binding_store,
            expected_binding_endpoint=_BINDING_ENDPOINT, cache=doc_cache,
            now=lambda: now,
        )

    # Nonce still consumable.
    assert await nonce_store.consume(nonce) is True


# ── WR-03 — strengthened F7 subject heuristic (bare-username rejected) ─────


@pytest.mark.asyncio
async def test_bare_username_sub_refused(doc_cache) -> None:
    """WR-03: a plain ``alice`` subject is refused (F7 GitHub-username form)."""
    sk, did = _make_didkey()
    nonce_store = InMemoryNonceStore()
    nonce = await _issue_nonce(nonce_store)
    binding_store: dict = {}
    now = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
    bad_sub = "alice"
    proof = ProofPayload(
        sub=bad_sub, nonce=nonce, issued_at=now,
        binding_endpoint=_BINDING_ENDPOINT, did=did,
    )
    sig = _sign_proof(proof, sk, did, signed_at=now)
    with pytest.raises(InvalidSubject):
        await bind(
            bad_sub, did, proof, sig,
            nonce_store=nonce_store, binding_store=binding_store,
            expected_binding_endpoint=_BINDING_ENDPOINT, cache=doc_cache,
            now=lambda: now,
        )


@pytest.mark.asyncio
async def test_provider_prefixed_numeric_sub_accepted(doc_cache) -> None:
    """WR-03 boundary: ``github:12345`` (provider-prefixed) still binds successfully."""
    sk, did = _make_didkey()
    nonce_store = InMemoryNonceStore()
    nonce = await _issue_nonce(nonce_store)
    binding_store: dict = {}
    now = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
    proof = ProofPayload(
        sub=_VALID_SUB, nonce=nonce, issued_at=now,
        binding_endpoint=_BINDING_ENDPOINT, did=did,
    )
    sig = _sign_proof(proof, sk, did, signed_at=now)
    record = await bind(
        _VALID_SUB, did, proof, sig,
        nonce_store=nonce_store, binding_store=binding_store,
        expected_binding_endpoint=_BINDING_ENDPOINT, cache=doc_cache,
        now=lambda: now,
    )
    assert record.sub == _VALID_SUB
