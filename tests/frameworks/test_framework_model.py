"""Phase 9 U2 — the Framework model, ID pattern, v1 migration, registry, SKOS.

Synthetic framework records only.
"""
from __future__ import annotations

import json
from importlib.resources import files

import pytest
from pydantic import ValidationError
from pyoxigraph import NamedNode, RdfFormat, parse

from folio_insights.models.framework import (
    FRAMEWORK_SCHEME_IRI,
    SKOS,
    Framework,
    FrameworkRegistry,
    MalformedFrameworkId,
    UnregisteredFramework,
    check_framework_id,
    default_frameworks,
    migrate_v1_framework_id,
)
from folio_insights.vocab._constants import FRAMEWORK_NS

PROVISIONAL_DEFAULTS = sorted([
    "us.federal.frcp",
    "us.federal.fre",
    "us.ucc",
    "us.restatement_2d.contracts",
    "us.common_law",
    "uk.england.common_law",
    "us.louisiana.civil_code",
])


@pytest.mark.parametrize(
    "good", ["us.federal.frcp", "us.ucc", "uk.england.common_law", "us.restatement_2d.contracts",
             "us.delaware.dgcl", "eu.gdpr"]
)
def test_valid_ids(good: str) -> None:
    assert check_framework_id(good) == good


@pytest.mark.parametrize(
    "bad", ["us", "US.federal", "us.federal.frcp.2024", "us..fre", "us.federal fre", ".us.fre",
            "us.fre.", "1us.fre", "us.a.b.c.d.e", "", None, 7]
)
def test_malformed_ids_are_refused(bad: object) -> None:
    with pytest.raises(MalformedFrameworkId):
        check_framework_id(bad)


def test_framework_has_no_time_scope_and_checks_its_shape() -> None:
    fw = Framework(id="us.delaware.dgcl", label="Delaware GCL", jurisdiction="us.delaware")
    assert fw.iri == FRAMEWORK_NS + "us.delaware.dgcl"
    assert not {"time_scope", "valid_from", "valid_time_start", "year"} & set(Framework.model_fields)
    with pytest.raises(ValidationError):
        Framework(id="us.delaware.dgcl", label="x", jurisdiction="uk")  # jurisdiction prefix
    with pytest.raises(ValidationError):
        Framework(id="us.x", label="x", jurisdiction="us", parent="us.x")
    with pytest.raises(ValidationError):
        Framework(id="us.x", label="", jurisdiction="us")
    with pytest.raises(ValidationError):
        Framework(id="us.x", label="x", jurisdiction="us", time_scope="1990")  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("raw", "expected", "warned"),
    [
        ("us.federal.frcp.2024", "us.federal.frcp", True),
        ("us.restatement_2d.contracts.1981", "us.restatement_2d.contracts", True),
        ("us.federal.fre-2011", "us.federal.fre", True),
        ("US.Federal.FRE", "us.federal.fre", True),
        ("us.ucc", "us.ucc", False),
    ],
)
def test_v1_migration_strips_year_suffix_with_a_warning(raw: str, expected: str, warned: bool) -> None:
    result = migrate_v1_framework_id(raw)
    assert result.framework_id == expected
    assert bool(result.warnings) is warned and result.changed is warned
    if raw.endswith(("2024", "1981", "2011")):
        assert any("year suffix stripped" in w for w in result.warnings)


def test_v1_migration_never_guesses() -> None:
    with pytest.raises(MalformedFrameworkId):
        migrate_v1_framework_id("Federal Rules 2024")


def test_default_set_is_one_provisional_data_file() -> None:
    """Decision Sheet q3 (open): the recommended seven, in ONE data file."""
    data = json.loads(
        (files("folio_insights.frameworks") / "default_frameworks.json").read_text("utf-8")
    )
    assert data["provisional"]["qid"] == "q3"
    assert sorted(f["id"] for f in data["frameworks"]) == PROVISIONAL_DEFAULTS
    assert sorted(f.id for f in default_frameworks()) == PROVISIONAL_DEFAULTS
    assert FrameworkRegistry.with_defaults().ids() == PROVISIONAL_DEFAULTS


def test_default_list_is_not_duplicated_in_code() -> None:
    """Changing the set stays a one-file change: no module repeats the list.

    (Modules may name individual frameworks — citation patterns, fixture tags —
    which simply do not apply when their framework is not registered.)"""
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "src" / "folio_insights"
    offenders = [
        str(p.relative_to(src))
        for p in src.rglob("*.py")
        if all(fid in p.read_text("utf-8") for fid in PROVISIONAL_DEFAULTS)
    ]
    assert offenders == [], offenders


def test_registry_crud_and_resolution() -> None:
    reg = FrameworkRegistry.with_defaults()
    child = Framework(id="us.federal.fre.rule_702", label="FRE 702", jurisdiction="us.federal",
                      parent="us.federal.fre")
    reg.register(child)
    assert reg.resolve("us.federal.fre.rule_702") is child and "us.federal.fre.rule_702" in reg
    assert reg.register(child) is child  # identical re-registration is a no-op
    with pytest.raises(ValueError):
        reg.register(child.model_copy(update={"label": "changed"}))
    with pytest.raises(ValueError, match="unregistered parent"):
        reg.register(Framework(id="us.texas.code", label="x", jurisdiction="us.texas",
                               parent="us.texas"))
    with pytest.raises(UnregisteredFramework):
        reg.resolve("us.delaware.dgcl")
    with pytest.raises(MalformedFrameworkId):
        reg.resolve("Delaware")


def test_skos_concept_scheme_export() -> None:
    reg = FrameworkRegistry.with_defaults()
    reg.register(Framework(id="us.federal.fre.rule_702", label="FRE 702",
                           jurisdiction="us.federal", parent="us.federal.fre"))
    triples = list(parse(reg.to_skos_turtle().encode(), format=RdfFormat.TURTLE))
    concepts = {t.subject for t in triples
                if t.predicate.value.endswith("#type") and t.object == NamedNode(SKOS + "Concept")}
    assert len(concepts) == 8
    broader = [(t.subject.value, t.object.value) for t in triples
               if t.predicate == NamedNode(SKOS + "broader")]
    assert broader == [(FRAMEWORK_NS + "us.federal.fre.rule_702", FRAMEWORK_NS + "us.federal.fre")]
    tops = {t.object for t in triples if t.predicate == NamedNode(SKOS + "hasTopConcept")}
    assert len(tops) == 7
    assert any(t.subject == NamedNode(FRAMEWORK_SCHEME_IRI) for t in triples)


def test_polysemy_fixture_frameworks_are_registered_iris() -> None:
    from folio_insights.polysemy.fixture_loader import (
        FIXTURE_FRAMEWORK_IDS,
        ShardFixture,
        consideration_fixtures_to_ttl,
    )

    defaults = FrameworkRegistry.with_defaults()
    assert all(fid in defaults for fid in FIXTURE_FRAMEWORK_IDS.values())
    shards = [
        ShardFixture(iri=f"urn:x:fixture/{i}", framework=name, source_doc="urn:x:doc",
                     extracted_text="synthetic", axiom_summary="synthetic axiom")
        for i, name in enumerate(sorted(FIXTURE_FRAMEWORK_IDS))
    ]
    triples = list(parse(consideration_fixtures_to_ttl(shards).encode(), format=RdfFormat.TURTLE))
    objects = [t.object for t in triples if t.predicate.value.endswith("/inFramework")]
    assert len(objects) == len(shards)
    assert all(isinstance(o, NamedNode) and o.value.startswith(FRAMEWORK_NS) for o in objects)
