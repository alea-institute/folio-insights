"""Phase 13 persistent storage: SQLite journal + Oxigraph projection.

Lives outside the pure-model dependency boundaries (``shards/``,
``governance/``, ``revision/store.py``), which keep their stdlib + Pydantic
seams. Open one ``CorpusStorageContext`` per corpus and use its ``shards`` and
``governance`` adapters wherever the in-memory doubles are used today.
"""
from __future__ import annotations

from folio_insights.storage.context import (
    FULL_SHACL_STATUS,
    CorpusStorageContext,
    StorageConfig,
    StorageStatus,
    StoredShardRecord,
    open_corpus_storage,
    verify_event_signature_offline,
)
from folio_insights.storage.errors import (
    CorpusIsolationError,
    OperationIdConflict,
    PiiRejected,
    ProjectionLockTimeout,
    ProjectionRecoveryFailed,
    ProjectionRecoveryPending,
    ShardIdentityViolation,
    StorageClosed,
    StorageError,
    UnsupportedStorageSchema,
)
from folio_insights.storage.governance import PersistentGovernanceLog
from folio_insights.storage.pii import DEFAULT_PII_PATTERNS, PiiGate, PiiPattern
from folio_insights.storage.shards import PersistentShardStore

__all__ = [
    "DEFAULT_PII_PATTERNS",
    "FULL_SHACL_STATUS",
    "CorpusIsolationError",
    "CorpusStorageContext",
    "OperationIdConflict",
    "PersistentGovernanceLog",
    "PersistentShardStore",
    "PiiGate",
    "PiiPattern",
    "PiiRejected",
    "ProjectionLockTimeout",
    "ProjectionRecoveryFailed",
    "ProjectionRecoveryPending",
    "ShardIdentityViolation",
    "StorageClosed",
    "StorageConfig",
    "StorageError",
    "StorageStatus",
    "StoredShardRecord",
    "UnsupportedStorageSchema",
    "open_corpus_storage",
    "verify_event_signature_offline",
]
