"""DidDocCache — the historical-key cache seam (D-11).

MIRRORS the Phase-5 ``revision/store.py`` ``ShardStore`` decision (D-02): a thin
async ``Protocol`` over an in-memory dict, keyed by ``(did, signed_at)``, that
caches the signing-time DID-document snapshot + the resolved verification key
material. Phase 13 swaps a persistent backend in behind the IDENTICAL async
interface; no caller signature changes.

Why this seam exists (SEC-05 / Pitfall F2): every ``AttestedSignature`` carries
``signing_key_id`` + ``did_doc_snapshot_at``; verification resolves the key
**at signing time**, not the DID's *current* key. For did:web that means the
did.json at ``signed_at`` (a rotated current did.json must NOT retro-validate
a historical signature). For did:plc that means the operation valid at
``signed_at`` in the PLC op log. The cache makes that lookup O(1) instead of
a network round-trip per verify — and is the gate the rotation-survival test
(EC3) exercises.

Boundary: this module stays storage-library-FREE. Phase 13 fills aiosqlite/
Oxigraph behind the same interface; in this phase the dict IS the cache.
"""
from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class DidDocSnapshot(BaseModel):
    """Frozen-at-signing-time DID-document snapshot the verifier resolves against.

    Pure Pydantic, ``extra="forbid"`` (mirrors the envelope discipline).
    Holds the minimum the verifier needs:

    * ``did`` — the DID this snapshot belongs to (for sanity).
    * ``fetched_at`` — wall-clock at which the snapshot was taken (for cache
      bookkeeping; NOT the signing time — that is the cache key's second leg).
    * ``verification_method_id`` — the DID URL + ``#fragment`` of the key in
      use at the snapshot moment (matches ``AttestedSignature.signing_key_id``).
    * ``public_key_multibase`` — the ed25519 public key in did:key-style
      multibase (``z`` + base58btc of the 0xed01-prefixed raw 32-byte key).
      Storing it in this single canonical form lets verifier.py recover an
      ``Ed25519PublicKey`` without a method-specific code path.
    * ``raw_doc`` — optional opaque dict copy of the resolved did.json / PLC op
      payload, kept for audit / debugging. Not used by the verifier hot path.
    """
    model_config = ConfigDict(extra="forbid")

    did: str
    fetched_at: datetime
    verification_method_id: str
    public_key_multibase: str
    raw_doc: dict | None = Field(default=None)


@runtime_checkable
class DidDocCache(Protocol):
    """Async historical-key cache seam (D-11).

    Keyed by ``(did, signed_at)``. The Phase-5 ``ShardStore`` is the structural
    template — same async shape, same "Phase 13 swaps persistence behind the
    identical interface" docstring contract. Tests use ``InMemoryDidDocCache``;
    Phase 13 will provide an aiosqlite/Oxigraph implementation that this same
    Protocol accepts without any caller change.
    """

    async def get(self, key: tuple[str, datetime]) -> DidDocSnapshot | None:
        """Return the snapshot for ``(did, signed_at)`` or ``None`` if uncached."""
        ...

    async def put(self, key: tuple[str, datetime], snapshot: DidDocSnapshot) -> None:
        """Store ``snapshot`` under ``(did, signed_at)``; overwrite if present."""
        ...


class InMemoryDidDocCache:
    """Process-local in-memory ``DidDocCache`` (D-11; mirrors ``InMemoryShardStore``).

    Stdlib + Pydantic only — the dict IS the seam Phase 13 replaces with a
    persistent (aiosqlite / Oxigraph) backend behind the identical async
    ``Protocol``. Reset per construction (per-test isolation).
    """

    def __init__(self) -> None:
        self._d: dict[tuple[str, datetime], DidDocSnapshot] = {}

    async def get(self, key: tuple[str, datetime]) -> DidDocSnapshot | None:
        return self._d.get(key)

    async def put(self, key: tuple[str, datetime], snapshot: DidDocSnapshot) -> None:
        self._d[key] = snapshot


__all__ = [
    "DidDocCache",
    "DidDocSnapshot",
    "InMemoryDidDocCache",
]
