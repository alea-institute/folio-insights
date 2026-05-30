"""Shared CLI signing+verification helper (CR-01 closure).

Wraps the Phase 6 ``sign_attestation`` + ``verify_attestation`` round-trip in
ONE place so every governance CLI command performs the same belt-and-
suspenders gate before calling ``log.append``:

  1. Compute the canonical signature payload via ``event.signature_payload()``.
  2. ``sign_attestation`` over the payload with the operator's signing key.
  3. ``verify_attestation`` against the SAME payload — refuses any signature
     whose did doesn't decode to the same public key the cache resolves for
     ``sig.did``. Phase 6 fail-closed contract: returns False; never raises.
  4. If verification fails, raise ``InvalidSignature`` (from
     ``governance.log``) so the CLI surface reports a uniform error and the
     log layer never sees a self-inconsistent signature.

Why a shared helper:
  * Before CR-01, no CLI invoked ``verify_attestation`` at all. A
    corpus_admin could sign a role assertion with an arbitrary private key
    that did NOT correspond to their stated did, and ``log.append`` accepted
    it (the log layer's own ``verify_attestation`` belt was documented but
    never wired — the ``InvalidSignature`` exception was defined in
    ``governance/log.py`` but never raised).
  * The log layer can't host the verification: D-04 keeps
    ``src/folio_insights/governance/`` on stdlib + Pydantic only, and the
    ``DidDocCache`` would have to be threaded through ``log.append`` (a
    signature change every Phase 13 backend would inherit). The CLI layer
    is the natural seam.
  * The 8+ governance CLI commands each call this helper after building
    their event and before appending. Keeps the per-command body short and
    guarantees no command can accidentally skip the verify step.

D-16 note: this helper lives outside the contest / supersede / retract
modules (cli/_signing.py, NOT contest.py / supersede.py / retract.py) and is
imported by ALL governance CLI commands uniformly, so the three-way grep
guard (test_grep_guard_three_way_disambiguation.py) is unaffected — the
forbidden cross-imports are between contest/supersede/retract themselves,
not between those commands and a neutral CLI utility.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from folio_insights.governance.log import InvalidSignature

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )

    from folio_insights.governance.events import GovernanceEvent
    from folio_insights.identity.cache import DidDocCache
    from folio_insights.shards.envelope import AttestedSignature, SignedAction


async def sign_and_verify_event(
    event: "GovernanceEvent",
    *,
    signing_key: "Ed25519PrivateKey",
    did: str,
    action: "SignedAction",
    signing_key_id: str,
    did_doc_snapshot_at: Optional[datetime],
    now: datetime,
    cache: "DidDocCache",
) -> "AttestedSignature":
    """Sign + verify-round-trip an event, returning the verified signature.

    Order:
      1. ``payload_hash = event.signature_payload().decode("utf-8")``.
      2. ``sig = sign_attestation(content_hash=payload_hash, ...)``.
      3. ``ok = await verify_attestation(payload_hash, sig, cache=cache)``.
      4. If ``ok`` is False, raise ``InvalidSignature``. Otherwise return ``sig``.

    The cache parameter is mandatory — there is no "skip verification" path.
    Genesis-row callers (the corpus_init bootstrap) DO NOT use this helper;
    they sign with a placeholder cache hop because their signature is
    verified structurally (signer == subject == admin_did) at the log layer's
    genesis carve-out. Every NON-genesis event MUST pass through this helper.

    Raises:
        InvalidSignature: ``verify_attestation`` returned False. The caller's
            ``log.append`` will never see a self-inconsistent signature.
    """
    from folio_insights.identity.signer import sign_attestation
    from folio_insights.identity.verifier import verify_attestation

    payload_hash = event.signature_payload().decode("utf-8")
    sig = sign_attestation(
        content_hash=payload_hash,
        signing_key=signing_key,
        did=did,
        action=action,
        signing_key_id=signing_key_id,
        did_doc_snapshot_at=did_doc_snapshot_at,
        now=now,
    )
    ok = await verify_attestation(payload_hash, sig, cache=cache)
    if not ok:
        raise InvalidSignature(
            f"verify_attestation refused the signature for {action} event "
            f"(signer did={did}). The signing key's public material does "
            f"not match the public key resolved for {did} via the "
            "DidDocCache. CR-01 belt-and-suspenders refusal."
        )
    return sig


__all__ = ["sign_and_verify_event"]
