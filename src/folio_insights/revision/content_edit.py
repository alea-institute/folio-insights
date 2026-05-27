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
import json
from datetime import UTC, datetime
from typing import Any

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


def get_field(shard: ShardEnvelope, path: str) -> Any:
    """Read a (possibly nested) field by dotted path: ``"triple.object"`` walks
    ``shard.triple.object``; ``"sense"`` reads the top-level field."""
    obj: Any = shard
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


def set_field(shard: ShardEnvelope, path: str, value: Any) -> None:
    """Assign a (possibly nested) field by dotted path.

    NOTE: ``validate_assignment`` is OFF on ``ShardEnvelope`` (verified — RESEARCH
    Pitfall 2), so this setter accepts wrong types SILENTLY. For reverse-replay
    that is safe (restoring a previously-valid value); for ``edit_shard_content``
    the incoming ``new_value`` is unvalidated, so the caller MUST re-validate via
    ``validate_shard`` after applying it. The 6 frozen identity fields still raise
    on assignment; ``triple.subject``/``.predicate`` do NOT (the gate guards them).
    """
    parts = path.split(".")
    obj: Any = shard
    for part in parts[:-1]:
        obj = getattr(obj, part)  # walk to the parent submodel
    setattr(obj, parts[-1], value)  # assign the leaf


# ── canonical_content_hash (D-05) — REAL deterministic JSON SHA-256 ──────────


def canonical_content_hash(shard: ShardEnvelope) -> str:
    """Deterministic SHA-256 over the (pre-edit) shard snapshot (D-05).

    ``model_dump(mode="json")`` renders datetimes → ISO-8601 and enums/Literals →
    plain strings (JSON-safe primitives, no custom encoder), then sorted-key
    ``json.dumps`` gives a stable canonical form. Mirrors the ``shards/minting.py``
    L89-93 sha256-over-normalized-payload precedent.

    Phase 6 swaps RFC 8785 JCS canonicalization into the ``json.dumps`` line ONLY
    — the function signature and every call site stay identical (D-05 seam).
    """
    payload = shard.model_dump(mode="json")
    canon = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


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

    Sequence (RESEARCH L246-291):

    1. ``await store.get(shard_iri)`` — raise ``ValueError`` if unknown (D-02).
    2. ``IMMUTABLE_FIELD_PATHS`` gate (D-06) — raise BEFORE any mutation.
    3. Capture ``old_value`` + the REAL pre-edit ``canonical_content_hash`` (D-05).
    4. Build the ``ContentEdit`` (signed with the unsigned Phase-6 stub).
    5. Transactionally append the edit + assign the new value; roll the append
       back if ``set_field`` raises (e.g. assigning a frozen leaf), so the chain
       never carries an edit whose assignment failed.
    6. ``validate_shard`` post-edit re-validation (V5 — rejects silent wrong types
       AND back-dated chains via the authoritative forward-only validator).
    7. ``await store.put(...)`` and return the recorded ``ContentEdit``.

    ``signing_key`` is accepted and unused (Phase 6 stub — named for the seam).
    """
    shard = await store.get(shard_iri)
    if shard is None:
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

    old_value = get_field(shard, field_path)
    pre_edit_hash = canonical_content_hash(shard)

    edit = ContentEdit(
        field_path=field_path,
        old_value=old_value,
        new_value=new_value,
        edited_at=datetime.now(UTC),
        editor_did=editor_did,
        rationale=rationale,
        signature=sign_attestation(editor_did, pre_edit_hash),
    )

    # Transactional append+assign: roll the append back if assignment fails so the
    # audit chain never carries an edit whose set_field raised.
    shard.content_edits.append(edit)
    try:
        set_field(shard, field_path, new_value)
    except Exception:
        shard.content_edits.pop()
        raise

    # Post-edit re-validation (V5 / Pitfall 2): silent wrong-type or back-dated
    # chain is rejected HERE, before the store sees the corrupted shard.
    validate_shard(shard)

    await store.put(shard_iri, shard)
    return edit


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
    "sign_attestation",
    "validate_shard",
    "edit_shard_content",
    "get_shard_at",
]
