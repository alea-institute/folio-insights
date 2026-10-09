"""propositions_to_shards: grouping, type preservation, refusals, field defaults."""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
from folio_propositions import WORKING_TAXONOMY

from folio_insights.bridge_ingest import (
    ContentIriMismatch,
    InvalidExtractorDid,
    MissingSourceUri,
    load_record,
    propositions_to_shards,
)
from folio_insights.bridge_ingest.errors import InvalidRecord
from folio_insights.bridge_ingest.mapping import SPEECH_ACT_BY_ROLE, type_reference
from folio_insights.shards import HypothesisShard, dump_shard_record, load_shard_record
from folio_insights.shards.minting import mint_shard_iri
from tests.bridge_ingest.conftest import SOURCE_URI, make_record, proposition

NOW = datetime(2026, 10, 9, 8, 0, tzinfo=UTC)
SPAN = "A carrier may limit liability only with a fair opportunity to choose."


def _map(record, **kw):
    return propositions_to_shards(
        record, framework_id="us.case-law.unspecified",
        extractor_did="did:web:folio-enrich.local", now=NOW, **kw,
    )


def test_one_shard_per_span_keeps_every_type() -> None:
    record = make_record(
        proposition("p1", SPAN, "Judicial Legal Conclusion"),
        proposition("p2", SPAN, "cited-authority proposition"),
        proposition("p3", "We find the cargo was damaged.", "Judicial Finding of Fact"),
    )
    result = _map(record)
    assert len(result.shards) == 2
    iri = mint_shard_iri(SOURCE_URI, SPAN)[0]
    shard = next(s for s in result.shards if s.shard_iri == iri)
    assert shard.logical_form_imputed == (
        "PROPOSITION_TYPES(Judicial Legal Conclusion | cited-authority proposition)"
    )
    entry = next(e for e in result.manifest if e.iri == iri)
    assert {s.proposition_id for s in entry.sources} == {"p1", "p2"}
    assert {s.proposition_type for s in entry.sources} == {
        "Judicial Legal Conclusion", "cited-authority proposition",
    }


def test_spans_differing_only_in_whitespace_share_a_shard() -> None:
    record = make_record(
        proposition("p1", SPAN, "Judicial Legal Conclusion"),
        proposition("p2", "  " + SPAN + "\r\n", "Legal Proposition", role="plaintiff"),
    )
    assert len(_map(record).shards) == 1


def test_field_defaults() -> None:
    record = make_record(proposition("p1", SPAN, "Judicial Legal Conclusion", individual_id="court:x"))
    shard = _map(record).shards[0]
    iri, provenance_hash = mint_shard_iri(SOURCE_URI, SPAN)
    assert isinstance(shard, HypothesisShard)
    assert (shard.shard_iri, shard.provenance_hash) == (iri, provenance_hash)
    assert shard.source_uri == SOURCE_URI and shard.source_span == SPAN
    assert shard.extracted_at == NOW
    assert shard.first_extractor_did == "did:web:folio-enrich.local"
    assert shard.epistemic_status == "hypothesis"
    assert shard.generation_method == "inductive"
    assert shard.verification_method == "extractor_assertion"
    assert shard.predication_mode == "per_accidens"
    assert shard.fork == "synthetic_a_posteriori"
    assert shard.layer == "L3_jurisdictional"
    assert shard.bfo_category == "continuant_dependent"
    assert shard.confidence == 0.5
    assert shard.ttl_days == 90
    assert shard.triple.subject == "court:x"
    assert shard.triple.predicate == "Judicial Legal Conclusion"
    assert shard.triple.object == SPAN
    assert shard.sense == SPAN
    assert shard.reference == WORKING_TAXONOMY["Judicial Legal Conclusion"]
    assert shard.framework_id == "us.case-law.unspecified"
    assert shard.extractor_version == "9.9.9-test"
    assert shard.extractor_model == "folio-enrich"
    assert shard.extraction_prompt_hash == hashlib.sha256(b"folio-enrich|9.9.9-test|lex-1").hexdigest()
    assert shard.depends_on_precedents == []


def test_reference_for_type_without_folio_iri() -> None:
    assert type_reference("cited-authority proposition") == (
        "urn:folio-propositions:type/cited-authority-proposition"
    )
    assert type_reference("Judicial Finding of Fact") == WORKING_TAXONOMY["Judicial Finding of Fact"]


def test_metadata_timestamp_wins_over_now() -> None:
    record = make_record(
        proposition("p1", SPAN), metadata={"exported_at": "2026-01-02T03:04:05Z"}
    )
    assert _map(record).shards[0].extracted_at == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        ("court", "holding"),
        ("secondary_source", "treatise_statement"),
        ("party", "pleading_argument"),
        ("plaintiff", "pleading_argument"),
        ("defendant", "pleading_argument"),
        ("appellant", "pleading_argument"),
        ("appellee", "pleading_argument"),
        ("petitioner", "pleading_argument"),
        ("respondent", "pleading_argument"),
        ("both_parties", "pleading_argument"),
        ("system", "dictum"),
        (None, "dictum"),
    ],
)
def test_speech_act_table(role, expected) -> None:
    shard = _map(make_record(proposition("p1", SPAN, role=role))).shards[0]
    assert shard.speech_act == expected
    assert SPEECH_ACT_BY_ROLE[role] == expected
    if role is None:
        assert shard.triple.subject == "unknown"
    else:
        assert shard.triple.subject == f"role:{role}"


def test_speech_act_from_first_type_sorted() -> None:
    record = make_record(
        proposition("p1", SPAN, "Legal Proposition", role="plaintiff"),
        proposition("p2", SPAN, "Judicial Legal Conclusion", role="court"),
    )
    # "Judicial Legal Conclusion" < "Legal Proposition": the court's view leads.
    assert _map(record).shards[0].speech_act == "holding"


def test_content_iri_mismatch_refuses_record() -> None:
    record = make_record(proposition("p1", SPAN))
    bad = record.propositions[0].model_copy(update={"content_iri": "urn:folio:shard/" + "0" * 32})
    tampered = record.model_copy(update={"propositions": [bad]})
    with pytest.raises(ContentIriMismatch) as info:
        _map(tampered)
    assert info.value.proposition_id == "p1"
    # The loader refuses the same record with the specific error, too.
    data = tampered.model_dump(mode="json")
    with pytest.raises(ContentIriMismatch):
        load_record(data)


def test_missing_source_uri_refused() -> None:
    record = make_record(proposition("p1", SPAN), source_uri=None)
    with pytest.raises(MissingSourceUri):
        _map(record)


def test_invalid_extractor_did_refused() -> None:
    with pytest.raises(InvalidExtractorDid):
        propositions_to_shards(make_record(proposition("p1", SPAN)), extractor_did="not-a-did")


def test_textless_propositions_skipped() -> None:
    record = make_record(proposition("p1", SPAN), proposition("p2", None, "policy proposition"))
    result = _map(record)
    assert [s.proposition_id for s in result.skipped] == ["p2"]
    assert result.skipped[0].reason == "no text"
    assert len(result.shards) == 1


def test_unstamped_record_is_minted() -> None:
    record = make_record(proposition("p1", SPAN), stamp=False)
    assert record.propositions[0].content_iri is None
    assert _map(record).shards[0].shard_iri == mint_shard_iri(SOURCE_URI, SPAN)[0]


def test_every_shard_round_trips(fixture_shards) -> None:
    for shard in fixture_shards:
        loaded = load_shard_record(dump_shard_record(shard)).shard
        assert loaded == shard


def test_every_shard_passes_the_shacl_suite(fixture_shards) -> None:
    from folio_insights.shapes import default_suite

    suite = default_suite()
    for shard in fixture_shards:
        report = suite.validate_shard(shard)
        assert report.conforms, report.violations


def test_older_schema_record_migrates() -> None:
    record = make_record(proposition("p1", SPAN), stamp=False)
    data = record.model_dump(mode="json")
    data["schema_version"] = 3
    for p in data["propositions"]:
        p["schema_version"] = 3
        p.pop("axiom_history")
        p.pop("content_iri")
    loaded = load_record(data)
    assert loaded.record.schema_version == 4


def test_ndjson_form_loads_same_record() -> None:
    import json

    record = make_record(proposition("p1", SPAN), proposition("p2", "Other span."))
    data = record.model_dump(mode="json")
    props = data.pop("propositions")
    lines = [json.dumps({"record_type": "proposition_document", **data})]
    lines += [json.dumps({"record_type": "proposition", **p}) for p in props]
    loaded = load_record("\n".join(lines) + "\n", ndjson=True)
    assert loaded.record == record
    assert loaded.sha256 == load_record(record).sha256


def test_garbage_refused_as_invalid_record() -> None:
    with pytest.raises(InvalidRecord):
        load_record(b"{not json", ndjson=False)
    with pytest.raises(InvalidRecord):
        load_record({"document_id": "d", "propositions": [{"id": 1}]})


@pytest.fixture
def fixture_shards():
    from tests.bridge_ingest.conftest import fixture_record_dict

    return _map(load_record(fixture_record_dict()).record).shards
