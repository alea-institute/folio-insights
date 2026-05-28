"""Phase 6 DID substrate tests (§6.5, REQ DID-01..DID-09).

Plan 06-01 ships:
  * test_canonical_jcs_properties.py — 1000-shuffled-order property test
    (exit criterion EC2 — JCS order-independence over the canonical hash)
  * test_jcs_golden.py — ~50-input cross-implementation golden test vs the
    cyberphone/json-canonicalization reference (Pitfall F4 closure).

Plans 06-02 / 06-03 fill: sign/verify did:key + did:web, did:plc resolve/
verify, signing-time key capture, OAuth→DID binding, DID-07 preview.
"""
