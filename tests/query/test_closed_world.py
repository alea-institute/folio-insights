"""Phase 9 U5 (R8): closed-world islands. Synthetic triples only."""
from __future__ import annotations

import dataclasses
import inspect
import pathlib
import typing

import pytest
from pyoxigraph import NamedNode, Quad, Store

from folio_insights import query
from folio_insights.query import closed_world as cw
from folio_insights.query.closed_world import (
    CLOSED_UNDER,
    OPEN_NOTE,
    ClosedWorldQuery,
    ClosedWorldScope,
    CountResult,
    InvalidIri,
)

EX = "https://example.test/"
CONTRACT_CLS = EX + "Contract"
PARTY = EX + "hasParty"
SIGNATORY = EX + "hasSignatory"
SCOPE = EX + "scope/contracts"
RDF_TYPE = cw.RDF_TYPE


class StoreRunner:
    """A SparqlRunner over an in-memory pyoxigraph store (union default graph)."""

    def __init__(self, triples: list[tuple[str, str, str]]) -> None:
        self.store = Store()
        self.queries: list[str] = []
        for s, p, o in triples:
            self.store.add(Quad(NamedNode(s), NamedNode(p), NamedNode(o)))

    async def query(self, sparql: str, *, include_tbox: bool = False):  # noqa: ANN201
        self.queries.append(sparql)
        res = self.store.query(sparql, use_default_graph_as_union=True)
        names = [v.value for v in res.variables]
        return [{n: sol[n] for n in names} for sol in res]


def planted(*, closed: bool) -> list[tuple[str, str, str]]:
    """Three contracts; c1 has a party and a signatory, c2 a party only, c3 neither."""
    t = [(EX + f"c{i}", RDF_TYPE, CONTRACT_CLS) for i in (1, 2, 3)]
    t += [(EX + "c1", PARTY, EX + "alice"), (EX + "c1", PARTY, EX + "bob"),
          (EX + "c2", PARTY, EX + "carol"), (EX + "c1", SIGNATORY, EX + "alice")]
    if closed:
        t += [(EX + f"c{i}", CLOSED_UNDER, SCOPE) for i in (1, 2, 3)]
    return t


SCOPE_DATA = ClosedWorldScope(SCOPE, frozenset({CONTRACT_CLS}), frozenset({PARTY, SIGNATORY}))


async def test_all_parties_closed_only_under_closed_under() -> None:
    q = ClosedWorldQuery(StoreRunner(planted(closed=True)), [SCOPE_DATA])
    r = await q.count_related(EX + "c1", PARTY)
    assert (r.world_assumption, r.count, r.scope_iri, r.incompleteness_note) == (
        "closed", 2, SCOPE, None)
    assert r.items == (EX + "alice", EX + "bob") and r.is_complete


async def test_all_parties_open_without_the_triple_and_notes_incompleteness() -> None:
    q = ClosedWorldQuery(StoreRunner(planted(closed=False)), [SCOPE_DATA])
    r = await q.count_related(EX + "c1", PARTY)
    assert r.world_assumption == "open" and r.count == 2 and not r.is_complete
    assert r.incompleteness_note == OPEN_NOTE and "incomplete" in r.incompleteness_note


async def test_triple_without_registered_scope_stays_open() -> None:
    q = ClosedWorldQuery(StoreRunner(planted(closed=True)), [])
    assert (await q.count_related(EX + "c1", PARTY)).world_assumption == "open"


async def test_scope_not_covering_the_property_stays_open() -> None:
    narrow = ClosedWorldScope(SCOPE, frozenset({CONTRACT_CLS}), frozenset({SIGNATORY}))
    q = ClosedWorldQuery(StoreRunner(planted(closed=True)), [narrow])
    assert (await q.count_related(EX + "c1", PARTY)).world_assumption == "open"


async def test_naf_results_differ_between_closed_and_open() -> None:
    closed = ClosedWorldQuery(StoreRunner(planted(closed=True)), [SCOPE_DATA])
    opened = ClosedWorldQuery(StoreRunner(planted(closed=False)), [SCOPE_DATA])
    c = await closed.count_lacking(CONTRACT_CLS, SIGNATORY, SCOPE)
    o = await opened.count_lacking(CONTRACT_CLS, SIGNATORY, SCOPE)
    assert (c.world_assumption, c.count) == ("closed", 2)  # c2 and c3 lack a signatory
    assert (c.total_instances, c.asserted_with_property) == (3, 1)
    assert (o.world_assumption, o.count) == ("open", None)  # absence is not negation
    assert (o.total_instances, o.asserted_with_property) == (3, 1)
    assert o.incompleteness_note == OPEN_NOTE and c.incompleteness_note is None


async def test_filter_not_exists_only_runs_inside_a_bound_scope() -> None:
    runner = StoreRunner(planted(closed=False))
    await ClosedWorldQuery(runner, [SCOPE_DATA]).count_lacking(CONTRACT_CLS, SIGNATORY, SCOPE)
    await ClosedWorldQuery(runner, [SCOPE_DATA]).count_related(EX + "c1", PARTY)
    assert not any("NOT EXISTS" in s for s in runner.queries)
    bound = StoreRunner(planted(closed=True))
    await ClosedWorldQuery(bound, [SCOPE_DATA]).count_lacking(CONTRACT_CLS, SIGNATORY, SCOPE)
    assert any("NOT EXISTS" in s for s in bound.queries)


async def test_declared_scope_iris_read_from_the_projection() -> None:
    assert await ClosedWorldQuery(StoreRunner(planted(closed=True))).declared_scope_iris() == [SCOPE]
    assert await ClosedWorldQuery(StoreRunner(planted(closed=False))).declared_scope_iris() == []


@pytest.mark.parametrize("bad", [
    "x> } DROP ALL #", "has space", "<a>", 'a:b"c', "a:b}{", "", "nocolon", "a:b\nc",
])
async def test_injection_shaped_values_are_refused(bad: str) -> None:
    q = ClosedWorldQuery(StoreRunner([]), [])
    with pytest.raises(InvalidIri):
        await q.count_related(bad, PARTY)
    with pytest.raises(InvalidIri):
        await q.count_related(EX + "c1", bad)
    with pytest.raises(InvalidIri):
        await q.count_lacking(CONTRACT_CLS, PARTY, bad)
    with pytest.raises(InvalidIri):
        ClosedWorldScope(bad)


async def test_real_corpus_projection_is_open_without_declarations(tmp_path) -> None:  # noqa: ANN001
    from folio_insights.storage import CorpusStorageContext

    ctx = await CorpusStorageContext.open(tmp_path / "root", "corpus-a")
    try:
        q = ClosedWorldQuery(ctx, [SCOPE_DATA])
        assert await q.declared_scope_iris() == []
        r = await q.count_related(EX + "c1", PARTY)
        assert (r.world_assumption, r.count) == ("open", 0)
        lack = await q.count_lacking(CONTRACT_CLS, SIGNATORY, SCOPE)
        assert lack.world_assumption == "open" and lack.count is None
    finally:
        await ctx.close()


def test_every_public_count_api_result_declares_a_world_assumption() -> None:
    assert set(cw.COUNT_APIS) == {
        n for n, _ in inspect.getmembers(ClosedWorldQuery, inspect.iscoroutinefunction)
        if n.startswith("count_")
    }
    for name in cw.COUNT_APIS:
        ret = typing.get_type_hints(getattr(ClosedWorldQuery, name))["return"]
        assert issubclass(ret, CountResult), name
        fields = {f.name: f for f in dataclasses.fields(ret)}
        assert "world_assumption" in fields, name
        assert typing.get_args(fields["world_assumption"].type) or fields[
            "world_assumption"].type in ("WorldAssumption", cw.WorldAssumption)


def test_dependency_leak_guard() -> None:
    forbidden = ("owlready2", "pyoxigraph", "oxrdflib", "pyshacl", "rdflib", "torch",
                 "folio_insights.storage", "folio_insights.vocab", "folio_insights.governance")
    qdir = pathlib.Path(query.__file__).parent
    for f in qdir.glob("*.py"):
        if f.name == "cli.py":  # the CLI wires storage lazily by design
            continue
        src = f.read_text(encoding="utf-8")
        for mod in forbidden:
            assert f"import {mod}" not in src and f"from {mod}" not in src, (f.name, mod)


def test_cli_registered_and_reports_unknown_corpus(tmp_path) -> None:  # noqa: ANN001
    from click.testing import CliRunner

    from folio_insights.cli import cli

    help_out = CliRunner().invoke(cli, ["query", "count", "--help"])
    assert help_out.exit_code == 0 and "related" in help_out.output and "lacking" in help_out.output
    res = CliRunner().invoke(cli, [
        "query", "count", "related", "--corpus", "nope", "--corpus-root", str(tmp_path),
        "--subject", EX + "c1", "--property", PARTY])
    assert res.exit_code == 1
