"""KnowledgeUnit -> ``SimpleAssertionShard`` (drain U8, R1, R4, KTD1).

Every field is a pure function of verified evidence plus the gated fields, so
identical inputs and templates give identical shards (up to the wall-clock
``extracted_at`` / ``transaction_time`` and signature times, which are not part
of identity):

* ``source_uri`` = ``source_uri_for(namespace, source_key)``:
  ``urn:folio:source:<namespace>:<source key>``, each part percent-encoded. The
  namespace is the extraction run's ``corpus`` (the source collection the
  ingestion stage keyed every document under) and the source key is the
  document's ingested path (``CorpusDocument.file_path``, which every unit's
  ``source_file`` repeats). Both are recorded by ``folio-insights extract`` and
  independent of the machine, the checkout and the storage root, so the URI is
  stable across re-runs and machines. ``rubric.adapters.SourceResolver`` resolves
  it back to the file in a sources directory (its last ``:`` segment).
* ``source_span`` = the VERIFIED SOURCE SLICE from eligibility (KTD1), never the
  unit's distilled text. ``shard_iri`` / ``provenance_hash`` come from
  ``ShardIRIRegistry.register(source_uri, source_span)`` (the unchanged
  ``shards.minting`` recipe), so a model cannot choose a shard's identity.
* ``triple`` (documented mapping, deterministic): subject = the unit's top usable
  FOLIO tag IRI (highest confidence, ties by IRI; ruler tags and judged B9 tags
  only); predicate = the folio-insights module annotation property for the
  unit's knowledge type (``PREDICATE_BY_UNIT_TYPE``; the properties the v1 OWL
  module already publishes, ``services.owl_serializer``); object = the unit's
  distilled text as an ``xsd:string`` literal. The distilled text lives here and
  in ``sense``, never in ``source_span``.
* ``epistemic_status="hypothesis"`` (Chief, p10 q2: minted shards are hypotheses
  until a reviewer promotes them), ``verification_method="extractor_assertion"``.
* ``extraction_prompt_hash`` = ``combined_prompt_hash`` (sha256 over the sorted,
  de-duplicated template hashes) of every template hash in the unit's own
  lineage (U1, ``unit_prompt_hash``'s inputs) together with the hash of every
  template the minter called for the unit: always ``mint.fields.v1``, plus
  ``frameworks.detector_fallback`` / ``bfo.classifier_fallback`` when those LLM
  fallbacks ran. One flat set, so the composition is order-free.
* ``extractor_model`` = the ``provider:model`` routes that produced the unit's
  text and fields, sorted, de-duplicated, joined with ``+``: the minter's own
  calls, plus the run summary's ``llm.by_task`` route for every task whose
  template appears in the lineage.
* ``extractor_version`` = the installed ``folio_insights`` version.
* ``confidence`` = the minimum over the gates' confidences: the anchor match,
  the framework detection and the seven field confidences. (The strict BFO
  classifier is a pass/refuse gate whose assignment carries no confidence.)
* ``depends_on_axioms`` / ``depends_on_shards`` = the unit's ``cross_references``
  that are shard IRIs present in the corpus (kernel shards into
  ``depends_on_axioms``, others into ``depends_on_shards``); other cross
  references (the deduplicator's unit ids) are not dependencies.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any
from urllib.parse import quote

from folio_insights.llm.templates import combined_prompt_hash, get_template
from folio_insights.minting.eligibility import Eligible
from folio_insights.models.knowledge_unit import KnowledgeType, KnowledgeUnit
from folio_insights.shards import SimpleAssertionShard, Triple

SOURCE_URI_PREFIX = "urn:folio:source:"
SHARD_IRI_PREFIX = "urn:folio:shard/"
XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"
#: The folio-insights OWL module namespace (``services.owl_serializer.FOLIO_INSIGHTS``).
MODULE_NS = "https://folio.openlegalstandard.org/modules/folio-insights/"
PREDICATE_BY_UNIT_TYPE: Mapping[KnowledgeType, str] = {
    KnowledgeType.ADVICE: MODULE_NS + "bestPractice",
    KnowledgeType.PRINCIPLE: MODULE_NS + "principle",
    KnowledgeType.PITFALL: MODULE_NS + "pitfall",
}
EPISTEMIC_STATUS = "hypothesis"
VERIFICATION_METHOD = "extractor_assertion"


def source_uri_for(namespace: str, source_key: str) -> str:
    """The stable source document URI (module docstring)."""
    if not namespace:
        raise ValueError("a source namespace (the extraction run's corpus) is required")
    if not source_key:
        raise ValueError("the unit names no source file")
    return (f"{SOURCE_URI_PREFIX}{quote(namespace, safe='')}:"
            f"{quote(source_key, safe='/')}")


def unit_hash(eligible: Eligible, unit: KnowledgeUnit) -> str:
    """Deterministic unit identity for the op ID: the verified slice + the unit's content."""
    content = unit.content_hash or hashlib.sha256(unit.text.encode("utf-8")).hexdigest()
    payload = f"{eligible.source_key}\n{eligible.verified_span}\n{content}".encode()
    return hashlib.sha256(payload).hexdigest()[:32]


def mint_op_id(run_id: str, eligible: Eligible, unit: KnowledgeUnit) -> str:
    return f"mint:{run_id}:{unit_hash(eligible, unit)}"


def extract_event_op_id(shard_iri: str) -> str:
    """One ExtractEvent per shard, whichever run minted it."""
    return f"mint-extract:{shard_iri}"


def lineage_template_hashes(unit: KnowledgeUnit) -> dict[str, str]:
    from folio_insights.llm.templates import unit_template_hashes

    return unit_template_hashes(unit.lineage)


def prompt_hash(unit: KnowledgeUnit, minter_template_hashes: Iterable[str]) -> str:
    """``extraction_prompt_hash`` (module docstring)."""
    hashes = {e.template_hash for e in unit.lineage if e.template_id and e.template_hash}
    hashes.update(minter_template_hashes)
    if not hashes:
        raise ValueError("a minted shard always has at least the mint.fields template hash")
    return combined_prompt_hash(hashes)


def _summary_routes(summary: Mapping[str, Any] | None) -> dict[str, set[str]]:
    routes: dict[str, set[str]] = {}
    llm = summary.get("llm") if isinstance(summary, Mapping) else None
    rows = llm.get("by_task") if isinstance(llm, Mapping) else None
    for row in rows or []:
        if isinstance(row, Mapping) and row.get("task") and row.get("provider") and row.get("model"):
            routes.setdefault(str(row["task"]), set()).add(f"{row['provider']}:{row['model']}")
    return routes


def extractor_model(
    unit: KnowledgeUnit,
    minter_routes: Iterable[str],
    summary: Mapping[str, Any] | None,
) -> str:
    """``extractor_model`` (module docstring)."""
    models = set(minter_routes)
    routes = _summary_routes(summary)
    for template_id in lineage_template_hashes(unit):
        try:
            task = get_template(template_id).task
        except KeyError:
            continue
        models.update(routes.get(task, ()))
    if not models:
        raise ValueError("a minted shard needs the route of the call that produced its fields")
    return "+".join(sorted(models))


def triple_for(unit: KnowledgeUnit, eligible: Eligible) -> Triple:
    """The documented (top tag, knowledge-type predicate, distilled text) triple."""
    predicate = PREDICATE_BY_UNIT_TYPE.get(unit.unit_type)
    if predicate is None:
        raise ValueError(f"unit type {unit.unit_type.value!r} has no SimpleAssertion mapping")
    return Triple(
        subject=eligible.top_tag.iri,
        predicate=predicate,
        object=unit.text.strip(),
        object_datatype=XSD_STRING,
    )


def dependency_fields(
    resolved: Sequence[str], *, is_kernel: Any
) -> dict[str, list[str]]:
    axioms = sorted({iri for iri in resolved if is_kernel(iri)})
    shards = sorted({iri for iri in resolved if not is_kernel(iri)})
    return {"depends_on_axioms": axioms, "depends_on_shards": shards}


def build_shard(
    unit: KnowledgeUnit,
    eligible: Eligible,
    *,
    shard_iri: str,
    provenance_hash: str,
    source_uri: str,
    fields: Mapping[str, str],
    framework_id: str,
    bfo_category: str,
    extractor_did: str,
    extractor_model: str,
    extraction_prompt_hash: str,
    confidence: float,
    extracted_at: datetime,
    depends_on: Mapping[str, list[str]] | None = None,
    valid_time_start: datetime | None = None,
    valid_time_end: datetime | None = None,
) -> SimpleAssertionShard:
    """The unsigned shard; ``minting.minter`` adds the ``extract`` signature."""
    import folio_insights

    return SimpleAssertionShard(
        shard_iri=shard_iri,
        provenance_hash=provenance_hash,
        source_uri=source_uri,
        source_span=eligible.verified_span,
        extracted_at=extracted_at,
        first_extractor_did=extractor_did,
        triple=triple_for(unit, eligible),
        sense=fields["sense"],
        reference=fields["reference"],
        logical_form_imputed=fields["logical_form_imputed"],
        layer=fields["layer"],  # type: ignore[arg-type]
        predication_mode=fields["predication_mode"],  # type: ignore[arg-type]
        fork=fields["fork"],  # type: ignore[arg-type]
        epistemic_status=EPISTEMIC_STATUS,
        verification_method=VERIFICATION_METHOD,
        framework_id=framework_id,
        speech_act=fields["speech_act"],  # type: ignore[arg-type]
        extractor_version=folio_insights.__version__,
        extraction_prompt_hash=extraction_prompt_hash,
        extractor_model=extractor_model,
        confidence=max(0.0, min(1.0, round(confidence, 6))),
        bfo_category=bfo_category,  # type: ignore[arg-type]
        valid_time_start=valid_time_start,
        valid_time_end=valid_time_end,
        **(depends_on or {}),
    )


__all__ = [
    "EPISTEMIC_STATUS",
    "MODULE_NS",
    "PREDICATE_BY_UNIT_TYPE",
    "SOURCE_URI_PREFIX",
    "VERIFICATION_METHOD",
    "build_shard",
    "dependency_fields",
    "extract_event_op_id",
    "extractor_model",
    "lineage_template_hashes",
    "mint_op_id",
    "prompt_hash",
    "source_uri_for",
    "triple_for",
    "unit_hash",
]
