"""KTD10 / PRD §8 P6 separation invariant: subsumption goes through the reasoner,
similarity through the prototype cluster, and the API cannot confuse them.

Modelled on ``tests/governance/test_grep_guard_three_way_disambiguation.py``:
(a) the similarity module holds no SPARQL, OWL axiom or reasoner import;
(b) the reasoner modules never import the similarity path;
(c) the two result types are distinct and share no base but ``object``.
"""
from __future__ import annotations

import ast
import dataclasses
import pathlib

import pytest

from folio_insights.polysemy import similarity_query
from folio_insights.polysemy.similarity_query import SimilarityResult
from folio_insights.reason import reasoner as reasoner_mod
from folio_insights.reason import structural
from folio_insights.reason.reasoner import SubsumptionResult

pytestmark = pytest.mark.polysemy_spike


def _source(module) -> str:  # noqa: ANN001
    return pathlib.Path(module.__file__).read_text(encoding="utf-8")


def _imports(module) -> set[str]:  # noqa: ANN001
    tree = ast.parse(_source(module))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
            out.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
    return out


def _code_without_docstrings(module) -> str:  # noqa: ANN001
    tree = ast.parse(_source(module))
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) \
                and isinstance(getattr(body[0], "value", None), ast.Constant):
            body.pop(0)
    return ast.unparse(tree)


def test_similarity_module_has_no_subsumption_path() -> None:
    imports = _imports(similarity_query)
    assert not any(i.startswith(("folio_insights.reason", "pyoxigraph", "owlready2",
                                 "folio_insights.store", "folio_insights.polysemy.tbox"))
                   for i in imports), imports
    code = _code_without_docstrings(similarity_query)
    for token in ("disjointWith", "subClassOf", "SELECT", "ASK", "query_rdf12",
                  "SubsumptionResult", "is_subclass_of", "are_disjoint"):
        assert token not in code, token


@pytest.mark.parametrize("module", [reasoner_mod, structural])
def test_reasoner_modules_never_import_similarity(module) -> None:  # noqa: ANN001
    imports = _imports(module)
    assert not any(i.startswith(("folio_insights.polysemy",)) for i in imports), imports
    code = _code_without_docstrings(module)
    for token in ("SimilarityResult", "cosine", "centroid", "embedding"):
        assert token not in code, token


def test_rule1_goes_through_the_reasoner_not_similarity() -> None:
    from folio_insights.polysemy import detector, tbox

    assert "folio_insights.reason.reasoner" in _imports(tbox)
    assert not any(i.startswith("folio_insights.polysemy.similarity_query") for i in _imports(tbox))
    assert detector.has_framework_conflicting_axiom is tbox.has_framework_conflicting_axiom


def test_result_types_are_distinct() -> None:
    assert SubsumptionResult.__mro__[1:] == (object,)
    assert SimilarityResult.__mro__[1:] == (object,)
    sub_fields = {f.name for f in dataclasses.fields(SubsumptionResult)}
    sim_fields = {f.name for f in dataclasses.fields(SimilarityResult)}
    assert "holds" in sub_fields and "holds" not in sim_fields
    assert "distance" in sim_fields and "distance" not in sub_fields
    sim = SimilarityResult("t", "a", "b", 0.3)
    assert not isinstance(sim, SubsumptionResult)
    assert sim.similarity == pytest.approx(0.7)
