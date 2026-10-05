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

    A verbatim copy of a journaled signed event, re-sent under a fresh
    operation ID, would otherwise be appended again (a replayed revocation,
    for instance). A copy with a moved ``signed_at`` fails signature
    verification instead, since the signed payload binds it.
    """


class JournalStateChanged(ValueError):
    """A guarded write named the journal state it was prepared against, and
    the corpus journal has moved on since (another shard revision or
    governance event committed in between). Nothing was appended.

    Raised inside the serialized write transaction, so the comparison and the
    append are atomic with respect to every other writer.
    """

    def __init__(self, *, expected: int, actual: int) -> None:
        super().__init__(
            f"corpus journal is at position {actual}, not the position {expected} "
            "this write was prepared against; nothing was appended"
        )
        self.expected = expected
        self.actual = actual


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

    def __reduce__(self) -> tuple:
        # Rebuild from the two names (never the message) across processes.
        return (type(self), (self.field_path, self.pattern_name))


class ShaclViolation(ValueError):
    """The record violates the Phase 11 SHACL suite; nothing was persisted.

    ``results`` holds one dict per Violation (focus node, path, constraint
    component, source shape and the shape's message). The message names
    the focus node and the shape messages, never the offending value.
    Shape messages are fixed text. Warnings never raise.
    """

    def __init__(self, subject: str, results: tuple[dict, ...] | list[dict]) -> None:
        self.subject = subject
        self.results = tuple(results)
        shown = "; ".join(
            f"{r.get('component')} on {r.get('path') or 'the node'}: {r.get('message')}"
            for r in self.results[:3]
        )
        more = f" (+{len(self.results) - 3} more)" if len(self.results) > 3 else ""
        super().__init__(
            f"refused before journal append: {subject} violates {len(self.results)} "
            f"SHACL constraint(s): {shown}{more}"
        )

    def __reduce__(self) -> tuple:
        return (type(self), (self.subject, self.results))


__all__ = [
    "CorpusIsolationError",
    "GovernanceEventReplayed",
    "JournalStateChanged",
    "OperationIdConflict",
    "PiiRejected",
    "ProjectionLockTimeout",
    "ProjectionRecoveryFailed",
    "ProjectionRecoveryPending",
    "ShardIdentityViolation",
    "ShaclViolation",
    "ShardRecordInvalid",
    "StorageClosed",
    "StorageError",
    "UnsupportedStorageSchema",
]
