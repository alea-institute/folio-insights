"""Phase 5 content-versioning write + read path (PRD §6.4; CONTEXT D-01, D-05, D-06, D-09).

The async, store-backed ``edit_shard_content`` write path (the locked PRD §6.4
call-site contract, D-01), the dotted-path ``get_field`` / ``set_field`` helpers,
the central ``IMMUTABLE_FIELD_PATHS`` gate (D-06), the real deterministic
``canonical_content_hash`` (D-05), the ``sign_attestation`` unsigned stub (D-05),
the post-edit ``validate_shard`` re-validation hook (V5 / RESEARCH Pitfall 2),
and ``get_shard_at`` reverse-replay historical reconstruction (D-09).

Stub / seam boundaries (so Phase 6 / 13 fill stubs without churning callers):

* ``signing_key`` is accepted by ``edit_shard_content`` and UNUSED in Phase 5 —
  Phase 6 (DID substrate) wires real ed25519 signing through it.
* ``sign_attestation`` returns an empty/unsigned ``AttestedSignature``
  (``signature=""``); Phase 6 fills real crypto. Tests assert it is clearly
  unsigned so an empty signature can never read as "verified".
* ``canonical_content_hash`` is REAL now (deterministic sorted-key JSON SHA-256,
  mirroring ``shards/minting.py``); Phase 6 swaps RFC 8785 JCS into the single
  ``json.dumps`` line without changing the call site.
* The ``ShardStore`` (``store.py``) is the in-memory D-02 seam Phase 13 swaps for
  Oxigraph behind the same async interface.

This module imports ``rdflib``/``pyshacl`` NOWHERE — it is pure Pydantic + stdlib.
The pyshacl forward-only shape is the sibling Plan 03 (``revision/shape_validation``);
``validate_content_edit_shape`` is intentionally NOT re-exported from this package's
``__init__`` — Plan 03 owns its own module and its tests import it directly.
"""
from __future__ import annotations

import hashlib
import unicodedata
from datetime import UTC, datetime
from typing import Any

import jcs

from folio_insights.revision.store import ShardStore
from folio_insights.shards import AttestedSignature, ContentEdit, ShardEnvelope

# ── IMMUTABLE_FIELD_PATHS (D-06) — the single source of truth ────────────────
# 6 Pydantic-frozen identity fields + the 2 identity-defining triple parts +
# the 2 append-only lists. ``triple.object`` is deliberately ABSENT (re-parenting
# is editable, D-04). The 2 triple parts are NOT protected by Pydantic frozen
# (the ``Triple`` submodel is mutable, not frozen) — this gate is their ONLY
# protection. ``content_edits`` / ``signatures`` are append-only-as-a-whole:
# appending is fine, replacing/reordering/removing the list is forbidden.
IMMUTABLE_FIELD_PATHS: frozenset[str] = frozenset(
    {
        # 6 Pydantic-frozen identity-and-origin fields (envelope.py L101-106)
        "shard_iri",
        "provenance_hash",
        "source_uri",
        "source_span",
        "extracted_at",
        "first_extractor_did",
        # identity-defining triple parts (Triple submodel is mutable — gate-only)
        "triple.subject",
        "triple.predicate",
        # append-only lists (append OK; reorder/remove/replace forbidden)
        "content_edits",
        "signatures",
    }
)


# ── dotted-path helpers (RESEARCH L171-184) ──────────────────────────────────


def _validate_field_path(shard: ShardEnvelope, path: str) -> None:
    """Bound a dotted ``field_path`` to DECLARED Pydantic model fields (WR-02).

    Both ``get_field`` and ``set_field`` previously used bare ``getattr`` /
    ``setattr`` traversal, so ANY path resolvable via Python attribute lookup was
    accepted — including dunders and descriptors that are not content
    (``"__class__"``, ``"model_fields"``, ``"triple.__class__.__bases__"``).
    ``get_field`` would then leak that internal state into the ``old_value`` slot
    of a ``ContentEdit`` (the audit record), and ``IMMUTABLE_FIELD_PATHS`` — a
    deny-list — could not catch it.

    This validator restricts the universe of accessible paths to schema-declared
    fields: at EACH segment it verifies the segment is a key in the current
    model's ``model_fields`` BEFORE any attribute access. It rejects empty paths,
    dunders, descriptors, and any non-declared attribute with a clear error, and
    raises BEFORE touching the object (no state leak, no audit record). It is the
    front-line schema whitelist; ``IMMUTABLE_FIELD_PATHS`` remains the orthogonal
    edit-permission deny-list layered on top.
    """
    if not path:
        raise ValueError("Empty field_path is not a declared model field.")
    obj: Any = shard
    for part in path.split("."):
        model_fields = getattr(type(obj), "model_fields", None)
        if model_fields is None or part not in model_fields:
            raise ValueError(
                f"Field path segment {part!r} (in {path!r}) is not a declared "
                f"model field on {type(obj).__name__}. Only schema-declared "
                "paths are permitted (no dunders, descriptors, or arbitrary "
                "attributes)."
            )
        # Safe to descend now that `part` is confirmed a declared field. The
        # final segment is validated but not necessarily descended-into here.
        obj = getattr(obj, part)


def get_field(shard: ShardEnvelope, path: str) -> Any:
    """Read a (possibly nested) field by dotted path: ``"triple.object"`` walks
    ``shard.triple.object``; ``"sense"`` reads the top-level field.

    ``path`` is bounded to DECLARED model fields (WR-02) — a non-declared or
    dunder segment raises ``ValueError`` BEFORE any attribute access, so internal
    state can never leak through this reader into an audit record.
    """
    _validate_field_path(shard, path)
    obj: Any = shard
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


def set_field(shard: ShardEnvelope, path: str, value: Any) -> None:
    """Assign a (possibly nested) field by dotted path.

    ``path`` is bounded to DECLARED model fields (WR-02) — a non-declared or
    dunder segment raises ``ValueError`` BEFORE any attribute access.

    NOTE: ``validate_assignment`` is OFF on ``ShardEnvelope`` (verified — RESEARCH
    Pitfall 2), so this setter accepts wrong types SILENTLY. For reverse-replay
    that is safe (restoring a previously-valid value); for ``edit_shard_content``
    the incoming ``new_value`` is unvalidated, so the caller MUST re-validate via
    ``validate_shard`` after applying it. The 6 frozen identity fields still raise
    on assignment; ``triple.subject``/``.predicate`` do NOT (the gate guards them).
    """
    _validate_field_path(shard, path)
    parts = path.split(".")
    obj: Any = shard
    for part in parts[:-1]:
        obj = getattr(obj, part)  # walk to the parent submodel
    setattr(obj, parts[-1], value)  # assign the leaf


# ── canonical_content_hash (D-05) — REAL deterministic JSON SHA-256 ──────────

# Fields excluded from the *content* hash (CR-02 / D-05). A content hash must
# bind the shard's CONTENT (triple, sense, reference, provenance fields, layer,
# etc.) so it is reproducible from the stored record — NOT volatile storage
# metadata or the mutable audit/signature logs:
#
#   * ``transaction_time`` — re-generated on every construction
#     (``default_factory=lambda: datetime.now(UTC)``), so identical content
#     would hash differently across instances / process restarts / nodes. This
#     is THE bug CR-02 fixed: the hash was non-deterministic across instances.
#   * ``valid_time_start`` / ``valid_time_end`` — bitemporal STORAGE metadata
#     (Phase 13 ``--as-of`` window markers), not the content itself.
#   * ``content_edits`` — the append-only AUDIT LOG, not content. Including it
#     would make the hash change on every edit, defeating its purpose as a
#     stable, reproducible pre-edit content binding (the value the signature's
#     ``over_content_hash`` slot records).
#   * ``signatures`` — attestations OVER the content, not the content itself
#     (including them would be circular once Phase 6 signs the content hash).
#
# Phase 6 (D-12 / DID-03) swapped RFC-8785 JCS into the canonical_content_hash
# line. The exclusion set is unchanged — content remains the bound surface.
_HASH_EXCLUDED_FIELDS: frozenset[str] = frozenset(
    {
        "transaction_time",
        "valid_time_start",
        "valid_time_end",
        "content_edits",
        "signatures",
    }
)


# ── Phase 6 JCS canonicalization helper (D-12 / DID-03 / Pitfall F4) ────────
#
# The F4 pre-normalization recipe (06-RESEARCH §2) is the hard part — `jcs`
# fixes key ordering + minimal number encoding per RFC 8785, but it does NOT
# NFC-normalize strings or pin datetime/None formats. Both signer and verifier
# go through this helper, so the same bytes flow into the same SHA-256.
#
# Recipe (lock these decisions; the property + golden tests prove them):
#
#   1. NFC-normalize every string KEY and VALUE recursively (Pitfall F4 #4 —
#      NFD vs NFC accents, NBSP, smart quotes hash differently). jcs / RFC 8785
#      does NOT do this; it MUST happen before jcs.canonicalize.
#   2. Pin datetime → RFC-3339 UTC, fixed "Z" suffix, microsecond precision.
#      Pydantic ``mode="json"`` emits one of `...+00:00` or `...Z`; we coerce
#      to `...Z` and a fixed 6-digit microsecond representation so signer ==
#      verifier across Pydantic minor versions and across model_validate/
#      model_dump round-trips. Walked over the payload AFTER model_dump so we
#      handle BOTH datetime objects and the ISO strings Pydantic emits.
#   3. KEEP explicit None values (don't strip). jcs serializes null
#      deterministically; stripping would lose the distinction between
#      "absent" and "explicitly null" for Optional bitemporal-adjacent fields
#      (e.g. supersedes, did_doc_snapshot_at). 06-RESEARCH §2 Open Question 3
#      locked this as KEEP; the canonical None policy belongs in one place.
#
# Float canonicalization: jcs emits the shortest round-trip per RFC 8785 from
# the native Python float — DON'T pre-stringify floats before passing them in.

_DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"  # canonical RFC-3339 UTC, 6-digit µs, Z suffix


def _canonicalize_datetime(dt: datetime) -> str:
    """Render a datetime as the canonical RFC-3339 UTC string used by JCS hashing.

    Coerces to UTC if tz-aware (and required tz-aware — naive datetimes are a
    project invariant); emits ``YYYY-MM-DDTHH:MM:SS.ffffffZ`` with a fixed
    6-digit microsecond and a literal ``Z`` suffix. The same representation
    survives ``model_dump → model_validate → model_dump`` round-trips, which
    closes the remaining F4 datetime surface (signer/verifier agreement).
    """
    if dt.tzinfo is None:
        # Project invariant: every datetime is tz-aware UTC (D-04).
        raise ValueError(
            f"Naive datetime {dt!r} cannot be canonicalized for JCS hashing — "
            "all shard datetimes must be tz-aware UTC (D-04)."
        )
    # Coerce to UTC and strip the +00:00 offset, emit the canonical "Z" form
    # with always-6-digit microseconds.
    utc = dt.astimezone(UTC)
    return utc.strftime(_DATETIME_FORMAT)


def _normalize_for_jcs(obj: Any) -> Any:
    """Recursively NFC-normalize strings and canonicalize datetime-shaped values.

    Walks dict/list/scalar payloads emitted by ``model_dump(mode="json")``:

    * ``str`` — NFC-normalize via ``unicodedata.normalize("NFC", s)``. Also
      detects ISO-8601 datetime strings Pydantic emits (mode="json" renders
      datetimes as ``...+00:00`` or ``...Z`` strings) and coerces them to the
      canonical ``_DATETIME_FORMAT`` representation. This is the F4 datetime
      pin: every datetime-shaped string flows into JCS in ONE form.
    * ``dict`` — normalize every key (after NFC) and every value recursively.
      jcs sorts keys per RFC 8785, so we don't sort here.
    * ``list`` — normalize every element recursively; preserve order.
    * ``datetime`` — canonicalize via ``_canonicalize_datetime`` (covers the
      case where a caller hands a raw datetime through model_dump(mode="python")
      or where the dump preserves a datetime; the explicit path through model_dump
      mode="json" already pre-stringifies them but we handle both).
    * Other scalars (int / float / bool / None) — pass through unchanged. jcs
      handles them per RFC 8785 (minimal float encoding; explicit null).
    """
    if isinstance(obj, str):
        nfc = unicodedata.normalize("NFC", obj)
        # Detect ISO-8601 datetime strings Pydantic mode="json" emits. We
        # accept both `...+00:00` and `...Z` forms (Pydantic version variance,
        # see tests/shards/test_envelope_roundtrip.py L77) and coerce to the
        # canonical _DATETIME_FORMAT. The shape gate is conservative: must
        # start with `YYYY-MM-DDTHH:MM:SS` and end with `Z` or `+HH:MM`.
        if (
            len(nfc) >= 19
            and nfc[4] == "-" and nfc[7] == "-" and nfc[10] == "T"
            and nfc[13] == ":" and nfc[16] == ":"
            and (nfc.endswith("Z") or "+" in nfc[19:] or "-" in nfc[19:])
        ):
            try:
                # datetime.fromisoformat handles both `...Z` (Python 3.11+) and
                # `...+00:00`; we then re-emit through our canonical formatter.
                parsed = datetime.fromisoformat(nfc.replace("Z", "+00:00"))
                if parsed.tzinfo is not None:
                    return _canonicalize_datetime(parsed)
            except ValueError:
                # Not actually an ISO datetime — fall through to NFC string.
                pass
        return nfc
    if isinstance(obj, dict):
        return {
            unicodedata.normalize("NFC", k) if isinstance(k, str) else k:
            _normalize_for_jcs(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_normalize_for_jcs(item) for item in obj]
    if isinstance(obj, datetime):
        return _canonicalize_datetime(obj)
    return obj


def _jcs_canonical_bytes(payload: dict) -> bytes:
    """Return RFC-8785 JCS canonical bytes for ``payload`` after F4 pre-normalization.

    The single canonicalization core both signer and verifier flow through;
    the cross-impl golden test (tests/identity/test_jcs_golden.py) asserts
    that the bytes returned here match the cyberphone/json-canonicalization
    reference vectors on a vendored input set.
    """
    normalized = _normalize_for_jcs(payload)
    return jcs.canonicalize(normalized)


def canonical_content_hash(shard: ShardEnvelope) -> str:
    """RFC-8785 JCS SHA-256 over the shard's CONTENT (D-05, D-12 / DID-03).

    Hashes the shard's content fields ONLY — everything EXCEPT the
    ``_HASH_EXCLUDED_FIELDS`` set (``transaction_time``, ``valid_time_start``,
    ``valid_time_end``, ``content_edits``, ``signatures``). The included content
    covers the Fregean ``triple``, ``sense``/``reference``, the 6 identity-and-
    origin fields, ``layer``/``fork``/``epistemic_status`` and the rest of the
    §6.1 envelope content.

    Phase 6 (DID-03) swapped raw ``json.dumps`` for the RFC-8785 JCS
    canonicalization pipeline (``_jcs_canonical_bytes``) with the F4
    pre-normalization recipe (06-RESEARCH §2):

    1. ``model_dump(mode="json", exclude=_HASH_EXCLUDED_FIELDS)`` — Pydantic
       renders datetimes → ISO strings, Literals/enums → plain strings.
    2. ``_normalize_for_jcs`` — recursive NFC normalize of every string key/value,
       canonical-RFC-3339-UTC datetime pin (``...Z`` suffix, fixed µs),
       explicit None KEEP (06-RESEARCH §2 Open Question 3 lock).
    3. ``jcs.canonicalize`` — RFC-8785 key ordering + minimal float encoding.
    4. ``sha256`` over the canonical bytes.

    Function signature, ``_HASH_EXCLUDED_FIELDS``, and every call site are
    UNCHANGED (the D-05 / D-12 seam). The 1000-shuffled-order property test
    (tests/identity/test_canonical_jcs_properties.py) and the cyberphone
    cross-impl golden test (tests/identity/test_jcs_golden.py) prove F4 is
    closed.
    """
    payload = shard.model_dump(mode="json", exclude=_HASH_EXCLUDED_FIELDS)
    return hashlib.sha256(_jcs_canonical_bytes(payload)).hexdigest()


# ── sign_attestation (D-05) — unsigned Phase 6 stub ──────────────────────────


def sign_attestation(editor_did: str, over_content_hash: str) -> AttestedSignature:
    """Return an UNSIGNED ``AttestedSignature`` placeholder (D-05).

    ``signature=""`` is unmistakably unsigned — Phase 6 (DID substrate) fills real
    ed25519 over the JCS-canonical content hash. ``over_content_hash`` is the REAL
    pre-edit ``canonical_content_hash`` so the audit record's content binding is
    meaningful from day one; only the cryptographic signature is deferred.
    """
    return AttestedSignature(
        did=editor_did,
        action="content_edit",
        over_content_hash=over_content_hash,
        signature="",
        signed_at=datetime.now(UTC),
    )


# ── validate_shard (V5 / RESEARCH Pitfall 2) — post-edit re-validation hook ──


def validate_shard(shard: ShardEnvelope) -> ShardEnvelope:
    """Re-run FULL model validation on ``shard`` and return the re-validated copy.

    ``validate_assignment`` is OFF (RESEARCH Pitfall 2), so a wrong-type assignment
    via ``set_field`` is accepted silently. Re-validating through
    ``model_validate(model_dump())`` re-runs every field validator AND the
    authoritative forward-only ``@model_validator`` on ``ShardEnvelope``, so a
    silent bad value (or a back-dated edit) is rejected at edit time rather than
    corrupting the shard. "Keep it honest" (CONTEXT) — this is a real re-validation,
    not a pass-through. Phase 11 (SHACL Hybrid) extends this hook.
    """
    return type(shard).model_validate(shard.model_dump())


# ── edit_shard_content (D-01, D-02, D-03, D-06) — the PRD §6.4 write path ─────


async def edit_shard_content(
    shard_iri: str,
    field_path: str,
    new_value: Any,
    editor_did: str,
    rationale: str,
    signing_key: Any,  # UNUSED in Phase 5 — Phase 6 wires real signing through it
    store: ShardStore,
) -> ContentEdit:
    """Apply an audited content edit to the shard at ``shard_iri`` (PRD §6.4, D-01).

    Sequence (RESEARCH L246-291; CR-01 / WR-03 transactional-write fix):

    1. ``await store.get(shard_iri)`` — raise ``ValueError`` if unknown (D-02).
    2. ``IMMUTABLE_FIELD_PATHS`` gate (D-06) — raise BEFORE any mutation.
    3. Take a DEEP WORKING COPY of the stored shard. ALL mutation happens on the
       copy, so the stored object is byte-for-byte unchanged if ANY later step
       raises (CR-01: ``InMemoryShardStore.get`` returns the same object reference
       held in the dict, so mutating it in place corrupts stored state even when
       this function later raises and never calls ``put``). This mirrors the
       reverse-replay D-09 rule: never mutate the stored shard.
    4. Capture ``old_value`` + the REAL pre-edit ``canonical_content_hash`` (D-05)
       off the working copy.
    5. Build the ``ContentEdit`` (signed with the unsigned Phase-6 stub), append
       it to the working copy, and assign the new value on the working copy. No
       rollback bookkeeping is needed — if anything raises, the working copy is
       simply discarded and the stored shard was never touched.
    6. ``validate_shard`` post-edit re-validation (V5) on the working copy —
       rejects silent wrong types AND back-dated chains via the authoritative
       forward-only validator. CAPTURE its return (WR-03): it is the re-validated
       / coerced ``ShardEnvelope`` that becomes the authoritative stored object.
    7. ``await store.put(...)`` the VALIDATED copy (reached only on full success)
       and return the recorded ``ContentEdit`` from that validated copy.

    ``signing_key`` is accepted and unused (Phase 6 stub — named for the seam).
    """
    stored = await store.get(shard_iri)
    if stored is None:
        raise ValueError(
            f"Unknown shard IRI {shard_iri!r}: no shard registered in the store "
            "(D-02 by-IRI lookup returned None). Refusing to edit."
        )

    # D-06 gate — BEFORE any mutation. ``triple.subject``/``.predicate`` are NOT
    # frozen on the mutable Triple submodel, so this gate is their only guard.
    if field_path in IMMUTABLE_FIELD_PATHS:
        raise ValueError(
            f"Field {field_path!r} is immutable (IMMUTABLE_FIELD_PATHS, D-06); "
            "edits to identity fields, triple.subject/.predicate, or the "
            "append-only content_edits/signatures lists are forbidden. "
            "(triple.object is editable — re-parenting, D-04.)"
        )

    # CR-01: deep working copy — the stored shard is NEVER mutated. Any exception
    # below discards `working` and leaves the stored object byte-for-byte intact.
    working = stored.model_copy(deep=True)

    old_value = get_field(working, field_path)
    pre_edit_hash = canonical_content_hash(working)

    edit = ContentEdit(
        field_path=field_path,
        old_value=old_value,
        new_value=new_value,
        edited_at=datetime.now(UTC),
        editor_did=editor_did,
        rationale=rationale,
        signature=sign_attestation(editor_did, pre_edit_hash),
    )

    # Append + assign on the working copy only. No try/except rollback is needed:
    # `working` is thrown away on any exception and the store still holds the
    # untouched original (CR-01 supersedes the old append/pop bookkeeping).
    working.content_edits.append(edit)
    set_field(working, field_path, new_value)

    # Post-edit re-validation (V5 / Pitfall 2): silent wrong-type or back-dated
    # chain is rejected HERE, on the working copy, before the store sees anything.
    # WR-03: capture the re-validated/coerced copy and make IT the stored object —
    # the pre-fix code discarded this return and stored the un-coerced object.
    validated = validate_shard(working)

    await store.put(shard_iri, validated)
    # Return the edit as it lives in the stored (validated) object, so the
    # returned record and the stored chain entry are the SAME instance.
    return validated.content_edits[-1]


# ── get_shard_at (D-09) — reverse-replay historical reconstruction ───────────


async def get_shard_at(
    shard_iri: str, t: datetime, store: ShardStore
) -> ShardEnvelope | None:
    """Reconstruct the shard's state as-of time ``t`` by reverse-replay (D-09).

    Algorithm (RESEARCH L136-149):

    1. ``store.get(shard_iri)``; unknown IRI → ``None`` (the unambiguous D-09/A3
       choice — never a silent wrong answer).
    2. ``t < extracted_at`` → ``None`` (the shard did not exist yet; strict edge).
    3. ``working = shard.model_copy(deep=True)`` — NEVER mutate the stored shard
       (Pitfall 3; the deep copy isolates the Triple submodel and the edit list).
    4. Undo every edit with ``edited_at > t`` in REVERSE-chronological order,
       restoring ``old_value`` via ``set_field``. STRICT ``>`` — an edit at exactly
       ``t`` counts as having-happened-by-``t`` and is KEPT (Pitfall 4 / D-09 ties).
    5. Trim ``content_edits`` to only entries with ``edited_at <= t`` (the
       historical view of the chain at time ``t``).

    Reverse-replay correctness depends on append order == chronological order,
    which the authoritative forward-only validator guarantees (mutually
    reinforcing). ``get_shard_at(iri, extracted_at)`` returns the exact-as-extracted
    state (all content edits undone, chain trimmed to []); ``get_shard_at(iri,
    latest_edit_time)`` returns the current shard unchanged.
    """
    shard = await store.get(shard_iri)
    if shard is None:
        return None
    if t < shard.extracted_at:
        return None

    working = shard.model_copy(deep=True)
    for edit in reversed(working.content_edits):
        if edit.edited_at > t:
            set_field(working, edit.field_path, edit.old_value)
    # Trim the chain to the historical view at time t (kept edits only).
    working.content_edits = [e for e in working.content_edits if e.edited_at <= t]
    return working


__all__ = [
    "IMMUTABLE_FIELD_PATHS",
    "get_field",
    "set_field",
    "canonical_content_hash",
    "_jcs_canonical_bytes",  # exposed for the cross-impl golden test (DID-03 / F4)
    "sign_attestation",
    "validate_shard",
    "edit_shard_content",
    "get_shard_at",
]
