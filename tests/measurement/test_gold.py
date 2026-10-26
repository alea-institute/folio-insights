"""Atomic synthetic gold is source-grounded and independently ontology-pinned."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from folio_insights.measurement.gold import (
    DEFAULT_GOLD_DIR,
    GoldSetError,
    OntologySnapshot,
    PinnedOntology,
    load_gold,
    load_ontology,
    validate_gold,
)
from folio_insights.measurement.schema import EvaluationInputs, GoldSuite, SupportingSpan

ROOT = Path(__file__).resolve().parents[2]
GOLD = ROOT / DEFAULT_GOLD_DIR


def raw_suite(name: str = "readme") -> dict:
    return json.loads((GOLD / f"{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("key", ["quote", "snippet", "excerpt", "passage", "source_text"])
@pytest.mark.parametrize("value", ["invented support", "", None])
def test_spans_reject_serialized_excerpt_fields(key: str, value: str | None) -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        SupportingSpan.model_validate({"start": 0, "end": 1, key: value})


@pytest.mark.parametrize("name", ["readme", "evaluation"])
def test_gold_round_trip_stores_offsets_only_and_derives_support(name: str) -> None:
    data = raw_suite(name)
    suite = load_gold(GOLD / f"{name}.json")
    assert json.loads(suite.model_dump_json()) == data
    for doc, serialized in zip(suite.documents, data["documents"], strict=True):
        for prop, stored in zip(doc.propositions, serialized["propositions"], strict=True):
            assert stored["span"] == {"start": prop.span.start, "end": prop.span.end}
            assert prop.span.source_slice(doc.source.text) == (
                doc.source.text[prop.span.start:prop.span.end]
            )


def test_source_slices_use_unicode_code_points_without_normalizing() -> None:
    data = raw_suite()
    doc = data["documents"][0]
    doc["source"]["text"] = "🦉 Café e\u0301. Fin."
    doc["source"]["sha256"] = hashlib.sha256(doc["source"]["text"].encode()).hexdigest()
    for prop in doc["propositions"]:
        prop["span"] = {"start": 2, "end": 10}
    loaded = GoldSuite.model_validate(data).documents[0]
    for prop in loaded.propositions:
        assert prop.span.source_slice(loaded.source.text) == "Café e\u0301."


def test_contract_rule_and_three_elements_have_complete_support() -> None:
    doc = load_gold().documents[0]
    rule = next(p for p in doc.propositions if p.item_id == "contract-rule")
    elements = [p for p in doc.propositions if any(
        link.relation == "condition-of" and link.target_id == rule.item_id for link in p.links
    )]
    assert rule.kind == "rule"
    assert [p.kind for p in elements] == ["element"] * 3
    assert [p.text for p in elements] == [
        "The plaintiff must prove the formation of a contract.",
        "The plaintiff must prove its performance of any conditions precedent.",
        "The plaintiff must prove the defendant's breach.",
    ]
    sentence = doc.source.text.split(". ", 1)[0] + "."
    assert rule.span.source_slice(doc.source.text) == sentence
    for item in [rule, *elements]:
        assert item.span.source_slice(doc.source.text) == sentence


def test_eight_readme_ids_and_verbatim_sources() -> None:
    suite = load_gold()
    assert Counter(d.source.example_id for d in suite.documents) == Counter(range(1, 9))
    blocks = re.findall(r"<details(?: open)?>(.*?)</details>",
                        (ROOT / "README.md").read_text(encoding="utf-8"), re.S)
    for doc, block in zip(suite.documents, blocks, strict=True):
        quotes = [line[2:] for line in block.splitlines() if line.startswith("> ")]
        assert doc.source.title == quotes[0]
        assert doc.source.text == "\n".join(quotes[1:])
        assert doc.source.sha256 == hashlib.sha256(doc.source.text.encode()).hexdigest()
    assert [d.source.genre for d in suite.documents] == [
        "opinions", "briefs", "know-how", "know-how", "statutes-regulations",
        "know-how", "know-how", "know-how",
    ]
    assert suite.documents[5].source.subgenre == "jury-instruction-reference"
    assert all(d.source.synthetic and d.source.partition == "tuning" for d in suite.documents)


def test_every_tag_resolves_to_recorded_class_and_actual_ancestor() -> None:
    ontology = load_ontology()
    assert ontology.source_sha256 == (
        "b6ed82e6d17b7cb1d468453e4111ec08ca091d72a6849be2b58dd37692cb6ef9"
    )
    for name in ("readme", "evaluation"):
        suite = load_gold(GOLD / f"{name}.json")
        assert suite.ontology_sha256 == ontology.source_sha256
        for doc in suite.documents:
            for item in doc.propositions:
                assert item.tags
                for tag in item.tags:
                    resolved = ontology.resolve(tag.label, tag.branch)
                    assert resolved.iri.startswith("https://folio.openlegalstandard.org/")
                    assert resolved.ancestor_path[0] == resolved.iri
                    assert resolved.ancestor_path[-1] == resolved.branch_iri
                    for child, parent in zip(resolved.ancestor_path, resolved.ancestor_path[1:]):
                        assert parent in ontology.concepts[child].parents
    obligation = ontology.resolve("Obligation", "Deontic Specification")
    assert obligation.branch_iri.endswith("RClhbl4E1TJp9LygIXewIhn")
    assert ontology.resolve("Duty", "Deontic Specification").iri == obligation.iri
    with pytest.raises(GoldSetError, match="ancestor"):
        ontology.resolve("Obligation", "Area of Law")
    with pytest.raises(GoldSetError, match="unknown"):
        ontology.resolve("Imaginary Legal Concept", "Area of Law")


def test_resolution_prefers_canonical_labels_and_rejects_ambiguous_aliases() -> None:
    data = json.loads((GOLD / "ontology.json").read_text(encoding="utf-8"))
    for concept in data["concepts"]:
        if concept["label"] in {"Obligation", "Permission"}:
            concept["alternative_labels"].append("shared-test-alias")
        if concept["label"] == "Permission":
            concept["alternative_labels"].append("Obligation")
    # A fake label collision tests resolution policy without changing recorded gold.
    ontology = PinnedOntology(OntologySnapshot.model_validate(data))
    assert ontology.resolve("obligation", "Deontic Specification").iri.endswith(
        "RDtFkLR3v97fran5zQ3ugao"
    )
    with pytest.raises(GoldSetError, match="ambiguous"):
        ontology.resolve("shared-test-alias", "Deontic Specification")


def test_independent_evaluation_groups_cover_four_genres_twice() -> None:
    public = load_gold()
    evaluation = load_gold(GOLD / "evaluation.json")
    assert len(evaluation.documents) == 8
    assert len({d.source.group_id for d in evaluation.documents}) == 8
    assert Counter(d.source.genre for d in evaluation.documents) == {
        "opinions": 2, "briefs": 2, "statutes-regulations": 2, "know-how": 2,
    }
    public_groups = {d.source.group_id for d in public.documents}
    for doc in evaluation.documents:
        assert doc.source.group_id not in public_groups
        assert doc.source.example_id is None
        assert doc.source.synthetic and doc.source.partition == "evaluation-candidate"
        assert doc.source.text not in {d.source.text for d in public.documents}
        # An evaluation excerpt must not simply repackage any README sentence.
        for sentence in re.split(r"(?<=[.!?])\s+", doc.source.text):
            assert all(sentence not in p.source.text for p in public.documents)


def test_repeated_text_keeps_distinct_occurrence_offsets() -> None:
    doc = next(d for d in load_gold(GOLD / "evaluation.json").documents
               if d.source.source_id == "evaluation-know-how-02")
    repeated = [p for p in doc.propositions
                if p.span.source_slice(doc.source.text) == "Record the answer."]
    assert len(repeated) == 2
    assert repeated[0].text == repeated[1].text
    assert repeated[0].span.start != repeated[1].span.start
    assert len({p.item_id for p in repeated}) == 2


def test_distinct_atomic_claims_can_share_one_supporting_span() -> None:
    doc = load_gold().documents[0]
    claims = [p for p in doc.propositions if p.item_id.startswith("contract-")]
    assert len(claims) == 4
    assert len({(p.span.start, p.span.end) for p in claims}) == 1
    assert len({p.text for p in claims}) == 4
    assert len({p.item_id for p in claims}) == 4


def test_exceptions_penalties_and_negligence_elements_are_separate() -> None:
    docs = load_gold().documents
    statute = docs[4]
    delay = next(p for p in statute.propositions if p.item_id == "notice-delay")
    assert {t.label for t in delay.tags} >= {"Permission", "Exception", "Privacy Law"}
    assert [(link.relation, link.target_id) for link in delay.links] == [
        ("exception-to", "notice-duty")
    ]
    penalty = next(p for p in statute.propositions if p.kind == "penalty")
    assert [(link.relation, link.target_id) for link in penalty.links] == [
        ("penalty-for", "notice-duty")
    ]
    negligence = docs[5]
    assert len([p for p in negligence.propositions if p.kind == "element"]) == 2
    assert len([p for p in docs[6].propositions if p.item_id.startswith("cap-exception-")]) == 3
    assert any(p.kind == "citation" for p in docs[1].propositions)
    assert any(link.relation == "cites" for p in docs[1].propositions for link in p.links)


@pytest.mark.parametrize("mutation, message", [
    ("start-bounds", "slice"), ("bounds", "span"), ("link", "target"),
    ("negative", "span"), ("reversed", "span"), ("empty-span", "span"),
    ("cross-document-link", "target"),
    ("self-link", "self"), ("duplicate-item", "duplicate"),
    ("duplicate-source", "duplicate"), ("duplicate-example", "duplicate"),
    ("source-hash", "digest"), ("ontology-hash", "ontology"),
    ("unknown-tag", "unknown"), ("wrong-branch", "ancestor"),
])
def test_invalid_fixtures_fail_validation(mutation: str, message: str) -> None:
    data = raw_suite()
    doc = data["documents"][0]
    prop = doc["propositions"][0]
    if mutation == "start-bounds":
        prop["span"] = {"start": len(doc["source"]["text"]) + 1,
                        "end": len(doc["source"]["text"]) + 2}
    elif mutation == "bounds":
        prop["span"]["end"] = len(doc["source"]["text"]) + 1
    elif mutation == "negative":
        prop["span"]["start"] = -1
    elif mutation == "reversed":
        prop["span"]["start"] = prop["span"]["end"]
    elif mutation == "empty-span":
        prop["span"] = {"start": 0, "end": 0}
    elif mutation == "cross-document-link":
        prop["links"] = [{"relation": "cites", "target_id":
                          data["documents"][1]["propositions"][0]["item_id"]}]
    elif mutation in {"link", "self-link"}:
        prop["links"] = [{"relation": "condition-of", "target_id":
                          "absent" if mutation == "link" else prop["item_id"]}]
    elif mutation == "duplicate-item":
        doc["propositions"].append(prop)
    elif mutation == "duplicate-source":
        data["documents"].append(doc)
    elif mutation == "duplicate-example":
        data["documents"][1]["source"]["example_id"] = 1
    elif mutation == "source-hash":
        doc["source"]["sha256"] = "0" * 64
    elif mutation == "ontology-hash":
        data["ontology_sha256"] = "0" * 64
    elif mutation == "unknown-tag":
        prop["tags"][0]["label"] = "Imaginary Legal Concept"
    else:
        prop["tags"][0] = {"label": "Obligation", "branch": "Area of Law"}
    with pytest.raises((ValidationError, GoldSetError), match=message):
        validate_gold(GoldSuite.model_validate(data), load_ontology())


def test_link_types_are_closed_and_hierarchy_is_rejected() -> None:
    data = raw_suite()
    data["documents"][0]["propositions"][1]["links"][0]["relation"] = "elaborates"
    with pytest.raises(ValidationError):
        GoldSuite.model_validate(data)
    data = raw_suite()
    data["documents"][0]["propositions"][0]["parent_id"] = "invented"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        GoldSuite.model_validate(data)
    data = raw_suite()
    data["documents"][0]["propositions"][0]["tags"][0]["iri"] = "model-authored"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        GoldSuite.model_validate(data)


def test_reciprocal_contradictions_are_not_a_dependency_dag() -> None:
    data = raw_suite()
    first, second = data["documents"][0]["propositions"][:2]
    first["links"] = [{"relation": "contradicts", "target_id": second["item_id"]}]
    second["links"] = [{"relation": "contradicts", "target_id": first["item_id"]}]
    # Link validation establishes endpoints, not logical dependency acyclicity.
    validate_gold(GoldSuite.model_validate(data), load_ontology())


def test_ontology_slice_digest_is_checked(tmp_path: Path) -> None:
    data = json.loads((GOLD / "ontology.json").read_text(encoding="utf-8"))
    data["concepts"][0]["label"] = "Invented"
    path = tmp_path / "ontology.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(GoldSetError, match="digest"):
        load_ontology(path)


def test_missing_or_malformed_gold_is_an_explicit_error(tmp_path: Path) -> None:
    with pytest.raises(GoldSetError, match="not found"):
        load_gold(tmp_path / "absent.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    with pytest.raises(GoldSetError, match="JSON"):
        load_gold(bad)


def test_evaluation_inputs_pin_every_measurement_dependency() -> None:
    payload = {
        "source_snapshots": {"readme-01": "1" * 64}, "gold_revision": "synthetic-v1",
        "gold_sha256": "2" * 64, "split_manifest_sha256": "3" * 64,
        "ontology_sha256": "4" * 64, "scorer_version": "atomic-v1",
        "matcher_version": "one-to-one-v1", "baseline_commit": "a" * 40,
        "candidate_commit": "b" * 40, "baseline_config_sha256": "5" * 64,
        "candidate_config_sha256": "6" * 64,
        "extraction_prompt_sha256": {"distillation": "7" * 64},
        "judge_prompt_sha256": {"codex": "8" * 64, "claude": "9" * 64},
        "judge_identities": {"codex": {"cli_version": "recorded-1", "model": "fixture-model"},
                             "claude": {"cli_version": "recorded-2", "model": "fixture-model"}},
        "sampling_seed": 42,
    }
    pinned = EvaluationInputs.model_validate(payload)
    assert EvaluationInputs.model_validate_json(pinned.model_dump_json()) == pinned
    del payload["split_manifest_sha256"]
    with pytest.raises(ValidationError):
        EvaluationInputs.model_validate(payload)
