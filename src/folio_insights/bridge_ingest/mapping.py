"""Map a folio-enrich ``PropositionDocumentRecord`` to ``HypothesisShard`` s.

``propositions_to_shards`` is a pure function: no I/O, no clock unless ``now``
is omitted. Identity comes from the frozen ``mint_shard_iri`` recipe; one shard
is produced per distinct IRI (identity is per ``(source_uri, span)``, so
several proposition types over one span share a shard, plan R12). Every
observed type and every enrich source survives in the provenance manifest and
in ``logical_form_imputed``.

Field mapping (one row per ``HypothesisShard`` field this module sets; every
other field keeps its model default)::

    field                    value
    -----------------------  ---------------------------------------------------
    shard_iri                mint_shard_iri(record.source_uri, text)[0]
    provenance_hash          mint_shard_iri(record.source_uri, text)[1]
    source_uri               record.source_uri
    source_span              the proposition text (first proposition of the
                             group, sorted by (proposition_type, id))
    extracted_at             record.document_metadata timestamp (first of
                             EXTRACTED_AT_KEYS that parses as ISO-8601, made
                             UTC), else ``now`` (UTC)
    first_extractor_did      ``extractor_did`` argument (must match the SHACL
                             ``^did:(key|web|plc):.+`` pattern)
    epistemic_status         "hypothesis"
    generation_method        "inductive"
    verification_method      "extractor_assertion"
    predication_mode         "per_accidens"
    fork                     "synthetic_a_posteriori"
    layer                    "L3_jurisdictional"
    bfo_category             "continuant_dependent"
    speech_act               SPEECH_ACT_BY_ROLE[asserter.role] of the first
                             proposition; no asserter -> "dictum"
    triple                   Triple(subject=asserter.individual_id
                             or "role:<role>" or "unknown",
                             predicate=<proposition_type>, object=<text>)
    sense                    the proposition text
    reference                WORKING_TAXONOMY[type] FOLIO IRI when not None,
                             else "urn:folio-propositions:type/<slug(type)>"
    logical_form_imputed     "PROPOSITION_TYPES(<sorted distinct types | ...>)"
    framework_id             ``framework_id`` argument
    extractor_version        record.generator.version or "unknown"
    extractor_model          record.generator.tool or "unknown"
    extraction_prompt_hash   sha256("<tool>|<version>|<proposition_lexicon_version>")
    confidence               0.5
    ttl_days                 model default (90)
    depends_on_precedents    [] (enrich citation edges point at enrich
                             individual ids, not insights IRIs; they are kept
                             in the manifest only)
    elaborates / depends_on_* / signatures / content_edits  [] (defaults)

Deviation from the I1 spec, following the model: the spec lists the six
envelope defaults; the real model (``shards/envelope.py``) also requires
``schema_version`` and ``vocab_version`` (both default to the current pins,
which the envelope validators insist on) and ``transaction_time`` (defaults
to the wall clock). Nothing else is required.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from folio_propositions import WORKING_TAXONOMY, Proposition, PropositionDocumentRecord
from pydantic import BaseModel, ConfigDict, Field

from folio_insights.bridge_ingest.errors import (
    ContentIriMismatch,
    InvalidExtractorDid,
    MissingSourceUri,
)
from folio_insights.shards.envelope import Triple
from folio_insights.shards.minting import mint_shard_iri
from folio_insights.shards.subtypes import HypothesisShard

DEFAULT_FRAMEWORK_ID = "us.case-law.unspecified"
DEFAULT_EXTRACTOR_DID = "did:web:folio-enrich.local"
DEFAULT_CONFIDENCE = 0.5
TYPE_REFERENCE_PREFIX = "urn:folio-propositions:type/"

# Envelope SHACL (shapes/ttl/envelope.shacl.ttl): fi:firstExtractorDid pattern.
_DID_PATTERN = re.compile(r"^did:(key|web|plc):.+")

# document_metadata keys read (in order) for extracted_at.
EXTRACTED_AT_KEYS: tuple[str, ...] = (
    "extracted_at",
    "exported_at",
    "completed_at",
    "created_at",
    "timestamp",
)

_PARTY_ROLES = (
    "party",
    "plaintiff",
    "defendant",
    "appellant",
    "appellee",
    "petitioner",
    "respondent",
    "both_parties",
)

# Asserter role -> envelope speech_act (I1 spec table).
SPEECH_ACT_BY_ROLE: Mapping[str | None, str] = {
    "court": "holding",
    "secondary_source": "treatise_statement",
    **{role: "pleading_argument" for role in _PARTY_ROLES},
    "system": "dictum",
    None: "dictum",
}

# Fixed hypothesis defaults (I1 spec; see module docstring).
HYPOTHESIS_DEFAULTS: Mapping[str, Any] = {
    "epistemic_status": "hypothesis",
    "generation_method": "inductive",
    "verification_method": "extractor_assertion",
    "predication_mode": "per_accidens",
    "fork": "synthetic_a_posteriori",
    "layer": "L3_jurisdictional",
    "bfo_category": "continuant_dependent",
    "confidence": DEFAULT_CONFIDENCE,
}


class ManifestSource(BaseModel):
    """One enrich proposition behind a shard IRI."""

    model_config = ConfigDict(extra="forbid")

    document_id: str
    proposition_id: str
    proposition_type: str
    start_char: int | None = None
    end_char: int | None = None
    disposition: str
    asserter_role: str | None = None
    citation_edges: list[dict[str, Any]] = Field(default_factory=list)


class ManifestEntry(BaseModel):
    """Every enrich source observed for one shard IRI in one record."""

    model_config = ConfigDict(extra="forbid")

    iri: str
    source_uri: str
    sources: list[ManifestSource]


class SkippedProposition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposition_id: str
    reason: str


class MappingResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    shards: list[HypothesisShard]
    manifest: list[ManifestEntry]
    skipped: list[SkippedProposition]


def type_slug(proposition_type: str) -> str:
    """Lowercase ASCII slug: runs of anything but ``[a-z0-9]`` become ``-``."""
    ascii_text = (
        unicodedata.normalize("NFKD", proposition_type).encode("ascii", "ignore").decode("ascii")
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug or "unnamed"


def type_reference(proposition_type: str) -> str:
    iri = WORKING_TAXONOMY.get(proposition_type)
    if iri:
        return iri
    return TYPE_REFERENCE_PREFIX + type_slug(proposition_type)


def _role(proposition: Proposition) -> str | None:
    return None if proposition.asserter is None else proposition.asserter.role.value


def speech_act_for(proposition: Proposition) -> str:
    return SPEECH_ACT_BY_ROLE.get(_role(proposition), "dictum")


def triple_subject(proposition: Proposition) -> str:
    asserter = proposition.asserter
    if asserter is None:
        return "unknown"
    if asserter.individual_id:
        return asserter.individual_id
    return f"role:{asserter.role.value}"


def extraction_prompt_hash(record: PropositionDocumentRecord) -> str:
    tool = record.generator.tool if record.generator else "unknown"
    version = record.generator.version if record.generator else "unknown"
    lexicon = (record.document_metadata or {}).get("proposition_lexicon_version") or ""
    return hashlib.sha256(f"{tool}|{version}|{lexicon}".encode()).hexdigest()


def record_timestamp(record: PropositionDocumentRecord) -> datetime | None:
    metadata = record.document_metadata or {}
    for key in EXTRACTED_AT_KEYS:
        value = metadata.get(key)
        if not isinstance(value, str) or not value:
            continue
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            continue
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    return None


def _manifest_source(record: PropositionDocumentRecord, p: Proposition) -> ManifestSource:
    return ManifestSource(
        document_id=record.document_id,
        proposition_id=p.id,
        proposition_type=p.proposition_type,
        start_char=p.start_char,
        end_char=p.end_char,
        disposition=p.disposition.value,
        asserter_role=_role(p),
        citation_edges=[edge.model_dump(mode="json") for edge in p.citation_edges],
    )


def propositions_to_shards(
    record: PropositionDocumentRecord,
    *,
    framework_id: str = DEFAULT_FRAMEWORK_ID,
    extractor_did: str = DEFAULT_EXTRACTOR_DID,
    now: datetime | None = None,
) -> MappingResult:
    """Map ``record`` to one ``HypothesisShard`` per distinct shard IRI.

    Raises ``MissingSourceUri`` when the record has no ``source_uri``,
    ``ContentIriMismatch`` when any stamped ``content_iri`` differs from the
    minted IRI (the whole record is refused), and ``InvalidExtractorDid`` for a
    DID the envelope SHACL suite would refuse.
    """
    source_uri = record.source_uri
    if not source_uri:
        raise MissingSourceUri(record.document_id)
    if not _DID_PATTERN.match(extractor_did or ""):
        raise InvalidExtractorDid(
            f"extractor DID {extractor_did!r} must match did:(key|web|plc):..."
        )
    if not framework_id:
        raise ValueError("framework_id must be a non-empty string")

    skipped: list[SkippedProposition] = []
    groups: dict[str, tuple[str, list[Proposition]]] = {}
    for p in record.propositions:
        if p.text is None:
            skipped.append(SkippedProposition(proposition_id=p.id, reason="no text"))
            continue
        if not p.text.strip():
            skipped.append(SkippedProposition(proposition_id=p.id, reason="empty text"))
            continue
        iri, provenance_hash = mint_shard_iri(source_uri, p.text)
        if p.content_iri is not None and p.content_iri != iri:
            raise ContentIriMismatch(p.id, p.content_iri, iri)
        groups.setdefault(iri, (provenance_hash, []))[1].append(p)

    extracted_at = record_timestamp(record) or (now or datetime.now(UTC))
    if extracted_at.tzinfo is None:
        extracted_at = extracted_at.replace(tzinfo=UTC)
    tool = record.generator.tool if record.generator else "unknown"
    version = record.generator.version if record.generator else "unknown"
    prompt_hash = extraction_prompt_hash(record)

    shards: list[HypothesisShard] = []
    manifest: list[ManifestEntry] = []
    for iri, (provenance_hash, members) in groups.items():
        members = sorted(members, key=lambda m: (m.proposition_type, m.id))
        first = members[0]
        text = first.text or ""
        types = sorted({m.proposition_type for m in members})
        shards.append(
            HypothesisShard(
                shard_iri=iri,
                provenance_hash=provenance_hash,
                source_uri=source_uri,
                source_span=text,
                extracted_at=extracted_at,
                first_extractor_did=extractor_did,
                triple=Triple(
                    subject=triple_subject(first),
                    predicate=first.proposition_type,
                    object=text,
                ),
                sense=text,
                reference=type_reference(first.proposition_type),
                logical_form_imputed="PROPOSITION_TYPES(" + " | ".join(types) + ")",
                speech_act=speech_act_for(first),  # type: ignore[arg-type]
                framework_id=framework_id,
                extractor_version=version or "unknown",
                extractor_model=tool or "unknown",
                extraction_prompt_hash=prompt_hash,
                **HYPOTHESIS_DEFAULTS,  # type: ignore[arg-type]
            )
        )
        manifest.append(
            ManifestEntry(
                iri=iri,
                source_uri=source_uri,
                sources=[_manifest_source(record, m) for m in members],
            )
        )
    return MappingResult(shards=shards, manifest=manifest, skipped=skipped)


__all__ = [
    "DEFAULT_CONFIDENCE",
    "DEFAULT_EXTRACTOR_DID",
    "DEFAULT_FRAMEWORK_ID",
    "EXTRACTED_AT_KEYS",
    "HYPOTHESIS_DEFAULTS",
    "SPEECH_ACT_BY_ROLE",
    "TYPE_REFERENCE_PREFIX",
    "ManifestEntry",
    "ManifestSource",
    "MappingResult",
    "SkippedProposition",
    "extraction_prompt_hash",
    "propositions_to_shards",
    "record_timestamp",
    "speech_act_for",
    "triple_subject",
    "type_reference",
    "type_slug",
]
