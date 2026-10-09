"""folio-enrich -> folio-insights bridge ingest ("bridge, not merge").

Turns a folio-enrich ``PropositionDocumentRecord`` export into
``HypothesisShard`` s under the shared content identity (``mint_shard_iri`` ==
``folio_propositions.content_iri``), writes them through the corpus storage
gates, and answers the bridge status read contract. See
``docs/bridge-ingest.md``.
"""
from folio_insights.bridge_ingest.errors import (
    BridgeIngestError,
    ContentIriMismatch,
    InvalidExtractorDid,
    InvalidRecord,
    MissingSourceUri,
)
from folio_insights.bridge_ingest.ingest import IngestReport, RefusedShard, ingest_record
from folio_insights.bridge_ingest.mapping import (
    DEFAULT_EXTRACTOR_DID,
    DEFAULT_FRAMEWORK_ID,
    ManifestEntry,
    ManifestSource,
    MappingResult,
    SkippedProposition,
    propositions_to_shards,
)
from folio_insights.bridge_ingest.record import LoadedRecord, load_record
from folio_insights.bridge_ingest.status import (
    MAX_STATUS_IRIS,
    ContestingRef,
    EnrichSource,
    RelatedRef,
    StatusResult,
    shard_count,
    shard_status,
)

__all__ = [
    "DEFAULT_EXTRACTOR_DID",
    "DEFAULT_FRAMEWORK_ID",
    "MAX_STATUS_IRIS",
    "BridgeIngestError",
    "ContentIriMismatch",
    "ContestingRef",
    "EnrichSource",
    "IngestReport",
    "InvalidExtractorDid",
    "InvalidRecord",
    "LoadedRecord",
    "ManifestEntry",
    "ManifestSource",
    "MappingResult",
    "MissingSourceUri",
    "RefusedShard",
    "RelatedRef",
    "SkippedProposition",
    "StatusResult",
    "ingest_record",
    "load_record",
    "propositions_to_shards",
    "shard_count",
    "shard_status",
]
