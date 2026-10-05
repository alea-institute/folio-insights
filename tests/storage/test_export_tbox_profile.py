"""Phase 9 U4 (R7) — the TBox stays in OWL 2 EL unless the operator opts in.

Without ``--expressive`` a TBox axiom outside EL fails the export, names the
axiom and the EL constraint, and writes nothing. With ``--expressive`` the
export succeeds with a warning, carries the OWL 2 DL layer and records HermiT
as the reasoner. Disposable roots, synthetic shards.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner
from pyoxigraph import NamedNode, Quad, RdfFormat, parse

from folio_insights.cli import cli
from folio_insights.reason.reasoner import (
    HermitReasoner,
    Reasoner,
    reasoner_for_profile,
)
from folio_insights.storage import CorpusStorageContext
from folio_insights.storage.exports import (
    ExportFormat,
    ExportRefused,
    TBoxProfileViolation,
    export_corpus,
    resolve_tbox_profile,
)
from folio_insights.storage.projection import TBOX_GRAPH, ProjectionHandle

from tests.storage.conftest import shard

OWL = "http://www.w3.org/2002/07/owl#"
RDF_TYPE = NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
KEY = NamedNode("urn:example:tbox#hasNationalId")


async def _corpus(root: Path, *, inject_non_el: bool) -> None:
    ctx = await CorpusStorageContext.open(root, "corpus-a")
    try:
        await ctx.ingest_shards([shard(1), shard(2)])
    finally:
        await ctx.close()
    if inject_non_el:
        # A TBox that has drifted out of EL (the store's TBox graph holds it
        # until the vocabulary digest changes).
        handle = ProjectionHandle(root)
        try:
            handle.store.extend(
                [
                    Quad(KEY, RDF_TYPE, NamedNode(f"{OWL}ObjectProperty"), TBOX_GRAPH),
                    Quad(KEY, RDF_TYPE, NamedNode(f"{OWL}InverseFunctionalProperty"), TBOX_GRAPH),
                ]
            )
        finally:
            handle.close()


async def _export(root: Path, dest: Path, **kwargs):
    ctx = await CorpusStorageContext.open(root, "corpus-a")
    try:
        return await export_corpus(ctx, dest, **kwargs)
    finally:
        await ctx.close()


async def test_shipped_tbox_exports_under_el_by_default(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    await _corpus(root, inject_non_el=False)
    result = await _export(root, tmp_path / "out")
    profile = result.manifest["tbox_profile"]
    assert profile["profile"] == "EL" and profile["el_conformant"] is True
    assert profile["reasoner"] == "hermit" and profile["warnings"] == []
    tbox = list(parse(path=str(tmp_path / "out" / "tbox.ttl"), format=RdfFormat.TURTLE))
    assert not any(t.predicate.value == f"{OWL}inverseOf" for t in tbox)  # DL layer is opt-in


async def test_non_el_axiom_fails_without_expressive_and_names_it(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    await _corpus(root, inject_non_el=True)
    dest = tmp_path / "out"
    with pytest.raises(TBoxProfileViolation) as info:
        await _export(root, dest)
    message = str(info.value)
    assert "<urn:example:tbox#hasNationalId>" in message
    assert "InverseFunctionalProperty" in message
    assert "inverse-functional" in message and "--expressive" in message
    assert [v.rule for v in info.value.violations] == ["inverse-functional-property"]
    assert isinstance(info.value, ExportRefused)
    assert not dest.exists()  # nothing written


async def test_abox_only_export_does_not_carry_or_check_the_tbox(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    await _corpus(root, inject_non_el=True)
    result = await _export(root, tmp_path / "out", formats=[ExportFormat.ABOX_TTL])
    assert result.manifest["tbox_profile"]["checked"] is False


async def test_expressive_export_succeeds_with_a_warning(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    await _corpus(root, inject_non_el=True)
    result = await _export(root, tmp_path / "out", expressive=True)
    profile = result.manifest["tbox_profile"]
    assert profile["profile"] == "DL" and profile["expressive_layer"] is True
    assert profile["reasoner"] == "hermit"
    assert profile["warnings"] and "outside OWL 2 EL" in profile["warnings"][0]
    rules = sorted(v["rule"] for v in profile["el_violations"])
    assert "inverse-functional-property" in rules and "inverse-object-property" in rules
    tbox = list(parse(path=str(tmp_path / "out" / "tbox.ttl"), format=RdfFormat.TURTLE))
    assert any(t.predicate.value == f"{OWL}inverseOf" for t in tbox)  # DL layer exported
    assert any(t.subject == KEY for t in tbox)


async def test_tbox_profile_dl_equals_expressive(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    await _corpus(root, inject_non_el=False)
    result = await _export(root, tmp_path / "out", tbox_profile="DL")
    assert result.manifest["tbox_profile"]["profile"] == "DL"
    assert resolve_tbox_profile(None, False) == "EL"
    assert resolve_tbox_profile("DL", False) == "DL" == resolve_tbox_profile(None, True)
    with pytest.raises(ValueError):
        resolve_tbox_profile("EL", True)
    with pytest.raises(ValueError):
        resolve_tbox_profile("QL", False)  # type: ignore[arg-type]


def test_cli_flags(tmp_path: Path) -> None:
    import asyncio

    root = tmp_path / "storage"
    asyncio.run(_corpus(root, inject_non_el=True))
    runner = CliRunner()
    base = ["storage", "export", "corpus-a", "--corpus-root", str(root)]

    refused = runner.invoke(cli, [*base, "--out", str(tmp_path / "a")])
    assert refused.exit_code != 0
    assert "InverseFunctionalProperty" in refused.output
    assert not (tmp_path / "a").exists()

    ok = runner.invoke(cli, [*base, "--out", str(tmp_path / "b"), "--expressive"])
    assert ok.exit_code == 0, ok.output
    assert "warning:" in ok.output and "InverseFunctionalProperty" in ok.output

    conflict = runner.invoke(
        cli, [*base, "--out", str(tmp_path / "c"), "--expressive", "--tbox-profile", "EL"]
    )
    assert conflict.exit_code == 2 and "conflicts" in conflict.output


def test_reasoner_seam_is_hermit_for_both_profiles() -> None:
    for profile in ("EL", "DL"):
        reasoner = reasoner_for_profile(profile)  # type: ignore[arg-type]
        assert isinstance(reasoner, Reasoner) and isinstance(reasoner, HermitReasoner)
        assert reasoner.name == "hermit" and profile in reasoner.profiles
    with pytest.raises(ValueError):
        reasoner_for_profile("QL")  # type: ignore[arg-type]


@pytest.mark.skipif(
    shutil.which("java") is None or os.environ.get("FOLIO_SKIP_HERMIT") == "1",
    reason="HermiT needs a JRE (worker tier)",
)
async def test_hermit_reasons_over_the_expressive_tbox(tmp_path: Path) -> None:
    pytest.importorskip("owlready2")
    from pyoxigraph import serialize

    root = tmp_path / "storage"
    await _corpus(root, inject_non_el=False)
    await _export(root, tmp_path / "out", expressive=True, formats=[ExportFormat.TBOX_TTL])
    triples = list(parse(path=str(tmp_path / "out" / "tbox.ttl"), format=RdfFormat.TURTLE))
    owl_only = [t for t in triples if "shacl" not in str(t)]  # HermiT reads OWL, not SHACL
    nt = tmp_path / "tbox.nt"
    nt.write_bytes(serialize(owl_only, format=RdfFormat.N_TRIPLES))
    result = HermitReasoner(xmx_mb=512).check(nt, profile="DL")
    assert result.reasoner == "hermit" and result.consistent is True


TBOX_CONSTRUCT = (
    "CONSTRUCT { ?s ?p ?o } WHERE { GRAPH <https://folio-insights.aleainstitute.ai/tbox> "
    "{ ?s ?p ?o } }"
)


async def test_construct_only_export_is_el_gated(tmp_path: Path) -> None:
    """Review P2-7: a CONSTRUCT that selects a non-EL axiom is refused under EL."""
    root = tmp_path / "storage"
    await _corpus(root, inject_non_el=True)
    dest = tmp_path / "out"
    with pytest.raises(TBoxProfileViolation, match="CONSTRUCT result"):
        await _export(root, dest, formats=[ExportFormat.SPARQL_CONSTRUCT],
                      construct_query=TBOX_CONSTRUCT, allow_partial=True)
    assert not dest.exists()
    ok = await _export(root, tmp_path / "dl", formats=[ExportFormat.SPARQL_CONSTRUCT],
                       construct_query=TBOX_CONSTRUCT, allow_partial=True, expressive=True)
    profile = ok.manifest["tbox_profile"]
    assert profile["construct_checked"] is True and profile["warnings"]
    assert "inverse-functional-property" in {v["rule"] for v in profile["el_violations"]}


async def test_export_records_a_tbox_revision_marker(tmp_path: Path) -> None:
    from folio_insights.storage.projection import tbox_digest
    from folio_insights.vocab._constants import TBOX_REVISION, VOCAB_VERSION

    root = tmp_path / "storage"
    await _corpus(root, inject_non_el=False)
    profile = (await _export(root, tmp_path / "out")).manifest["tbox_profile"]
    assert profile["vocab_version"] == VOCAB_VERSION
    assert profile["tbox_revision"] == TBOX_REVISION != VOCAB_VERSION
    assert profile["tbox_digest"] == tbox_digest()
