"""Phase 6 DID substrate (§6.5) — identity/ package.

Hosts the DID-signed attestation crypto backbone: client-side local keystore
(``keys.py``), DID resolver (``resolver.py``: did:key + did:web + did:plc),
``DidDocCache`` (``cache.py`` — in-memory seam Phase 13 swaps), real ed25519
signer (``signer.py``), and verifier (``verifier.py``) with signing-time key
capture.

Dep-isolation: ``shards/`` stays crypto/RDF/atproto-free (the
``tests/shards/test_dep_leak_guard.py`` boundary). Crypto + atproto + dag_cbor +
httpx imports live here. ``identity/`` imports ``revision/`` for the JCS canonical
content hash (Plan 01) but ``revision/`` does NOT import ``identity/`` — the
dependency direction is ``identity/ -> revision/ -> shards/``.

Public exports below are the surface Plan 03 (binding + CLI + preview) consumes;
tests under ``tests/identity/`` may import directly from submodules where
convenient. New submodules added during this plan are wired in here as they land.
"""
from __future__ import annotations

from folio_insights.identity.cache import (
    DidDocCache,
    DidDocSnapshot,
    InMemoryDidDocCache,
)
from folio_insights.identity.keys import (
    did_key_from_public,
    generate_keypair,
    load_signing_key,
    public_key_from_did_key,
)
from folio_insights.identity.resolver import (
    UnknownDidMethodError,
    UnresolvableDidError,
    resolve_did,
)

__all__ = [
    # keys.py
    "generate_keypair",
    "load_signing_key",
    "did_key_from_public",
    "public_key_from_did_key",
    # cache.py
    "DidDocCache",
    "DidDocSnapshot",
    "InMemoryDidDocCache",
    # resolver.py
    "resolve_did",
    "UnknownDidMethodError",
    "UnresolvableDidError",
]
