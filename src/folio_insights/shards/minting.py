"""Phase 2 provenance-hash IRI minting (PRD §6.3; CONTEXT D-01/D-02).

Recipe (locked by D-02, width amended by D-01; CRLF fold by D-08):
  input = NFC(rfc3986_normalize(source_uri)) + "\\n" + _normalize_span(source_span)
  hash  = sha256(input.encode("utf-8")).hexdigest()   # 64 hex chars
  iri   = f"urn:folio:shard/{hash[:32]}"              # 32-hex body

``_normalize_span`` folds internal CR/CRLF to LF before NFC + trim (D-08), so
text differing only in line endings hashes identically (SHARD-07).

Note: PRD §6.3 L547-551 originally specified an ``https://`` (aleainstitute
domain) prefix for the shard IRI body. CONTEXT D-02 supersedes that with
``urn:folio:shard/`` — the URN scheme is location-independent, and the
PRD-draft http form will be reconciled in a PRD revision.

Determinism is a hard property (enforced via hypothesis property test in
Plan 02-03): same (uri, span) → same (iri, hash) across runs, platforms,
and line-ending styles. Phase 4 adds collision detection + nightly re-hash
verification; Phase 2 only ships the pure minting function.
"""
from __future__ import annotations

import hashlib
import unicodedata
from urllib.parse import quote, urlsplit, urlunsplit

_IRI_PREFIX = "urn:folio:shard/"
_IRI_HEX_LEN = 32  # first 32 of sha256's 64 hex chars (D-01 — 128-bit body)


def _normalize_uri(uri: str) -> str:
    """RFC 3986 normalize: lowercase scheme + host, percent-encode path,
    strip trailing slash (except root). Query + fragment preserved (D-02)."""
    parts = urlsplit(uri)
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    path = quote(parts.path, safe="/%:@")
    if path.endswith("/") and path != "/":
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, parts.query, parts.fragment))


def _normalize_span(span: str) -> str:
    """Fold internal CR/CRLF to LF, NFC normalize, then strip outer whitespace.

    D-08: internal "\\r\\n" and lone "\\r" become "\\n" BEFORE the NFC call so
    text differing only in line endings hashes identically (SHARD-07). The LF
    fold must precede NFC so combining-char sequences spanning a fold normalize
    consistently. The LF-only inter-field separator lives in ``mint_shard_iri``;
    this helper only normalizes the span content itself.
    """
    lf = span.replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFC", lf).strip()


def mint_shard_iri(source_uri: str, source_span: str) -> tuple[str, str]:
    """Deterministic provenance-hash → shard IRI (D-01/D-02).

    Returns:
        (iri, provenance_hash) where:
          provenance_hash = 64-char lowercase hex SHA-256 (full hash UNCHANGED —
                            the registry compares full hashes for collisions, D-02)
          iri             = f"urn:folio:shard/{provenance_hash[:32]}"  (D-01 128-bit body)

    The hash input is:
        NFC(rfc3986(source_uri)) + "\\n" + _normalize_span(source_span)
    where ``_normalize_span`` folds internal CR/CRLF to LF before NFC + trim (D-08).
    """
    uri_n = unicodedata.normalize("NFC", _normalize_uri(source_uri))
    span_n = _normalize_span(source_span)
    payload = (uri_n + "\n" + span_n).encode("utf-8")
    hash_hex = hashlib.sha256(payload).hexdigest()
    iri = f"{_IRI_PREFIX}{hash_hex[:_IRI_HEX_LEN]}"
    return iri, hash_hex


__all__ = ["mint_shard_iri"]
