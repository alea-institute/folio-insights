"""CLI source copies remain accessible within the viewer's output confinement."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from api.routes import source
from folio_insights.cli import cli
from folio_insights.pipeline.orchestrator import PipelineOrchestrator


@pytest.fixture
def extraction_stages(monkeypatch):
    """Exercise real ingestion, parsing, boundary detection and output, without LLMs."""
    monkeypatch.setattr("folio_insights.pipeline.stages.ingestion.IngestionBridge", lambda: None)
    monkeypatch.setattr("folio_insights.pipeline.stages.ingestion.MapperBridge", lambda: None)
    build_stages = PipelineOrchestrator._build_stages
    monkeypatch.setattr(
        PipelineOrchestrator, "_build_stages", lambda self: build_stages(self)[:3]
    )


def _extract(input_dir: Path, output_dir: Path, corpus: str = "legal"):
    return CliRunner().invoke(
        cli,
        ["extract", str(input_dir), "--output", str(output_dir),
         "--corpus", corpus, "--no-resume"],
    )


def _write_input(path: Path, text: str = "Always review the evidence before trial."):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"<chapter><paragraph>{text}</paragraph></chapter>")


def test_external_cli_sources_are_available_in_viewer(tmp_path, monkeypatch, extraction_stages):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    original = input_dir / "chapter.xml"
    _write_input(original)
    result = _extract(input_dir, output_dir)
    assert result.exit_code == 0, result.output
    data = json.loads((output_dir / "legal" / "extraction.json").read_text())
    assert data["units"]
    expected = "legal/sources/chapter.xml"
    unit = data["units"][0]
    assert unit["source_file"] == expected
    assert unit["original_span"]["source_file"] == expected
    manifest = json.loads((output_dir / "legal" / "corpus-legal.json").read_text())
    assert manifest["documents"][0]["file_path"] == expected
    assert (output_dir / expected).read_bytes() == original.read_bytes()
    monkeypatch.setattr(source, "_output_dir", lambda: output_dir)
    response = asyncio.run(source.get_source(file=unit["source_file"], start=0, end=20))
    assert response["found"] is True
    assert "Always review" in response["text"]


def test_existing_output_source_is_not_copied(tmp_path, extraction_stages):
    output_dir = tmp_path / "output"
    input_dir = output_dir / "existing"
    original = input_dir / "chapter.xml"
    _write_input(original)
    result = _extract(input_dir, output_dir)
    assert result.exit_code == 0, result.output
    data = json.loads((output_dir / "legal" / "extraction.json").read_text())
    assert data["units"][0]["source_file"] == "existing/chapter.xml"
    assert not (output_dir / "legal" / "sources").exists()


def test_nested_sources_with_same_name_are_preserved(tmp_path, extraction_stages):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    for folder in ("a", "b"):
        _write_input(
            input_dir / folder / "chapter.xml",
            f"Always review the evidence from folder {folder} before trial.",
        )
    result = _extract(input_dir, output_dir)
    assert result.exit_code == 0, result.output
    data = json.loads((output_dir / "legal" / "extraction.json").read_text())
    assert {unit["source_file"] for unit in data["units"]} == {
        "legal/sources/a/chapter.xml", "legal/sources/b/chapter.xml"
    }
    for folder in ("a", "b"):
        assert (output_dir / "legal" / "sources" / folder / "chapter.xml").read_bytes() == (
            input_dir / folder / "chapter.xml"
        ).read_bytes()


@pytest.mark.parametrize("corpus", ["../escape", "/tmp/cli-source-escape"])
def test_corpus_path_escape_is_rejected(tmp_path, extraction_stages, corpus):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    _write_input(input_dir / "chapter.xml")
    result = _extract(input_dir, output_dir, corpus)
    assert result.exit_code == 1
    assert "outside" in result.output.lower()
    assert not output_dir.exists()


@pytest.mark.parametrize("link_location", ["corpus", "sources", "nested", "file", "input"])
def test_symlink_escape_is_rejected(tmp_path, extraction_stages, link_location):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    outside = tmp_path / "outside"
    outside.mkdir()
    original = input_dir / "nested" / "chapter.xml"
    _write_input(original)
    if link_location == "input":
        external = outside / "external.xml"
        _write_input(external)
        (input_dir / "external.xml").symlink_to(external)
    else:
        destination = {
            "corpus": output_dir / "legal",
            "sources": output_dir / "legal" / "sources",
            "nested": output_dir / "legal" / "sources" / "nested",
            "file": output_dir / "legal" / "sources" / "nested" / "chapter.xml",
        }[link_location]
        destination.parent.mkdir(parents=True, exist_ok=True)
        target = outside / "target.xml" if link_location == "file" else outside
        if link_location == "file":
            target.write_text("Keep this original content.")
        destination.symlink_to(target)
    before = {p: p.read_bytes() for p in outside.rglob("*") if p.is_file()}
    result = _extract(input_dir, output_dir)
    assert result.exit_code == 1, result.output
    assert "outside" in result.output.lower()
    assert {p: p.read_bytes() for p in outside.rglob("*") if p.is_file()} == before


def test_output_inside_input_does_not_reingest_source_copies(tmp_path, extraction_stages):
    input_dir = tmp_path / "input"
    output_dir = input_dir / "output"
    _write_input(input_dir / "chapter.xml")
    result = _extract(input_dir, output_dir)
    assert result.exit_code == 0, result.output
    # A changed input forces a second run and catches recursive source copying.
    _write_input(input_dir / "chapter.xml", "Review the amended evidence before trial.")
    result = _extract(input_dir, output_dir)
    assert result.exit_code == 0, result.output
    data = json.loads((output_dir / "legal" / "extraction.json").read_text())
    assert len(data["units"]) == 1
    assert data["units"][0]["source_file"] == "legal/sources/chapter.xml"
    assert not (output_dir / "legal" / "sources" / "output").exists()


def test_source_endpoint_still_rejects_traversal_and_symlink_escape(tmp_path, monkeypatch):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    external = tmp_path / "private.xml"
    _write_input(external)
    (output_dir / "link.xml").symlink_to(external)
    monkeypatch.setattr(source, "_output_dir", lambda: output_dir)
    for path in ("../private.xml", "link.xml", str(external)):
        response = asyncio.run(source.get_source(file=path, start=0, end=20))
        assert response["found"] is False


async def test_registry_skips_unchanged_original_and_refreshes_changed_source(tmp_path, monkeypatch):
    from folio_insights.config import Settings
    from folio_insights.pipeline.stages.base import InsightsJob
    from folio_insights.pipeline.stages.ingestion import IngestionStage
    from folio_insights.services.corpus_registry import CorpusRegistry

    monkeypatch.setattr("folio_insights.pipeline.stages.ingestion.IngestionBridge", lambda: None)
    monkeypatch.setattr("folio_insights.pipeline.stages.ingestion.MapperBridge", lambda: None)
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    original = input_dir / "chapter.xml"
    _write_input(original)
    stage = IngestionStage(Settings(output_dir=output_dir))
    first = await stage.execute(InsightsJob(corpus_name="legal", source_dir=input_dir))
    registry = CorpusRegistry("legal")
    registry.manifest.documents = first.documents
    registry.save(output_dir / "legal")
    second = await stage.execute(InsightsJob(corpus_name="legal", source_dir=input_dir))
    assert not second.documents
    assert not second.metadata["ingested"]
    _write_input(original, "Review the amended evidence before trial.")
    third = await stage.execute(InsightsJob(corpus_name="legal", source_dir=input_dir))
    assert len(third.documents) == 1
    assert third.documents[0].file_path == "legal/sources/chapter.xml"
    assert (output_dir / third.documents[0].file_path).read_bytes() == original.read_bytes()


def test_legacy_absolute_manifest_is_rewritten(tmp_path, extraction_stages):
    from folio_insights.services.corpus_registry import CorpusRegistry

    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    original = input_dir / "chapter.xml"
    _write_input(original)
    registry = CorpusRegistry("legal")
    registry.mark_processed(original, "xml")
    registry.save(output_dir / "legal")
    assert registry.needs_processing(original) is False

    result = _extract(input_dir, output_dir)
    assert result.exit_code == 0, result.output
    data = json.loads((output_dir / "legal" / "extraction.json").read_text())
    assert data["units"][0]["source_file"] == "legal/sources/chapter.xml"
    assert (output_dir / "legal" / "sources" / "chapter.xml").read_bytes() == original.read_bytes()
    manifest = json.loads((output_dir / "legal" / "corpus-legal.json").read_text())
    assert manifest["documents"][0]["file_path"] == "legal/sources/chapter.xml"
