"""Phase 11 review findings, shapes side (each test failed before its fix).

* P2-1: the compiled engine reproduces pyshacl's ordering on naive vs aware
  dateTimes, NaN, infinities and bool-as-number. Naive timestamps are read as
  UTC in the validation rendering only; the shard model, its serialization,
  ``canonical_content_hash`` and existing signatures are byte-identical to
  origin/master.
* P2-4: implicit ``owl:Class`` targets, custom constraint components,
  malformed counts and unknown regex flags are refused at compile time.
  ``sh:deactivated`` is honoured on shapes (``true`` or ``1``) and on
  ``sh:sparql`` constraints.
* Renderer nits: a camelCase alias of a declared field and a null-valued
  undeclared key are both reported as undeclared, and a non-string
  ``shard_type`` renders without crashing.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pyoxigraph import RdfFormat, Store
from rdflib import Graph

from folio_insights.shapes import pyshacl_adapter
from folio_insights.shapes.compiled import CompiledSuite, UnsupportedShaclConstruct, turtle_graph
from folio_insights.shapes.corpus import run_constraints, store_query
from folio_insights.shapes import rendering
from folio_insights.shapes.rendering import render_shard
from folio_insights.shapes.suite import SUITE_PATHS, default_suite
from folio_insights.shards import dump_shard_record, load_shard_record
from folio_insights.storage.errors import ShaclViolation
from tests.shapes.cases import dumped, mutate

SH = "http://www.w3.org/ns/shacl#"


def _agree(data: dict) -> set:
    graph, _ = render_shard(data)
    ours = {(r.focus, r.path, r.component, r.severity) for r in default_suite().compiled.validate(graph)}
    ref = {
        (r["focus"], r["path"], r["component"].removeprefix(SH), r["severity"].removeprefix(SH))
        for r in pyshacl_adapter.validate(graph, SUITE_PATHS).results
    }
    assert ours == ref
    return ours


@pytest.mark.parametrize(
    "change",
    [
        {"valid_time_start": "2026-01-01T00:00:00", "valid_time_end": "2027-01-01T00:00:00Z"},
        {"valid_time_start": "2027-01-01T00:00:00", "valid_time_end": "2026-01-01T00:00:00Z"},
        {"valid_time_start": "2026-01-01T05:00:00Z", "valid_time_end": "2026-01-01T03:00:00"},
        {"valid_time_start": "2026-01-01T00:00:00", "valid_time_end": "2026-01-01T00:00:00"},
        {"confidence": float("nan")},
        {"confidence": float("inf")},
        {"confidence": float("-inf")},
        {"confidence": True},
        {"confidence": False},
        {"ttl_days": True},
        {"confidence": 10**30},
    ],
    ids=lambda c: "-".join(f"{k}={v}" for k, v in c.items()),
)
def test_engines_agree_on_exotic_values(change: dict) -> None:
    _agree(mutate(dumped(), **change))


# A record with naive valid-time bounds (and a naive extracted_at /
# transaction_time). The two digests below were computed with the
# origin/master code (git archive origin/master src): the shard model, its
# serialization and canonical_content_hash must stay byte-identical, because
# stored records and their signatures depend on them (U17/R18).
NAIVE_RECORD = {
    "shard_type": "simple_assertion", "shard_iri": "urn:folio:shard/0123456789abcdef0123456789abcdef",
    "provenance_hash": "0" * 64, "source_uri": "urn:x:s", "source_span": "span",
    "extracted_at": "2026-01-01T00:00:00", "first_extractor_did": "did:key:zX",
    "triple": {"subject": "s", "predicate": "p", "object": "o"}, "sense": "s", "reference": "r",
    "logical_form_imputed": "P", "layer": "L1_definitional", "predication_mode": "per_se",
    "fork": "analytic", "epistemic_status": "authority_only",
    "verification_method": "textual_citation", "framework_id": "f", "speech_act": "holding",
    "extractor_version": "1", "extraction_prompt_hash": "0" * 64, "extractor_model": "m",
    "confidence": 0.5, "bfo_category": "continuant_independent",
    "transaction_time": "2026-01-02T00:00:00",
    "valid_time_start": "2026-01-01T00:00:00", "valid_time_end": "2027-01-01T00:00:00Z",
    "supersedes": None, "superseded_by": None,
}
MASTER_CONTENT_HASH = "5770b0318cfa404e7d2d7f9d8ae2214ea8e0ef2d502748efafd77ffa4111013a"
MASTER_RECORD_SHA256 = "93ea860ce40402bf75cfb3c08ab95ac6258e4ae11f4c91ed306b49558b3b9f67"


def test_naive_bounds_leave_model_bytes_and_hash_identical_to_master() -> None:
    import hashlib

    from folio_insights.revision.content_edit import canonical_content_hash

    shard = load_shard_record(json.dumps(NAIVE_RECORD).encode()).shard
    assert shard.valid_time_start.tzinfo is None  # the model keeps naive input naive
    record = dump_shard_record(shard)
    assert hashlib.sha256(record).hexdigest() == MASTER_RECORD_SHA256
    assert json.loads(record)["valid_time_start"] == "2026-01-01T00:00:00"
    assert canonical_content_hash(shard) == MASTER_CONTENT_HASH


async def test_signature_over_a_naive_record_still_verifies() -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from folio_insights.identity.cache import InMemoryDidDocCache
    from folio_insights.identity.signer import sign_attestation
    from folio_insights.identity.verifier import verify_attestation
    from folio_insights.revision.content_edit import canonical_content_hash
    from tests.storage.conftest import _did_for

    sk = Ed25519PrivateKey.generate()
    did = _did_for(sk)
    # Signed over the master-era hash of the stored naive record...
    sig = sign_attestation(
        MASTER_CONTENT_HASH, sk, did, "extract",
        signing_key_id=f"{did}#{did.removeprefix('did:key:')}",
        did_doc_snapshot_at=None, now=datetime(2026, 3, 1, tzinfo=UTC),
    )
    # ...and verified against the record as this code loads it.
    reloaded = load_shard_record(json.dumps(NAIVE_RECORD).encode()).shard
    assert await verify_attestation(reloaded, sig, cache=InMemoryDidDocCache())
    assert canonical_content_hash(reloaded) == sig.over_content_hash == MASTER_CONTENT_HASH


@pytest.mark.parametrize(
    "start,end,accepted",
    [
        ("2026-01-01T00:00:00", "2027-01-01T00:00:00Z", True),
        ("2027-01-01T00:00:00", "2026-01-01T00:00:00Z", False),
        ("2026-01-01T05:00:00Z", "2026-01-01T03:00:00", False),
        ("2026-01-01T03:00:00Z", "2026-01-01T05:00:00", True),
        ("2026-01-01T00:00:00", "2026-01-01T00:00:00Z", False),
        ("2026-01-01T00:00:00", "2026-06-01T00:00:00", True),
    ],
)
def test_naive_aware_writes_are_judged_identically_by_both_engines(
    start: str, end: str, accepted: bool
) -> None:
    from folio_insights.storage.shacl_status import check_shard_payload

    loaded = load_shard_record(json.dumps(mutate(dumped(), valid_time_start=start, valid_time_end=end)).encode())
    payload = dump_shard_record(loaded.shard)
    assert json.loads(payload)["valid_time_start"] == start  # stored bytes keep the input form
    try:
        check_shard_payload(payload, default_suite())
        compiled_accepts = True
    except ShaclViolation:
        compiled_accepts = False
    graph, _ = render_shard(json.loads(payload))
    reference = pyshacl_adapter.validate(graph, SUITE_PATHS)
    assert compiled_accepts is reference.conforms is accepted
    _agree(json.loads(payload))


def test_renderer_reads_naive_datetimes_as_utc_and_keeps_others() -> None:
    from folio_insights.shapes.rendering import utc_datetime_lexical

    assert utc_datetime_lexical("2026-01-01T00:00:00") == "2026-01-01T00:00:00+00:00"
    assert utc_datetime_lexical("2026-01-01T00:00:00Z") == "2026-01-01T00:00:00Z"
    assert utc_datetime_lexical("2026-01-01T05:00:00+05:00") == "2026-01-01T05:00:00+05:00"
    assert utc_datetime_lexical("not-a-time") == "not-a-time"
    assert utc_datetime_lexical("") == ""


H = (
    "@prefix sh: <http://www.w3.org/ns/shacl#> . @prefix ex: <http://ex/> . "
    "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> . @prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
)


@pytest.mark.parametrize(
    "ttl",
    [
        "ex:S a sh:NodeShape, owl:Class ; sh:property [ sh:path ex:q ; sh:minCount 1 ] .",
        "ex:CC a sh:ConstraintComponent ; sh:parameter [ sh:path ex:needsQ ] ; "
        "sh:validator [ a sh:SPARQLAskValidator ; sh:ask \"ASK { $this <http://ex/q> ?x }\" ] . "
        "ex:S a sh:NodeShape ; sh:targetClass ex:C ; ex:needsQ true .",
        "ex:S a sh:NodeShape ; sh:targetClass ex:C ; sh:property [ sh:path ex:p ; sh:minCount 1.0 ] .",
        "ex:S a sh:NodeShape ; sh:targetClass ex:C ; sh:property [ sh:path ex:p ; sh:pattern \"a\" ; sh:flags \"q\" ] .",
        "ex:S a sh:NodeShape ; sh:targetClass ex:C ; sh:sparql [ sh:select \"SELECT $this WHERE {}\" ; sh:ask \"ASK {}\" ] .",
    ],
    ids=["owl_class_implicit", "custom_component", "decimal_min_count", "unknown_flag", "sparql_extra_term"],
)
def test_unsupported_shacl_refuses_to_compile(tmp_path: Path, ttl: str) -> None:
    path = tmp_path / "s.ttl"
    path.write_text(H + ttl)
    with pytest.raises(UnsupportedShaclConstruct):
        CompiledSuite([path])


def test_deactivated_shapes_and_sparql_constraints_are_skipped_like_pyshacl(tmp_path: Path) -> None:
    path = tmp_path / "d.ttl"
    path.write_text(H + (
        'ex:S a sh:NodeShape ; sh:targetClass ex:C ; sh:deactivated "1"^^xsd:boolean ; '
        "sh:property [ sh:path ex:missing ; sh:minCount 1 ] .\n"
        "ex:T a sh:NodeShape ; sh:targetClass ex:C ; "
        'sh:sparql [ sh:select "SELECT $this WHERE { $this ?p ?o }" ; sh:deactivated true ] , '
        '[ sh:select "SELECT $this WHERE { $this <http://ex/p> ?o }" ] .\n'
    ))
    data = "@prefix ex: <http://ex/> . ex:a a ex:C ; ex:p \"x\" ."
    suite = CompiledSuite([path])
    assert suite.validate(turtle_graph(data)) == []
    assert len(suite.sparql) == 1  # the deactivated sh:sparql constraint is dropped
    store = Store()
    store.load(data.encode(), format=RdfFormat.TURTLE)
    ours = run_constraints(store_query(store), suite.sparql)
    ref = pyshacl_adapter.validate(Graph().parse(data=data, format="turtle"), [path], local_only=False)
    assert {r.focus[1] for r in ours} == {r["focus"][1] for r in ref.results} == {"http://ex/a"}


def test_camel_case_alias_and_null_undeclared_keys_are_reported() -> None:
    alias = dumped()
    alias["sourceSpan"] = alias.pop("source_span")
    alias["bogus"] = None
    graph, _ = render_shard(alias)
    results = default_suite().compiled.validate(graph)
    closed = {r.path for r in results if r.component == "ClosedConstraintComponent"}
    ns = rendering.UNDECLARED_NS
    assert closed == {f"{ns}sourceSpan", f"{ns}bogus"}
    assert any(r.component == "MinCountConstraintComponent" and r.path.endswith("/sourceSpan")
               for r in results)  # the real field is still missing
    _agree(alias)


@pytest.mark.parametrize("tag", [[], {}, 7, None])
def test_non_string_shard_type_renders(tag: object) -> None:
    graph, _ = render_shard({"shard_type": tag, "sense": "x"})
    assert graph.nodes
