"""Phase 2 provenance-hash IRI minting (PRD §6.3; CONTEXT D-01/D-02).

Recipe (locked by D-02, width amended by D-01; CRLF fold by D-08; NFC-order
fix by CR-01):
  input = rfc3986_nfc(source_uri) + "\\n" + _normalize_span(source_span)
  hash  = sha256(input.encode("utf-8")).hexdigest()   # 64 hex chars
  iri   = f"urn:folio:shard/{hash[:32]}"              # 32-hex body

``rfc3986_nfc`` applies NFC to each URI component BEFORE percent-encoding — the
literal D-02 recipe wrote ``NFC(rfc3986_normalize(...))``, but NFC after
``quote()`` is a no-op on the ASCII percent-encoding, so NFD vs NFC URIs minted
different IRIs (CR-01). The corrected ordering delivers D-02's stated intent:
the same logical source mints one IRI regardless of input normalization form.

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
import json
import re
import unicodedata
from urllib.parse import quote, urlsplit, urlunsplit

_IRI_PREFIX = "urn:folio:shard/"
_IRI_HEX_LEN = 32  # first 32 of sha256's 64 hex chars (D-01 — 128-bit body)
LEGACY_IDENTITY_RECIPE = "legacy-v1"
ATOMIC_IDENTITY_RECIPE = "atomic-v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _normalize_uri(uri: str) -> str:
    """RFC 3986 normalize: lowercase scheme + host, NFC-then-percent-encode path,
    strip trailing slash (except root). Query + fragment preserved (D-02).

    NFC runs on each component BEFORE percent-encoding (CR-01). ``quote()`` turns
    non-ASCII bytes into ``%XX`` ASCII, so a later NFC pass over the encoded form
    is a no-op — an NFD path (``cafe`` + combining acute) and its NFC equivalent
    (``café``) would otherwise mint different IRIs for the same logical source,
    breaking the D-02 determinism guarantee and storing one source as two
    content-addressed rows. Normalizing each component first makes the encoded
    output identical regardless of the caller's input normalization form.
    """
    parts = urlsplit(uri)
    scheme = parts.scheme.lower()
    netloc = unicodedata.normalize("NFC", parts.netloc).lower()
    path = quote(unicodedata.normalize("NFC", parts.path), safe="/%:@")
    if path.endswith("/") and path != "/":
        path = path.rstrip("/")
    query = unicodedata.normalize("NFC", parts.query)
    fragment = unicodedata.normalize("NFC", parts.fragment)
    return urlunsplit((scheme, netloc, path, query, fragment))


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
        rfc3986_nfc(source_uri) + "\\n" + _normalize_span(source_span)
    where ``_normalize_uri`` applies NFC to each URI component BEFORE
    percent-encoding (CR-01 — NFC after ``quote()`` is a no-op on ASCII), and
    ``_normalize_span`` folds internal CR/CRLF to LF before NFC + trim (D-08).
    """
    uri_n = _normalize_uri(source_uri)
    span_n = _normalize_span(source_span)
    payload = (uri_n + "\n" + span_n).encode("utf-8")
    hash_hex = hashlib.sha256(payload).hexdigest()
    iri = f"{_IRI_PREFIX}{hash_hex[:_IRI_HEX_LEN]}"
    return iri, hash_hex


def atomic_proposition_key(
    text: str, start: int, end: int, source_snapshot_digest: str,
) -> str:
    """Freeze NFC extraction text, exact character offsets and snapshot SHA-256.

    Text is neither trimmed nor line-folded. JSON array framing makes field
    boundaries unambiguous. Tags, links and later reviewed wording are absent.
    """
    if not text.strip():
        raise ValueError("atomic text must be nonempty")
    if type(start) is not int or type(end) is not int or start < 0 or end <= start:
        raise ValueError("atomic offsets must be integers with 0 <= start < end")
    if not _SHA256_RE.fullmatch(source_snapshot_digest):
        raise ValueError("source_snapshot_digest must be a lowercase SHA-256 hex digest")
    payload = json.dumps(
        [ATOMIC_IDENTITY_RECIPE, unicodedata.normalize("NFC", text), start, end,
         source_snapshot_digest],
        ensure_ascii=False, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def mint_atomic_shard_iri(
    source_uri: str, source_span: str, proposition_key: str,
) -> tuple[str, str]:
    """Atomic-v1 identity: normalized URI, *verbatim* span and frozen key.

    Separate domain framing leaves the legacy recipe untouched. Revisions use
    the stored key; fresh extraction derives a new key with atomic_proposition_key.
    """
    if not _SHA256_RE.fullmatch(proposition_key):
        raise ValueError("proposition_key must be a lowercase SHA-256 hex digest")
    payload = json.dumps(
        [ATOMIC_IDENTITY_RECIPE, _normalize_uri(source_uri), source_span, proposition_key],
        ensure_ascii=False, separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{_IRI_PREFIX}{digest[:_IRI_HEX_LEN]}", digest


__all__ = [
    "ATOMIC_IDENTITY_RECIPE", "LEGACY_IDENTITY_RECIPE", "atomic_proposition_key",
    "mint_atomic_shard_iri", "mint_shard_iri",
]
