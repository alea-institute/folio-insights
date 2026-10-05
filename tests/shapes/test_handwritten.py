"""SHACL-01: the six hand-written shapes parse and flag the PRD §10 fixtures.

Every case in ``cases.py`` runs under pyshacl (the reference engine) over the
local tier of the full suite. Valid fixtures conform with no results.
Each invalid fixture produces its expected severity and message.
"""
from __future__ import annotations

import pytest
from pyoxigraph import RdfFormat
from pyoxigraph import parse as ox_parse
from rdflib import Graph

from folio_insights.shapes import pyshacl_adapter
from folio_insights.shapes.suite import HAND_WRITTEN, HAND_WRITTEN_PATHS, SUITE_PATHS
from tests.shapes.cases import INVALID_CASES, NOT_EXPRESSIBLE, VALID_CASES, Case

SH = "http://www.w3.org/ns/shacl#"


def test_six_hand_written_shapes_exist_and_parse() -> None:
    assert HAND_WRITTEN == (
        "envelope", "subtypes", "governance", "supersession", "distinguo", "signatures",
    )
    for path in HAND_WRITTEN_PATHS:
        graph = Graph().parse(str(path), format="turtle")
        with open(path, "rb") as handle:
            assert len(list(ox_parse(handle, format=RdfFormat.TURTLE))) == len(graph) > 0
        shapes = set(graph.subjects(predicate=None, object=__import__("rdflib").URIRef(f"{SH}NodeShape")))
        assert shapes, f"{path.name} declares no sh:NodeShape"


@pytest.mark.parametrize("case", VALID_CASES, ids=lambda c: c.name)
def test_valid_fixtures_conform(case: Case) -> None:
    report = pyshacl_adapter.validate(case.build(), SUITE_PATHS)
    assert report.conforms, report.text
    assert report.results == [], report.text


@pytest.mark.parametrize("case", INVALID_CASES, ids=lambda c: c.name)
def test_invalid_fixtures_produce_their_message(case: Case) -> None:
    report = pyshacl_adapter.validate(case.build(), SUITE_PATHS)
    matching = [
        r for r in report.results
        if r["severity"] == f"{SH}{case.severity}"
        and any(case.message in m for m in r["message"])
    ]
    assert matching, f"expected {case.severity} containing {case.message!r}\n{report.text}"
    # Conformance follows severity: only Violations make a record non-conforming.
    assert report.conforms is (case.severity != "Violation") or any(
        r["severity"] == f"{SH}Violation" for r in report.results
    )


def test_warning_only_fixtures_still_conform() -> None:
    warnings = [c for c in INVALID_CASES if c.severity == "Warning"]
    assert len(warnings) >= 8
    for case in warnings:
        report = pyshacl_adapter.validate(case.build(), SUITE_PATHS)
        assert report.conforms, f"{case.name} must not refuse anything\n{report.text}"


def test_inexpressible_prd_fixtures_name_their_enforcer() -> None:
    assert set(NOT_EXPRESSIBLE) == {
        "signature verification failure",
        "promotion without reviewer role",
        "arbiter action with reviewer DID",
    }
    assert all(NOT_EXPRESSIBLE.values())
