"""Fixtures + Hypothesis strategies for tests/identity (Phase 6).

Shares the proven `_sample_shard` builder from tests/shards/conftest.py so
hash-stability tests exercise REAL validated `ShardEnvelope` instances rather
than synthesized dicts. The Hypothesis strategies build shard payloads with
randomized text content (Unicode noise) + randomized field ordering, both of
which are the F4 surface JCS must canonicalize away.
"""
from __future__ import annotations

import random
import string
from datetime import UTC, datetime

import pytest
from hypothesis import strategies as st

from folio_insights.shards import SimpleAssertionShard

# Reuse the proven builder — tests/ is on the import path via pytest's rootdir.
from tests.shards.conftest import _sample_shard

# ── Unicode noise corpus (the F4 character set the planner picked) ──
#
# Per 06-RESEARCH §2: NFC normalization closes the smart-quotes / em-dash /
# NBSP / combining-accent surface. We include a representative sample of each
# in the property test so the order-independence test ALSO exercises Unicode
# invariance (an NFD-form value must hash identically to its NFC equivalent).

# Latin small-letter-a with combining-acute (NFD) — NFC-normalizes to U+00E1.
_NFD_ACCENTED = "á"  # → "á" under NFC
_NFC_ACCENTED = "á"   # already NFC

UNICODE_NOISE_SAMPLES: list[tuple[str, str]] = [
    # (NFD form, NFC form) — both must hash identically after normalization.
    (_NFD_ACCENTED, _NFC_ACCENTED),
    ("résumé", "résumé"),                   # résumé
    ("naive café", "naive café"),                       # identity (already NFC)
    ("smart “quote”", "smart “quote”"),       # smart quotes (no NFD/NFC diff)
    ("non‑breaking", "non‑breaking"),                   # non-breaking hyphen
    ("em—dash", "em—dash"),                             # em-dash
    ("space NBSP", "space NBSP"),                       # NBSP
]


@pytest.fixture
def make_shard():
    """Return a builder that constructs a valid SimpleAssertionShard with overrides."""
    def _build(**overrides):
        return _sample_shard(SimpleAssertionShard, **overrides)
    return _build


# ── Hypothesis strategy: small valid envelope payloads ──
#
# Bound the example budget so the 1000-run property test stays under the 30s
# pytest timeout. The strategy generates payloads we feed into the SAME
# `_sample_shard` builder via overrides — guaranteed-valid instances without
# Pydantic constraint failures eating our budget.

_RANDOM_TEXT = st.text(
    alphabet=st.characters(
        whitelist_categories=("Lu", "Ll", "Nd", "Pc", "Zs", "Pd"),
        max_codepoint=0x024F,  # Latin Extended-B; avoid surrogates / control
    ),
    min_size=1,
    max_size=24,
)


@st.composite
def shard_payloads(draw) -> dict:
    """Hypothesis-driven payload (overrides for _sample_shard).

    Randomizes only the CONTENT fields that survive the _HASH_EXCLUDED set —
    transaction_time, valid_time_*, content_edits, signatures are excluded
    from the hash by design so randomizing them is wasted budget. Datetimes
    use microsecond precision and a randomized minute/second/µs so the F4
    datetime pin is exercised.
    """
    sense = draw(_RANDOM_TEXT)
    reference = "urn:folio:concept/" + draw(_RANDOM_TEXT)
    subject = draw(_RANDOM_TEXT)
    predicate = "urn:folio:predicate/" + draw(_RANDOM_TEXT)
    obj = draw(_RANDOM_TEXT)

    # Randomize extracted_at across a wide span with µs precision so the F4
    # datetime canonicalization is genuinely exercised.
    minute = draw(st.integers(min_value=0, max_value=59))
    second = draw(st.integers(min_value=0, max_value=59))
    micro = draw(st.integers(min_value=0, max_value=999_999))
    extracted_at = datetime(2026, 4, 24, 12, minute, second, micro, tzinfo=UTC)

    confidence = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))

    # Build a fresh Triple via override dict — `_sample_shard` rebuilds it.
    from folio_insights.shards import Triple
    triple = Triple(subject=subject, predicate=predicate, object=obj)

    return {
        "sense": sense,
        "reference": reference,
        "triple": triple,
        "extracted_at": extracted_at,
        "confidence": confidence,
    }


# ── Plan 06-02 fixtures: identity/ unit-test seams ────────────────────────────


@pytest.fixture
def doc_cache():
    """A fresh ``InMemoryDidDocCache`` per test (D-11 seam; mirrors ``store``
    fixture in tests/revision/conftest.py).
    """
    from folio_insights.identity import InMemoryDidDocCache

    return InMemoryDidDocCache()


@pytest.fixture
def ed25519_keypair_a():
    """An ed25519 keypair (``cryptography`` ``Ed25519PrivateKey``) for the
    "signing-time" side of rotation-survival scenarios. Key A is the key in
    use when the historical signature was produced.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    return Ed25519PrivateKey.generate()


@pytest.fixture
def ed25519_keypair_b():
    """A second ed25519 keypair for the "post-rotation current" side of
    rotation-survival scenarios. Key B replaces Key A in the current did.json
    (did:web rotation) — but the snapshot from signing time keeps Key A, so
    historical verify still passes.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    return Ed25519PrivateKey.generate()


@pytest.fixture
def did_web_doc_for():
    """Builder: return a callable that constructs a did:web did.json carrying
    a given ed25519 ``cryptography`` private key's public half in
    ``publicKeyMultibase`` form.
    """
    from cryptography.hazmat.primitives import serialization
    from folio_insights.identity.keys import did_key_from_public

    def _build(did: str, sk) -> dict:
        raw = sk.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        mb = did_key_from_public(raw).removeprefix("did:key:")
        return {
            "id": did,
            "verificationMethod": [
                {
                    "id": f"{did}#key-1",
                    "type": "Multikey",
                    "controller": did,
                    "publicKeyMultibase": mb,
                }
            ],
        }

    return _build


@pytest.fixture
def did_plc_doc_for():
    """Builder for a synthetic did:plc DID document (recorded fixture — no
    live atproto network).
    """
    from cryptography.hazmat.primitives import serialization
    from folio_insights.identity.keys import did_key_from_public

    def _build(did: str, sk) -> dict:
        raw = sk.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        mb = did_key_from_public(raw).removeprefix("did:key:")
        return {
            "id": did,
            "verificationMethod": [
                {
                    "id": f"{did}#atproto",
                    "type": "Multikey",
                    "controller": did,
                    "publicKeyMultibase": mb,
                }
            ],
        }

    return _build


def shuffle_dict_keys(d: dict, seed: int) -> dict:
    """Return a new dict whose keys are a randomized permutation of d's.

    Python 3.7+ dict ordering preserves insertion order; constructing via
    randomized iteration order is the easiest way to feed JCS a payload
    whose pre-canonicalization key order is *different* but whose canonical
    form must be identical. Recursively shuffles nested dicts/lists too.
    """
    rng = random.Random(seed)
    if isinstance(d, dict):
        items = list(d.items())
        rng.shuffle(items)
        return {k: shuffle_dict_keys(v, rng.randint(0, 2**31 - 1)) for k, v in items}
    if isinstance(d, list):
        # Lists preserve order semantically (RFC 8785) — DON'T shuffle list
        # elements; shuffle nested dicts inside the list, in place by index.
        return [shuffle_dict_keys(item, rng.randint(0, 2**31 - 1)) for item in d]
    return d
