"""Tests for the ingestion and structure parser stages.

Ingestion runs folio-enrich's document readers, so the tests that ingest are
marked ``integration`` (folio-enrich on disk), like ``tests/test_bridge.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from folio_insights.pipeline.stages.base import InsightsJob
from folio_insights.pipeline.stages.ingestion import IngestionStage
from folio_insights.pipeline.stages.structure_parser import (
    StructureParserStage,
    _build_structured_elements,
)
from folio_insights.services.corpus_registry import CorpusRegistry


@pytest.fixture
def ingestion_job(tmp_path: Path) -> InsightsJob:
    """Create an InsightsJob pointing at a temp directory."""
    return InsightsJob(
        corpus_name="test",
        source_dir=tmp_path,
    )


def _make_md_file(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


@pytest.mark.integration
async def test_ingest_directory(tmp_path: Path):
    """Create temp dir with 2 .md files and 1 .txt file, verify all ingested."""
    (tmp_path / "chapter1.md").write_text(
        "# Chapter 1\n\nFirst paragraph.\n\n## Section A\n\nContent here.\n",
        encoding="utf-8",
    )
    (tmp_path / "chapter2.md").write_text(
        "# Chapter 2\n\nSecond chapter.\n",
        encoding="utf-8",
    )
    (tmp_path / "notes.txt").write_text(
        "Important note about trial preparation.\n",
        encoding="utf-8",
    )

    job = InsightsJob(corpus_name="test", source_dir=tmp_path)
    stage = IngestionStage()
    result = await stage.execute(job)

    assert len(result.documents) == 3
    for doc in result.documents:
        assert doc.content_hash, f"Missing content_hash for {doc.file_path}"
        assert doc.format in ("markdown", "plain_text")

    # Verify ingested metadata exists
    ingested = result.metadata["ingested"]
    assert len(ingested) == 3


@pytest.mark.integration
async def test_preserve_structure(tmp_path: Path):
    """Verify heading hierarchy is preserved through ingestion + structure parsing."""
    md_content = (
        "# Depositions\n\n"
        "Opening paragraph about depositions.\n\n"
        "## Expert Witnesses\n\n"
        "Lock expert into reviewed-document list.\n\n"
        "### Methodology Challenges\n\n"
        "Challenge the methodology used by the expert.\n\n"
        "- Always verify credentials\n"
        "- Check publication record\n"
    )
    (tmp_path / "depo.md").write_text(md_content, encoding="utf-8")

    job = InsightsJob(corpus_name="test", source_dir=tmp_path)

    # Run ingestion
    ingestion = IngestionStage()
    job = await ingestion.execute(job)

    # Run structure parser
    parser = StructureParserStage()
    job = await parser.execute(job)

    structured = job.metadata["structured"]
    assert len(structured) == 1

    file_key = list(structured.keys())[0]
    elements = structured[file_key]

    # Find the paragraph "Challenge the methodology..."
    methodology_paras = [
        e for e in elements
        if "Challenge the methodology" in e.get("text", "")
    ]
    assert len(methodology_paras) >= 1

    # The section_path should include "Expert Witnesses" or "Methodology Challenges"
    # depending on the ingestor's heading detection
    para = methodology_paras[0]
    section_path = para.get("section_path", [])
    # At minimum the structure parser should have some heading context
    assert len(section_path) >= 1, f"Expected heading context, got: {section_path}"


@pytest.mark.integration
async def test_variable_length(tmp_path: Path):
    """Files of 50 chars and 50K chars both ingest without error."""
    # Short file
    (tmp_path / "short.md").write_text("# Short\n\nBrief note.\n", encoding="utf-8")

    # Long file (~50K chars)
    long_content = "# Long Document\n\n"
    long_content += ("This is a paragraph with substantial legal content. " * 20 + "\n\n") * 50
    (tmp_path / "long.md").write_text(long_content, encoding="utf-8")

    job = InsightsJob(corpus_name="test", source_dir=tmp_path)
    stage = IngestionStage()
    result = await stage.execute(job)

    assert len(result.documents) == 2

    ingested = result.metadata["ingested"]
    texts = [v["text"] for v in ingested.values()]
    lengths = sorted(len(t) for t in texts)

    # Short file should be small
    assert lengths[0] < 100
    # Long file should be large
    assert lengths[1] > 10000


@pytest.mark.integration
async def test_skip_processed(tmp_path: Path):
    """Process a file, then re-run -- verify it is skipped on second run."""
    (tmp_path / "once.md").write_text("# Once\n\nProcess me once.\n", encoding="utf-8")

    job1 = InsightsJob(corpus_name="test", source_dir=tmp_path)
    stage = IngestionStage()
    result1 = await stage.execute(job1)
    assert len(result1.documents) == 1

    # Second run with a fresh job should still find the file,
    # but the corpus_registry within the stage instance is ephemeral.
    # This test verifies the registry logic itself.
    registry = CorpusRegistry("test-skip")
    file_path = tmp_path / "once.md"

    # First check: needs processing
    assert registry.needs_processing(file_path) is True

    # Mark as processed
    registry.mark_processed(file_path, "markdown")

    # Second check: does NOT need processing
    assert registry.needs_processing(file_path) is False


async def test_xml_ingestion(tmp_path: Path):
    """Create a simple XML file and verify text content is extracted."""
    xml_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<document>\n"
        "  <title>Legal Analysis</title>\n"
        "  <section>\n"
        "    <heading>Introduction</heading>\n"
        "    <paragraph>This is the introductory text.</paragraph>\n"
        "  </section>\n"
        "</document>\n"
    )
    (tmp_path / "analysis.xml").write_text(xml_content, encoding="utf-8")

    job = InsightsJob(corpus_name="test", source_dir=tmp_path)
    stage = IngestionStage()
    result = await stage.execute(job)

    assert len(result.documents) == 1
    assert result.documents[0].format == "xml"

    ingested = result.metadata["ingested"]
    file_key = list(ingested.keys())[0]
    text = ingested[file_key]["text"]
    assert "Legal Analysis" in text
    assert "introductory text" in text


@pytest.fixture
def no_enrich_checkout(monkeypatch, tmp_path: Path):
    """Point the enrich path at a missing directory and reset the cached path flag."""
    from folio_insights.config import get_settings
    from folio_insights.services.bridge import folio_bridge

    monkeypatch.setattr(get_settings(), "folio_enrich_path", tmp_path / "no-enrich")
    monkeypatch.setattr(folio_bridge, "_path_ensured", False)


async def test_tabular_and_xml_corpus_never_builds_ingestion_bridge(
    tmp_path: Path, monkeypatch, no_enrich_checkout
):
    """CSV/TSV/XML corpora ingest without a folio-enrich checkout (bridge built lazily)."""
    from folio_insights.services.bridge import mapper_bridge

    monkeypatch.setattr(mapper_bridge, "_mapper_checked", True)
    monkeypatch.setattr(mapper_bridge, "_mapper_path", None)
    src = tmp_path / "src"
    src.mkdir()
    (src / "rules.csv").write_text("Rule,Source\nHearsay,FRE 802\n", encoding="utf-8")
    (src / "rules.tsv").write_text("Rule\tSource\nRelevance\tFRE 401\n", encoding="utf-8")
    (src / "doc.xml").write_text("<doc><p>Hello XML.</p></doc>", encoding="utf-8")

    result = await IngestionStage().execute(InsightsJob(corpus_name="test", source_dir=src))

    assert sorted(d.format for d in result.documents) == ["csv", "tsv", "xml"]
    texts = "\n".join(v["text"] for v in result.metadata["ingested"].values())
    assert "Hearsay | FRE 802" in texts and "Relevance | FRE 401" in texts
    assert "Hello XML." in texts


async def test_bridge_format_without_checkout_fails_fast(tmp_path: Path, no_enrich_checkout):
    """A corpus that needs the bridge still aborts up front, with the actionable error."""
    from folio_insights.services.bridge.ingestion_bridge import IngestionBridgeUnavailableError

    src = tmp_path / "src"
    src.mkdir()
    (src / "chapter.md").write_text("# Title\n\nBody.\n", encoding="utf-8")
    (src / "rules.csv").write_text("a,b\n", encoding="utf-8")

    with pytest.raises(IngestionBridgeUnavailableError, match="FOLIO_INSIGHTS_FOLIO_ENRICH_PATH"):
        await IngestionStage().execute(InsightsJob(corpus_name="test", source_dir=src))


async def test_unknown_format_skipped(tmp_path: Path):
    """A .xyz file should be skipped without error."""
    (tmp_path / "mystery.xyz").write_text("Unknown format content", encoding="utf-8")

    job = InsightsJob(corpus_name="test", source_dir=tmp_path)
    stage = IngestionStage()
    result = await stage.execute(job)

    # .xyz is not in SUPPORTED_EXTENSIONS, so nothing should be ingested
    assert len(result.documents) == 0


def test_build_structured_elements():
    """Unit test for the structure building logic."""
    elements = [
        {"text": "Depositions", "element_type": "heading", "level": 1},
        {"text": "Opening paragraph.", "element_type": "paragraph", "level": None},
        {"text": "Expert Witnesses", "element_type": "heading", "level": 2},
        {"text": "Lock expert into list.", "element_type": "paragraph", "level": None},
        {"text": "Methodology Challenges", "element_type": "heading", "level": 3},
        {"text": "Challenge the methodology.", "element_type": "paragraph", "level": None},
        {"text": "Always verify credentials", "element_type": "list_item", "level": None},
    ]

    result = _build_structured_elements(elements)

    assert len(result) == 7

    # Heading "Depositions" should have section_path = ["Depositions"]
    assert result[0].element_type == "heading"
    assert result[0].section_path == ["Depositions"]

    # Paragraph after h1 should inherit ["Depositions"]
    assert result[1].section_path == ["Depositions"]

    # Paragraph under h2 should inherit ["Depositions", "Expert Witnesses"]
    assert result[3].section_path == ["Depositions", "Expert Witnesses"]

    # Paragraph under h3 should inherit full path
    assert result[5].section_path == ["Depositions", "Expert Witnesses", "Methodology Challenges"]

    # List item should also inherit full path
    assert result[6].element_type == "list_item"
    assert result[6].section_path == ["Depositions", "Expert Witnesses", "Methodology Challenges"]

    # All elements should have valid offsets
    for elem in result:
        assert elem.char_offset_end > elem.char_offset_start
