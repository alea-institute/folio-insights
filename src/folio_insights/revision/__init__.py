"""Phase 5 ``revision/`` package — content-versioning write path + store seam (§6.4).

The async store-backed ``edit_shard_content`` write path (PRD §6.4 signature,
D-01), the in-memory ``ShardStore`` seam (D-02, Phase 13 swaps Oxigraph), the
dotted-path ``get_field``/``set_field`` helpers + ``IMMUTABLE_FIELD_PATHS`` gate
(D-06), the real ``canonical_content_hash`` + ``sign_attestation`` stub (D-05),
the ``validate_shard`` post-edit re-validation hook (V5), and ``get_shard_at``
reverse-replay reconstruction (D-09).

This package lives OUTSIDE the ``shards/`` dep-leak guard, so the sibling Plan 03
adds the pyshacl forward-only shape here (``shape_validation.py`` +
``content_edit_shape.ttl``). ``validate_content_edit_shape`` is NOT re-exported
from this ``__init__`` — Plan 03 owns its own module and its tests import it
directly. Leave this comment so Plan 03's parallel work needs no edit here.
"""
from folio_insights.revision.content_edit import (
    IMMUTABLE_FIELD_PATHS,
    canonical_content_hash,
    edit_shard_content,
    get_field,
    get_shard_at,
    set_field,
    sign_attestation,
    validate_shard,
)
from folio_insights.revision.store import InMemoryShardStore, ShardStore

__all__ = [
    "edit_shard_content",
    "get_shard_at",
    "get_field",
    "set_field",
    "IMMUTABLE_FIELD_PATHS",
    "canonical_content_hash",
    "sign_attestation",
    "validate_shard",
    "ShardStore",
    "InMemoryShardStore",
]
