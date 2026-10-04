"""Typed refusals raised by the Phase 13 persistent storage layer.

Every refusal is a ``ValueError`` or ``RuntimeError`` subclass so callers that
already catch those keep working; new callers can catch the specific type.
"""
from __future__ import annotations


class StorageError(RuntimeError):
    """Base class for storage-layer failures that are not input refusals."""


class UnsupportedStorageSchema(StorageError):
    """The on-disk journal or projection declares a schema this code cannot use."""


class StorageClosed(StorageError):
    """The storage context was closed (explicitly, or after a recovery failure)."""


class ProjectionRecoveryFailed(StorageError):
    """The RDF projection could not catch up to the committed journal.

    The context that raised this is closed (or never opened) so it never
    serves a mixed revision; query and export refuse until recovery succeeds.
    """


class ProjectionRecoveryPending(ProjectionRecoveryFailed):
    """A journal commit succeeded but the RDF projection could not catch up.

    The operation is durable and pending recovery, not aborted: reopening the
    context replays the journal into the projection, and retrying the same
    operation ID returns the committed result. The context that raised this is
    closed so it never serves a mixed revision.
    """

    def __init__(self, message: str, *, op_id: str, position: int) -> None:
        super().__init__(message)
        self.op_id = op_id
        self.position = position


class ProjectionLockTimeout(StorageError):
    """The projection lock could not be acquired within the configured timeout."""


class CorpusIsolationError(ValueError):
    """A request named a corpus other than the one this context is bound to."""


class OperationIdConflict(ValueError):
    """An operation ID was reused for a different request."""


class GovernanceEventReplayed(ValueError):
    """A governance event whose signature is already in the committed history.

    The signature covers only the event body, so a journaled event re-sent
    with a moved ``signature.signed_at`` or under a fresh operation ID would
    otherwise be accepted again (a replayed revocation, for instance).
    """


class ShardRecordInvalid(ValueError):
    """A shard record failed model validation.

    The message lists field locations and error types only; input values are
    never included, so refused text does not reach logs or tracebacks.
    """


class ShardIdentityViolation(ValueError):
    """A shard write would change frozen identity or shrink an append-only list."""


class PiiRejected(ValueError):
    """Raw text matched a configured PII pattern; nothing was persisted.

    The message names the field path and pattern, never the matched value, so
    the refused input is not retained in logs or tracebacks.
    """

    def __init__(self, field_path: str, pattern_name: str) -> None:
        super().__init__(
            f"refused before journal append: field {field_path!r} matches the "
            f"{pattern_name!r} PII pattern"
        )
        self.field_path = field_path
        self.pattern_name = pattern_name


__all__ = [
    "CorpusIsolationError",
    "GovernanceEventReplayed",
    "OperationIdConflict",
    "PiiRejected",
    "ProjectionLockTimeout",
    "ProjectionRecoveryFailed",
    "ProjectionRecoveryPending",
    "ShardIdentityViolation",
    "ShardRecordInvalid",
    "StorageClosed",
    "StorageError",
    "UnsupportedStorageSchema",
]
