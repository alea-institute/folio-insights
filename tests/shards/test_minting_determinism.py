"""Minting determinism — hypothesis 1000-example property test + directed vectors.

Covers CONTEXT D-02 (provenance-hash recipe: NFC + LF + trim + RFC 3986), the
Phase 04 D-01 hex32 width amendment, and the D-08 internal-CRLF fold.

Phase 2 is the first hypothesis adopter in the repo (per 02-PATTERNS.md). The
``@settings(max_examples=1000, deadline=None)`` matches the D-02 "1000 random
runs" language; ``deadline=None`` avoids per-example 200 ms deadline flakes
on slow CI under complex unicode inputs.
"""
from __future__ import annotations

import unicodedata

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from folio_insights.shards import mint_shard_iri

pytestmark = pytest.mark.shards


# ── Property test: 1000 random (uri, span) pairs → deterministic output ──


@settings(max_examples=1000, deadline=None)
@given(
    scheme=st.sampled_from(["http", "https", "urn"]),
    host=st.text(
        alphabet="abcdefghijklmnopqrstuvwxyz0123456789-.",
        min_size=3,
        max_size=20,
    ).filter(lambda s: not s.startswith(".") and not s.endswith(".")),
    path=st.text(min_size=0, max_size=50),
    span=st.text(min_size=0, max_size=200),
)
def test_mint_is_deterministic(scheme: str, host: str, path: str, span: str) -> None:
    """D-02: same (uri, span) → same (iri, hash) across repeated calls (1000 runs)."""
    uri = f"{scheme}://{host}/{path}" if scheme != "urn" else f"urn:{host}:{path}"
    iri_a, hash_a = mint_shard_iri(uri, span)
    iri_b, hash_b = mint_shard_iri(uri, span)
    assert iri_a == iri_b
    assert hash_a == hash_b
    assert iri_a.startswith("urn:folio:shard/")
    assert len(iri_a) == len("urn:folio:shard/") + 32
    assert len(hash_a) == 64
    assert all(c in "0123456789abcdef" for c in hash_a)


# ── Directed vectors: NFC / NFD / RFC 3986 / CRLF ──


def test_nfc_equals_nfd_normalization() -> None:
    """D-02: NFC 'café' and NFD 'café' (e + combining acute) yield same IRI."""
    nfc_span = unicodedata.normalize("NFC", "café")
    nfd_span = unicodedata.normalize("NFD", "café")
    assert nfc_span != nfd_span, "Precondition: NFC and NFD byte-differ"
    iri_a, hash_a = mint_shard_iri("urn:x:1", nfc_span)
    iri_b, hash_b = mint_shard_iri("urn:x:1", nfd_span)
    assert (iri_a, hash_a) == (iri_b, hash_b)


def test_crlf_trimmed_from_span() -> None:
    """D-02: trailing CRLF in span is stripped via str.strip() before hashing."""
    iri_a, _ = mint_shard_iri("urn:x:1", "body text\r\n")
    iri_b, _ = mint_shard_iri("urn:x:1", "body text")
    assert iri_a == iri_b


def test_internal_crlf_normalized_to_lf() -> None:
    """D-08: internal CRLF / lone CR fold to LF -> same IRI as the LF form.

    Unlike test_crlf_trimmed_from_span (trailing CRLF caught by .strip()),
    this locks the *internal* line-ending fold so the same text with
    CRLF / CR / LF line endings hashes identically (SHARD-07).
    """
    iri_crlf, _ = mint_shard_iri("urn:x:1", "line one\r\nline two")
    iri_cr, _ = mint_shard_iri("urn:x:1", "line one\rline two")
    iri_lf, _ = mint_shard_iri("urn:x:1", "line one\nline two")
    assert iri_crlf == iri_lf == iri_cr


def test_rfc3986_case_fold_and_trailing_slash() -> None:
    """D-02: RFC 3986 — lowercase scheme+host, strip trailing slash."""
    iri_a, _ = mint_shard_iri("HTTPS://Example.COM/doc/", "span")
    iri_b, _ = mint_shard_iri("https://example.com/doc", "span")
    assert iri_a == iri_b


def test_rfc3986_fragment_preserved() -> None:
    """D-02: fragment component survives normalization (part of ID basis)."""
    iri_with_frag, _ = mint_shard_iri("https://example.com/doc#sec1", "span")
    iri_no_frag, _ = mint_shard_iri("https://example.com/doc", "span")
    # Different input → different IRI (fragment is part of the ID basis).
    assert iri_with_frag != iri_no_frag


def test_iri_prefix_and_length() -> None:
    """D-01/D-02: IRI prefix is urn:folio:shard/ and body is 32 hex chars."""
    iri, h = mint_shard_iri("urn:x:1", "hello")
    assert iri.startswith("urn:folio:shard/")
    assert len(iri) == len("urn:folio:shard/") + 32
    assert iri.removeprefix("urn:folio:shard/") == h[:32]
    assert len(h) == 64


def test_different_span_produces_different_iri() -> None:
    """D-02: distinct spans under same URI yield distinct IRIs (sanity)."""
    iri_a, _ = mint_shard_iri("urn:x:1", "alpha")
    iri_b, _ = mint_shard_iri("urn:x:1", "beta")
    assert iri_a != iri_b
