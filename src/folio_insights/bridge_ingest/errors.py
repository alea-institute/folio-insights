"""Refusals raised by bridge-ingest.

Every refusal is a ``ValueError`` subclass, so the CLI and the HTTP route can
map the whole family to one input-refusal response. Messages name proposition
ids and IRIs, never filesystem paths or proposition text.
"""
from __future__ import annotations


class BridgeIngestError(ValueError):
    """Base class: the record was refused and nothing was written."""


class InvalidRecord(BridgeIngestError):
    """The input is not a valid ``PropositionDocumentRecord`` (any supported form)."""


class MissingSourceUri(BridgeIngestError):
    """The record has no ``source_uri``, so no shard IRI can be minted."""

    def __init__(self, document_id: str | None) -> None:
        super().__init__(
            f"record {document_id!r} has no source_uri; bridge-ingest needs it to "
            "mint shard IRIs (enrich sets it before export)"
        )
        self.document_id = document_id


class ContentIriMismatch(BridgeIngestError):
    """A proposition's stamped ``content_iri`` differs from ``mint_shard_iri``.

    The whole record is refused (plan R11): the two products disagree on the
    identity recipe or the record was altered, and re-minting silently would
    hide that.
    """

    def __init__(self, proposition_id: str, stamped: str, minted: str) -> None:
        super().__init__(
            f"proposition {proposition_id!r} carries content_iri {stamped!r} but "
            f"mint_shard_iri(source_uri, text) gives {minted!r}; refusing the record"
        )
        self.proposition_id = proposition_id
        self.stamped = stamped
        self.minted = minted


class InvalidExtractorDid(BridgeIngestError):
    """The extractor DID does not match the envelope SHACL ``did:(key|web|plc):`` pattern."""


__all__ = [
    "BridgeIngestError",
    "ContentIriMismatch",
    "InvalidExtractorDid",
    "InvalidRecord",
    "MissingSourceUri",
]
