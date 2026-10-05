"""Phase 9 U4 (KTD5) — the pure-Python OWL 2 EL profile checker.

Synthetic TBox fragments only. Each forbidden construct is flagged with a
stable rule and the axiom's triples; the allowed EL constructors pass; the
shipped vocabulary TBox passes EL and the OWL 2 DL layer holds exactly the
axioms that are not EL.
"""
from __future__ import annotations

import subprocess
import sys

import pytest
from pyoxigraph import RdfFormat, parse

from folio_insights.reason.el_profile import EL_DATATYPES, check_el_profile, format_violations

PREFIXES = """
@prefix ex: <urn:ex:> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix sh: <http://www.w3.org/ns/shacl#> .
"""


def _check(ttl: str):
    return check_el_profile(parse((PREFIXES + ttl).encode(), format=RdfFormat.TURTLE))


ALLOWED = """
ex:A a owl:Class ; rdfs:subClassOf ex:B , [ a owl:Restriction ; owl:onProperty ex:p ; owl:someValuesFrom ex:C ] .
ex:D owl:equivalentClass [ owl:intersectionOf ( ex:A ex:B ) ] .
ex:E owl:equivalentClass [ a owl:Restriction ; owl:onProperty ex:p ; owl:hasValue ex:i ] .
ex:F owl:equivalentClass [ a owl:Restriction ; owl:onProperty ex:p ; owl:hasSelf true ] .
ex:G owl:equivalentClass [ owl:oneOf ( ex:i ) ] .
ex:A owl:disjointWith ex:C .
ex:p a owl:ObjectProperty , owl:TransitiveProperty , owl:ReflexiveProperty ;
     rdfs:subPropertyOf ex:q ; rdfs:domain ex:A ; rdfs:range ex:B ;
     owl:propertyChainAxiom ( ex:q ex:r ) .
ex:d a owl:DatatypeProperty , owl:FunctionalProperty ; rdfs:range xsd:dateTime .
ex:e a owl:DatatypeProperty ; rdfs:range xsd:string .
ex:A owl:hasKey ( ex:d ) .
ex:Shape a sh:NodeShape ; sh:property [ sh:path ex:d ; sh:in ( "a" "b" "c" ) ] .
"""


def test_allowed_el_constructs_pass() -> None:
    assert _check(ALLOWED) == []


@pytest.mark.parametrize(
    ("ttl", "rule"),
    [
        ("ex:p a owl:ObjectProperty , owl:InverseFunctionalProperty .", "inverse-functional-property"),
        ("ex:p a owl:ObjectProperty , owl:FunctionalProperty .", "functional-object-property"),
        ("ex:p a owl:SymmetricProperty .", "symmetric-property"),
        ("ex:p a owl:AsymmetricProperty .", "asymmetric-property"),
        ("ex:p a owl:IrreflexiveProperty .", "irreflexive-property"),
        ("ex:p owl:propertyDisjointWith ex:q .", "disjoint-properties"),
        ("ex:p owl:inverseOf ex:q .", "inverse-object-property"),
        ("ex:A owl:equivalentClass [ owl:unionOf ( ex:B ex:C ) ] .", "disjunction"),
        ("ex:A owl:disjointUnionOf ( ex:B ex:C ) .", "disjunction"),
        ("ex:A owl:equivalentClass [ owl:complementOf ex:B ] .", "negation"),
        (
            "ex:A rdfs:subClassOf [ a owl:Restriction ; owl:onProperty ex:p ; owl:allValuesFrom ex:B ] .",
            "universal-restriction",
        ),
        (
            'ex:A rdfs:subClassOf [ a owl:Restriction ; owl:onProperty ex:p ; owl:maxCardinality "2"^^xsd:nonNegativeInteger ] .',
            "cardinality-restriction",
        ),
        (
            'ex:A rdfs:subClassOf [ a owl:Restriction ; owl:onProperty ex:p ; owl:minQualifiedCardinality "3"^^xsd:nonNegativeInteger ; owl:onClass ex:B ] .',
            "cardinality-restriction",
        ),
        ("ex:A owl:equivalentClass [ owl:oneOf ( ex:i ex:j ) ] .", "enumeration"),
        ("ex:d a owl:DatatypeProperty ; rdfs:range xsd:boolean .", "datatype-outside-el"),
        ("ex:d a owl:DatatypeProperty ; rdfs:range xsd:double .", "datatype-outside-el"),
        (
            "ex:A rdfs:subClassOf [ a owl:Restriction ; owl:onProperty ex:d ; owl:someValuesFrom xsd:float ] .",
            "datatype-outside-el",
        ),
        (
            'ex:T owl:equivalentClass [ a rdfs:Datatype ; owl:onDatatype xsd:integer ; owl:withRestrictions ( [ xsd:minInclusive 1 ] ) ] .',
            "datatype-restriction",
        ),
    ],
)
def test_forbidden_constructs_are_flagged(ttl: str, rule: str) -> None:
    violations = _check(ttl)
    assert rule in {v.rule for v in violations}, violations


def test_violation_names_the_axiom_and_constraint() -> None:
    [violation] = _check("ex:key a owl:ObjectProperty , owl:InverseFunctionalProperty .")
    assert violation.subject == "<urn:ex:key>"
    assert violation.triples[0] == (
        "<urn:ex:key> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> "
        "<http://www.w3.org/2002/07/owl#InverseFunctionalProperty> ."
    )
    assert "inverse-functional" in violation.constraint
    text = format_violations([violation])
    assert "InverseFunctionalProperty" in text and "<urn:ex:key>" in text


def test_restriction_violation_carries_the_whole_anonymous_axiom() -> None:
    [violation] = _check(
        "ex:A rdfs:subClassOf [ a owl:Restriction ; owl:onProperty ex:p ; owl:allValuesFrom ex:B ] ."
    )
    joined = "\n".join(violation.triples)
    assert "allValuesFrom" in violation.triples[0]
    assert "onProperty" in joined and "<urn:ex:p>" in joined


def test_checker_is_deterministic_and_accepts_string_triples() -> None:
    triples = [("<urn:ex:p>", "<http://www.w3.org/2002/07/owl#inverseOf>", "<urn:ex:q>")]
    assert check_el_profile(triples) == check_el_profile(list(reversed(triples)))
    assert [v.rule for v in check_el_profile(triples)] == ["inverse-object-property"]


def test_el_datatype_map_excludes_boolean_and_double() -> None:
    xsd = "http://www.w3.org/2001/XMLSchema#"
    assert f"<{xsd}string>" in EL_DATATYPES and f"<{xsd}dateTime>" in EL_DATATYPES
    assert f"<{xsd}boolean>" not in EL_DATATYPES and f"<{xsd}double>" not in EL_DATATYPES


def test_shipped_vocabulary_tbox_is_el() -> None:
    """The plan's gate: the shared TBox passes OWL 2 EL (fixed in U0, not waived)."""
    from folio_insights.storage.projection import tbox_quads

    violations = check_el_profile(tbox_quads())
    assert violations == [], format_violations(violations)


def test_dl_layer_holds_exactly_the_non_el_axioms() -> None:
    from folio_insights.storage.exports import expressive_tbox_quads

    rules = sorted(v.rule for v in check_el_profile(expressive_tbox_quads()))
    assert rules == [
        "datatype-outside-el",
        "datatype-outside-el",
        "inverse-object-property",
        "inverse-object-property",
    ]


def test_el_check_never_imports_owlready2() -> None:
    """The export (web tier) runs the EL check without the JVM stack."""
    code = (
        "import sys; import folio_insights.storage.exports, folio_insights.reason.reasoner; "
        "import folio_insights.reason as r; "
        "assert 'owlready2' not in sys.modules, 'owlready2 imported'; print('ok')"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert out.returncode == 0 and out.stdout.strip() == "ok", out.stderr
