"""JCS order-independence property tests — Plan 06-01 exit criterion EC2.

Exercises the canonical_content_hash + the underlying _jcs_canonical_bytes
core (DID-03 / D-12) over 1000+ random shards. The CONTRACT we prove:

  1. **Field/key-order independence** — two shards with identical CONTENT
     but different dict-insertion order hash IDENTICALLY (RFC-8785 key sort).
  2. **Unicode invariance** — an NFD-form text field hashes the SAME as its
     NFC equivalent (the F4 normalization recipe — jcs alone does NOT do this;
     the recipe is what closes the gap).
  3. **Datetime canonicalization stability** — a microsecond-precision
     `extracted_at` hashes identically before/after model_validate(model_dump)
     round-trip (datetime "Z" suffix + 6-digit µs lock).

This is the IN-PHASE gate (EC2) per CONTEXT D-12. The cyberphone cross-impl
golden test (test_jcs_golden.py) is the orthogonal F4 closure.

Budget: Hypothesis @given with max_examples=1000, deadline disabled. Random
seed control is via Hypothesis's own database; runs complete in <5s.
"""
from __future__ import annotations

import unicodedata

import pytest
from hypothesis import HealthCheck, given, settings

from folio_insights.revision.content_edit import (
    _jcs_canonical_bytes,
    canonical_content_hash,
)
from folio_insights.shards import SimpleAssertionShard

from tests.identity.conftest import (
    UNICODE_NOISE_SAMPLES,
    shard_payloads,
    shuffle_dict_keys,
)
from tests.shards.conftest import _sample_shard

pytestmark = pytest.mark.identity


# ── EC2: field/key-order independence across 1000 random shards ──────────


@settings(
    max_examples=1000,
    deadline=None,  # JCS is fast, but CI variance + Hypothesis shrinking
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(payload=shard_payloads())
def test_jcs_order_independence_across_random_shards(payload: dict) -> None:
    """For 1000 random shards, the canonical hash is identical across
    randomized dict-insertion-order permutations of the model_dump payload.

    This is THE Phase-6 EC2 gate. We hash via _jcs_canonical_bytes (which is
    what canonical_content_hash uses) over two payloads:
      A. shard.model_dump(mode="json") — natural Pydantic key order.
      B. shuffle_dict_keys(A, seed=...) — a randomized key permutation of A.

    JCS sorts keys per RFC-8785; the resulting bytes — and therefore the
    SHA-256 — MUST be equal. A failing example would mean either jcs is not
    sorting deterministically, or our pre-normalization is non-deterministic
    on key order, either of which is a BLOCKING F4 violation.
    """
    shard = _sample_shard(SimpleAssertionShard, **payload)
    natural = shard.model_dump(mode="json")
    # Three differently-seeded shuffles for breadth on key-order space.
    for seed in (0xC0FFEE, 0xDECAFBAD, 0xBADC0DE):
        shuffled = shuffle_dict_keys(natural, seed)
        assert _jcs_canonical_bytes(natural) == _jcs_canonical_bytes(shuffled), (
            f"JCS canonical bytes diverged under dict-key permutation "
            f"(seed={seed:#x}); F4 key-order invariance violated."
        )


# ── Unicode invariance (NFC pre-normalization) ───────────────────────────


@pytest.mark.parametrize("nfd_text,nfc_text", UNICODE_NOISE_SAMPLES)
def test_jcs_unicode_nfc_invariance(nfd_text: str, nfc_text: str) -> None:
    """An NFD-form string hashes identically to its NFC equivalent.

    Pitfall F4 #4 closure: text fields like `sense` / `reference` /
    `source_span` carry user input that may arrive in NFD form (decomposed
    accent + base letter) or NFC (precomposed). The signer and verifier MUST
    agree on the hash regardless of input form, and the pre-normalization
    recipe is what makes that true. jcs alone does NOT do this.
    """
    # Sanity: the test data is what we think it is.
    assert unicodedata.normalize("NFC", nfd_text) == unicodedata.normalize("NFC", nfc_text), (
        "Test data invariant: both samples must normalize to the same NFC string"
    )
    nfd_shard = _sample_shard(SimpleAssertionShard, sense=nfd_text)
    nfc_shard = _sample_shard(SimpleAssertionShard, sense=nfc_text)
    assert canonical_content_hash(nfd_shard) == canonical_content_hash(nfc_shard), (
        f"NFD form {nfd_text!r} and NFC form {nfc_text!r} produced different "
        "canonical hashes — NFC pre-normalization recipe is broken (F4)."
    )


# ── Datetime canonicalization stability across model_validate round-trip ──


def test_extracted_at_microsecond_hash_stable_across_round_trip() -> None:
    """Acceptance criterion (Plan §3): a microsecond-precision extracted_at
    hashes identically before and after model_validate(model_dump(mode='json')).

    This is the remaining F4 surface — without the datetime pin, Pydantic
    minor-version drift in datetime ISO output (`+00:00` vs `Z`, trailing
    zeros in µs) could cause signer == verifier to disagree. The
    _DATETIME_FORMAT lock + the _normalize_for_jcs walk over ISO strings is
    what closes this.
    """
    from datetime import UTC, datetime
    extracted = datetime(2026, 4, 24, 12, 34, 56, 789123, tzinfo=UTC)
    shard = _sample_shard(SimpleAssertionShard, extracted_at=extracted)
    h_before = canonical_content_hash(shard)
    rehydrated = SimpleAssertionShard.model_validate(shard.model_dump(mode="json"))
    h_after = canonical_content_hash(rehydrated)
    assert h_before == h_after, (
        f"Hash drifted across model_validate(model_dump) round-trip: "
        f"{h_before} vs {h_after} — F4 datetime seam is open."
    )


def test_exclusion_set_does_not_affect_hash() -> None:
    """Mutating only excluded fields (transaction_time, valid_time_*,
    content_edits, signatures) does NOT change canonical_content_hash.

    Verifies the D-05 exclusion set survived the JCS swap. CR-02 was the
    bug this guards against (transaction_time leaking into the hash); the
    JCS swap must preserve the same exclusion behavior.
    """
    from datetime import UTC, datetime, timedelta

    shard = _sample_shard(SimpleAssertionShard)
    h_baseline = canonical_content_hash(shard)

    # Mutate only EXCLUDED fields.
    shard.transaction_time = datetime.now(UTC) + timedelta(days=365)
    shard.valid_time_start = datetime(2020, 1, 1, tzinfo=UTC)
    shard.valid_time_end = datetime(2030, 12, 31, tzinfo=UTC)
    # content_edits / signatures append-only mutation — equivalent test by
    # appending a placeholder signature; we already trust the exclusion of
    # transaction_time alone here, but adding a signature exercises the list
    # exclusion too.
    from folio_insights.shards import AttestedSignature
    shard.signatures.append(AttestedSignature(did="did:key:zZ"))

    h_after_excluded_mutation = canonical_content_hash(shard)
    assert h_baseline == h_after_excluded_mutation, (
        "canonical_content_hash changed after mutating only EXCLUDED fields; "
        "_HASH_EXCLUDED_FIELDS is not being honored under the JCS swap (D-05)."
    )


def test_changing_content_does_change_hash() -> None:
    """Sanity dual to the exclusion test: mutating an INCLUDED content
    field (e.g. `sense`) DOES change the canonical hash.

    Without this, the exclusion test alone could mask a bug where
    canonical_content_hash returns a constant. This is the "hash actually
    binds content" cross-check.
    """
    shard = _sample_shard(SimpleAssertionShard, sense="original")
    h_original = canonical_content_hash(shard)
    shard.sense = "revised"
    h_revised = canonical_content_hash(shard)
    assert h_original != h_revised, (
        "canonical_content_hash unchanged after mutating `sense` — hash does "
        "not bind content; JCS pipeline is broken or sense is wrongly excluded."
    )
