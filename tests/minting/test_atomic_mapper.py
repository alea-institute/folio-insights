"""U39 opt-in mapping: full tags, source-grounded identity and subtype gates."""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from folio_insights.minting.eligibility import Eligible, Refused, RunEvidence, evaluate
from folio_insights.minting.mapper import build_shard, mint_op_id, source_uri_for
from folio_insights.models.knowledge_unit import ConceptTag, KnowledgeType, KnowledgeUnit
from folio_insights.shards.minting import atomic_proposition_key, mint_atomic_shard_iri

from tests.minting.conftest import (
    ARB, DAUBERT, SENTENCES, SOURCE, SOURCE_FILE, default_fields, lineage, llm_tag,
    ruler_tag, unit,
)


def atomic_unit(*, kind="procedural_rule", text=None, source_file=SOURCE_FILE):
    data = unit("rule", SENTENCES[0], text=text, unit_type=kind)
    data["source_file"] = data["original_span"]["source_file"] = source_file
    data["provenance"] = {
        "source_snapshot_id": source_file,
        "source_sha256": hashlib.sha256(SOURCE.encode()).hexdigest(),
        "genre": "statutes-regulations",
    }
    data["proposition_kind"] = "citation" if kind == "citation" else "rule"
    return KnowledgeUnit.model_validate(data)


def assess(ku, oracle, **kwargs):
    return evaluate(ku, lambda key: (SOURCE, ""), oracle=oracle, atomic=True, **kwargs)


def mapped(ku, eligible):
    uri = source_uri_for("synthetic", eligible.source_key)
    key = atomic_proposition_key(
        ku.text, *eligible.span_offsets, eligible.source_sha256)
    iri, digest = mint_atomic_shard_iri(uri, eligible.verified_span, key)
    return build_shard(
        ku, eligible, shard_iri=iri, provenance_hash=digest, source_uri=uri,
        fields={k: v["value"] for k, v in default_fields().items()},
        framework_id="us.federal.fre", bfo_category="occurrent_process",
        extractor_did="did:example:extractor", extractor_model="fake:fixture",
        extraction_prompt_hash="a" * 64, confidence=0.9,
        extracted_at=datetime(2026, 10, 26, tzinfo=UTC),
    )


@pytest.mark.parametrize(("kind", "predicate"), [
    ("procedural_rule", "proceduralRule"), ("citation", "citation"),
])
def test_rule_and_citation_map_to_atomic_simple_assertions(oracle, kind, predicate):
    ku = atomic_unit(kind=kind)
    eligible = assess(ku, oracle)
    assert isinstance(eligible, Eligible), eligible
    shard = mapped(ku, eligible)
    assert shard.schema_version == 3 and shard.identity_recipe == "atomic-v1"
    assert shard.shard_type == "simple_assertion"
    assert shard.triple.predicate == (
        "https://folio.openlegalstandard.org/modules/folio-insights/" + predicate)
    assert shard.triple.subject == DAUBERT
    assert shard.triple.object == ku.text
    assert shard.source_span == SOURCE[ku.original_span.start:ku.original_span.end]
    assert shard.atomic_identity.text == ku.text
    assert shard.framework_id == "us.federal.fre"
    assert shard.bfo_category == "occurrent_process"


def test_full_validated_tags_and_provenance_survive_mapping(oracle):
    ku = atomic_unit()
    ku.folio_tags = [
        ConceptTag.model_validate(tag)
        for tag in [ruler_tag(DAUBERT, confidence=0.8), llm_tag(confidence=0.9),
                    ruler_tag(DAUBERT, confidence=0.9),
                    {"iri": "", "label": "unresolved proposal", "confidence": 1.0,
                     "extraction_path": "proposed_class"}]
    ]
    ku.lineage = KnowledgeUnit.model_validate(unit(
        "x", SENTENCES[0], events=lineage(concept=True))).lineage
    eligible = assess(ku, oracle, run=RunEvidence(b9_verified=True))
    assert isinstance(eligible, Eligible), eligible
    shard = mapped(ku, eligible)
    assert [tag.iri for tag in shard.folio_tags] == sorted([ARB, DAUBERT])
    assert shard.triple.subject == min(ARB, DAUBERT)
    assert [tag.model_dump() for tag in shard.folio_tags] == [
        tag.model_dump() for tag in eligible.tags]
    assert next(tag for tag in shard.folio_tags if tag.iri == ARB).judge_status == "judged"
    assert all(tag.branch == "Service" for tag in shard.folio_tags)
    assert all(tag.confidence == 0.9 for tag in shard.folio_tags)


@pytest.mark.parametrize("kind", ["procedural_rule", "citation"])
@pytest.mark.parametrize(("mutation", "code"), [
    ("nonexistent", "iri_nonexistent"), ("wrong_branch", "iri_wrong_branch"),
    ("no_branch", "iri_wrong_branch"), ("unresolved", "no_folio_concept"),
    ("unverified", "iri_unverified"), ("unjudged", "iri_unjudged"),
    ("no_template", "no_prompt_identity"), ("unsupported", "unsupported_specifics"),
    ("snapshot", "anchor_unverified"), ("offsets", "anchor_unverified"),
    ("stored_veto", "anchor_unverified"), ("metadata", "metadata_unit"),
])
def test_atomic_subtypes_retain_eligibility_refusals(oracle, kind, mutation, code):
    ku = atomic_unit(kind=kind)
    if mutation == "nonexistent":
        ku.folio_tags[0].iri = "https://folio.openlegalstandard.org/UNKNOWN"
    elif mutation == "wrong_branch":
        ku.folio_tags[0].branch = "Location"
    elif mutation == "no_branch":
        ku.folio_tags[0].branch = ""
    elif mutation == "unresolved":
        ku.folio_tags[0].iri = ""
    elif mutation == "unverified":
        ku.folio_tags[0].extraction_path = "model_generated"
    elif mutation == "unjudged":
        ku.folio_tags[0].extraction_path = "semantic"
    elif mutation == "no_template":
        ku.lineage[1].template_id = ku.lineage[1].template_hash = None
    elif mutation == "unsupported":
        ku.text = "Rule 26 requires leading questions on cross-examination."
    elif mutation == "snapshot":
        ku.provenance = ku.provenance.model_copy(update={"source_sha256": "0" * 64})
    elif mutation == "offsets":
        ku.original_span.start += 1
    elif mutation == "stored_veto":
        ku.anchor_score, ku.anchor_verified = 0.7, False
    elif mutation == "metadata":
        ku.lineage.append(ku.lineage[0].model_copy(update={
            "stage": "folio_tagger", "action": "skip"}))
    outcome = assess(ku, oracle, run=RunEvidence(b9_verified=True))
    assert isinstance(outcome, Refused) and outcome.code == code, outcome


@pytest.mark.parametrize("kind", ["procedural_rule", "citation"])
def test_atomic_source_is_independently_read_and_required(oracle, kind):
    ku = atomic_unit(kind=kind)
    missing = evaluate(ku, lambda key: (None, "absent"), oracle=oracle, atomic=True)
    assert isinstance(missing, Refused) and missing.code == "source_unavailable"
    changed = evaluate(ku, lambda key: (SOURCE + "changed", ""), oracle=oracle, atomic=True)
    assert isinstance(changed, Refused) and changed.code == "anchor_unverified"


def test_atomic_dedup_preserves_claims_documents_and_occurrences(oracle):
    seen = set()
    first = atomic_unit(text="Ask only leading questions on cross-examination.")
    second = atomic_unit(text="The witness can do nothing but agree.")
    other_doc = atomic_unit(text=first.text, source_file="other.txt")
    shards = []
    for ku in [first, second, other_doc]:
        eligible = assess(ku, oracle, seen=seen)
        assert isinstance(eligible, Eligible), eligible
        shards.append(mapped(ku, eligible))
    assert len({s.shard_iri for s in shards}) == 3
    duplicate = assess(first, oracle, seen=seen)
    assert isinstance(duplicate, Refused) and duplicate.code == "duplicate_in_run"
    # Run operation IDs must distinguish claims even with a stale content_hash.
    a, b = assess(first, oracle), assess(second, oracle)
    assert mint_op_id("run", a, first) != mint_op_id("run", b, second)


def test_equal_text_at_distinct_offsets_is_not_an_atomic_duplicate(oracle):
    source = SOURCE + SOURCE
    seen = set()
    shards = []
    for shift in [0, len(SOURCE)]:
        ku = atomic_unit()
        ku.original_span.start += shift
        ku.original_span.end += shift
        ku.provenance = ku.provenance.model_copy(update={
            "source_sha256": hashlib.sha256(source.encode()).hexdigest()})
        eligible = evaluate(ku, lambda key: (source, ""), oracle=oracle, atomic=True, seen=seen)
        assert isinstance(eligible, Eligible), eligible
        shards.append(mapped(ku, eligible))
    assert shards[0].shard_iri != shards[1].shard_iri


def test_atomic_behavior_is_explicitly_default_off(oracle):
    ku = atomic_unit()
    refused = evaluate(ku, lambda key: (SOURCE, ""), oracle=oracle)
    assert isinstance(refused, Refused) and refused.code == "unit_type_unsupported"
    ku.unit_type = KnowledgeType.ADVICE
    eligible = evaluate(ku, lambda key: (SOURCE, ""), oracle=oracle)
    assert isinstance(eligible, Eligible)
    from folio_insights.shards.minting import mint_shard_iri

    uri = source_uri_for("synthetic", eligible.source_key)
    iri, digest = mint_shard_iri(uri, eligible.verified_span)
    shard = build_shard(
        ku, eligible, shard_iri=iri, provenance_hash=digest, source_uri=uri,
        fields={k: v["value"] for k, v in default_fields().items()},
        framework_id="us.federal.fre", bfo_category="occurrent_process",
        extractor_did="did:example:extractor", extractor_model="fake:fixture",
        extraction_prompt_hash="a" * 64, confidence=0.9,
        extracted_at=datetime(2026, 10, 26, tzinfo=UTC),
    )
    assert shard.schema_version == 2
    assert "folio_tags" not in shard.model_dump()


def test_atomic_mapping_retains_every_valid_branch_and_has_stable_order(oracle):
    ku = atomic_unit()
    iri = "https://folio.openlegalstandard.org/RCz1SYWoNDDTDvPr0kSJBq"
    ku.folio_tags = [ConceptTag.model_validate(ruler_tag(iri, branch=branch))
                    for branch in ["Service", "Event"]]
    first = assess(ku, oracle)
    ku.folio_tags.reverse()
    second = assess(ku, oracle)
    assert isinstance(first, Eligible) and isinstance(second, Eligible)
    assert [tag.branch for tag in mapped(ku, first).folio_tags] == ["Event", "Service"]
    assert mapped(ku, first).folio_tags == mapped(ku, second).folio_tags


@pytest.mark.parametrize("kind", ["procedural_rule", "citation"])
async def test_atomic_subtypes_use_original_visibility_framework_fields_and_bfo_gates(
    tmp_path, oracle, provider, kind,
):
    from folio_insights.frameworks.detector import FrameworkDetector, SourceMetadata
    from folio_insights.minting.fields import (
        OracleBranchResolver, classify_bfo, detect_framework, infer_fields, strict_classifier,
    )
    from folio_insights.minting.minter import MintRefused, check_visibility
    from folio_insights.models.framework import FrameworkRegistry

    ku = atomic_unit(kind=kind)
    eligible = assess(ku, oracle)
    assert isinstance(eligible, Eligible)
    with pytest.raises(MintRefused, match="non-public sources"):
        check_visibility(tmp_path, "synthetic", "non-public")
    check_visibility(tmp_path, "synthetic", "public")

    detector = FrameworkDetector(FrameworkRegistry.with_defaults())
    _, refusal = await detect_framework(detector, SourceMetadata(title=SOURCE_FILE))
    assert isinstance(refusal, Refused) and refusal.code == "framework_unconfident"
    detected, refusal = await detect_framework(
        detector, SourceMetadata(framework_id="us.federal.fre"))
    assert refusal is None and detected.framework_id == "us.federal.fre"

    refusal = await infer_fields(ku, eligible, port=None)
    assert isinstance(refusal, Refused) and refusal.code == "field_inference_unavailable"
    fields = await infer_fields(ku, eligible, port=provider.port(), context=provider.context())
    assert not isinstance(fields, Refused)
    provider.fields = lambda body: default_fields(sense={"value": "supported", "confidence": 0.1})
    refusal = await infer_fields(ku, eligible, port=provider.port(), context=provider.context())
    assert isinstance(refusal, Refused) and refusal.code == "field_low_confidence:sense"

    refusal = await classify_bfo(strict_classifier(resolver=None), eligible,
                                  fields.values["speech_act"], subject=ku.text)
    assert isinstance(refusal, Refused) and refusal.code == "bfo_unclassifiable"
    bfo = await classify_bfo(strict_classifier(resolver=OracleBranchResolver(oracle)),
                             eligible, fields.values["speech_act"], subject=ku.text)
    assert not isinstance(bfo, Refused) and bfo.category == "occurrent_process"
