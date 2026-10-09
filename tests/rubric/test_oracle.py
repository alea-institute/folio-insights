"""IRI oracles (KTD4): the frozen fixture oracle and the lazy live FOLIO oracle."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from folio_insights.rubric.oracle import (
    OWL_THING,
    FixtureOracle,
    FolioResolveOracle,
    IriOracle,
    OracleError,
    load_oracle,
    normalize_branch,
)

from tests.rubric.conftest import CROSS, ORACLE_PATH, RUSSIA, SYNTHETIC_IRI

F = "https://folio.openlegalstandard.org/"


def test_fixture_oracle_knows_exactly_its_concepts(oracle: FixtureOracle) -> None:
    assert isinstance(oracle, IriOracle)
    assert oracle.exists(RUSSIA) and oracle.branch_of(RUSSIA) == ("Location",)
    assert oracle.branch_of(CROSS) == ("Event", "Service")
    assert not oracle.exists(SYNTHETIC_IRI) and oracle.branch_of(SYNTHETIC_IRI) == ()


def test_fixture_oracle_holds_only_real_folio_iris() -> None:
    """Every frozen entry is a FOLIO IRI; nothing synthetic may pose as a real concept."""
    data = json.loads(ORACLE_PATH.read_text(encoding="utf-8"))
    for iri, entry in data["concepts"].items():
        assert iri.startswith(F) and "SYNTHETIC" not in iri.upper(), iri
        assert entry["branches"], iri
        assert not entry["label"].upper().startswith("SYNTHETIC"), iri


def test_fixture_oracle_covers_every_gold_iri(oracle: FixtureOracle) -> None:
    """The frozen oracle lists the gold set's real IRIs and nothing it does not use."""
    gold = Path(ORACLE_PATH).parent / "books_gold"
    used: set[str] = set()
    for run in gold.glob("*/extraction.json"):
        for u in json.loads(run.read_text(encoding="utf-8"))["units"]:
            used.update(t["iri"] for t in u["folio_tags"] if t["iri"])
    real = {i for i in used if "SYNTHETIC" not in i}
    assert real <= set(oracle.concepts), real - set(oracle.concepts)
    # The conftest constants plus the gold IRIs are all the oracle holds.
    assert set(oracle.concepts) - real <= {CROSS, RUSSIA}


@pytest.mark.parametrize("payload, match", [
    ({"concepts": {}}, "format"),
    ({"format": 1, "concepts": []}, "concepts"),
    ({"format": 1, "concepts": {"x": "y"}}, "must be an object"),
    ({"format": 1, "concepts": {"x": {"branches": "Service"}}}, "list of strings"),
])
def test_fixture_oracle_rejects_malformed_files(payload: dict, match: str) -> None:
    with pytest.raises(OracleError, match=match):
        FixtureOracle.from_dict(payload)


def test_fixture_oracle_file_errors(tmp_path: Path) -> None:
    with pytest.raises(OracleError, match="not found"):
        FixtureOracle.from_file(tmp_path / "absent.json")
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    with pytest.raises(OracleError, match="not valid JSON"):
        FixtureOracle.from_file(bad)


def test_normalize_branch() -> None:
    assert normalize_branch(" Document/Artifact ") == normalize_branch("document / artifact")


def test_load_oracle_specs(tmp_path: Path) -> None:
    assert load_oracle(None) is None
    assert isinstance(load_oracle(ORACLE_PATH), FixtureOracle)
    live = load_oracle("folio")
    assert isinstance(live, FolioResolveOracle)
    assert live._provider is None  # nothing loaded until first use


def test_folio_resolve_oracle_is_lazy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Constructing the live oracle imports nothing; only the first lookup loads FOLIO."""
    monkeypatch.setitem(sys.modules, "folio_resolve", None)  # any import now fails
    oracle = FolioResolveOracle()
    assert oracle._provider is None
    with pytest.raises(ImportError):
        oracle.exists(F + "Ranything")


def _ontology():  # noqa: ANN202
    from folio_resolve import Concept, InMemoryOntology

    concepts = [
        Concept(iri=F + "Rsvc", label="Service", parent_iris=(OWL_THING,)),
        Concept(iri=F + "Revt", label="Event", parent_iris=(OWL_THING,)),
        Concept(iri=F + "Rloc", label="Location", preferred_label="Global",
                parent_iris=(OWL_THING,)),
        Concept(iri=F + "Rlit", label="Litigation Practice", parent_iris=(F + "Rsvc",)),
        Concept(iri=F + "Rtrial", label="Trial Events", parent_iris=(F + "Revt",)),
        Concept(iri=F + "Rcross", label="Cross", parent_iris=(F + "Rlit", F + "Rtrial")),
        Concept(iri=F + "Rcountry", label="Country", parent_iris=(F + "Rloc",)),
        # A cycle must not loop forever.
        Concept(iri=F + "Ra", label="A", parent_iris=(F + "Rb",)),
        Concept(iri=F + "Rb", label="B", parent_iris=(F + "Ra",)),
    ]
    return InMemoryOntology(concepts)


def test_folio_resolve_oracle_walks_to_top_level_branches() -> None:
    oracle = FolioResolveOracle(provider=_ontology())
    assert oracle.exists(F + "Rcross") and not oracle.exists(F + "Rmissing")
    assert oracle.branch_of(F + "Rcross") == ("Event", "Service")
    # The branch is the rdfs:label ("Location"), not the preferred label.
    assert oracle.branch_of(F + "Rcountry") == ("Location",)
    assert oracle.branch_of(F + "Rsvc") == ("Service",)
    assert oracle.branch_of(F + "Rmissing") == ()
    assert oracle.branch_of(F + "Ra") == ()  # cyclic, no root: no branch, no hang
    assert not oracle.exists(OWL_THING)
