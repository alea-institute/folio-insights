"""Extraction safeguards transferred in governance plan U3 (B6, B7, RUB-05, binary re-read).

* B6: ``is_structural`` keeps heading, contents and attribution lines out of unit-ization
  (shape only), and ``is_substantive`` adds the distiller's small length floor.
* RUB-05: every unit carries a verifiable anchor (span, exact snippet, score) into the
  ingested source text.
* B7: long paragraphs are refined concurrently under a bound, Tier-3 LLM refinement is
  opt-in, and a deterministic sentence-group split caps unit size without dropping text.
* Ingestion builds fallback elements from the bridge-extracted text, never from the raw
  bytes of a binary container.

Every text here is invented for the tests.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from folio_insights.config import Settings, get_settings
from folio_insights.models.knowledge_unit import KnowledgeType, KnowledgeUnit, Span
from folio_insights.pipeline.stages.base import InsightsJob
from folio_insights.pipeline.stages.boundary_detection import BoundaryDetectionStage
from folio_insights.services.anchoring import MIN_ANCHOR_SCORE, resolve_anchor
from folio_insights.services.boundary.structural import Boundary
from folio_insights.services.substance import (
    MIN_SUBSTANTIVE_CHARS,
    is_structural,
    is_substantive,
)

SUBSTANTIVE = [
    "Confirm the synthetic filing deadline with the clerk before the hearing begins.",
    "Never let a synthetic witness guess: ask them to say they do not know instead.",
    "A short rule still counts when it reads like a sentence; keep it whole.",
    "1. Always confirm the synthetic deadline with the clerk before filing.",  # numbered advice
]
# Short genuine advice and enumerated tips (review P2-5): never structural, and above the
# distiller's 20-character floor.
SHORT_ADVICE = [
    "Never lead on direct examination.",
    "Always object before the witness answers.",
    "Do not ask a question you cannot answer.",
    "1. Ask only leading questions on cross-examination",
    "2. Keep every question to one fact",
    "a) Object to hearsay before the answer comes in",
    "- Never argue with the judge in front of the jury",
    "Section 1983 claims require state action and a deprivation of a federal right",
    "Rule 12(b)(6) motions test the pleadings, not the evidence.",
    "IV. The court must find good cause before granting leave to amend",
    "Short line that is still advice.",
]
NOT_SUBSTANTIVE = [
    "B. Synthetic Topic Heading",                         # enumerated heading
    "B. Synthetic Topic",                                  # short enumerated heading
    "Chapter 7 Synthetic Hearing Practice Overview",      # structural word, no punctuation
    "IV. Preparing The Synthetic Record For Review",      # roman numeral heading
    "Rule 403 Excludes Unfairly Prejudicial Evidence",    # title-cased rule heading
    "Preserve Every Objection For The Appellate Record",  # title-case line
    "— A. Synthetic Author Name",                         # attribution line
    "The Craft Of Synthetic Courtroom Questioning Today",  # title-case line
    "N/A",                                                 # no words
    "12 ............................................ 345",  # contents dots and page numbers
    "Synthetic Discovery Deadlines 42",                    # contents entry with page number
]


@pytest.fixture(autouse=True)
def _fresh_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ---------- B6: substance ----------


@pytest.mark.parametrize("text", SUBSTANTIVE + SHORT_ADVICE)
def test_substantive_prose_is_kept(text):
    assert not is_structural(text)
    assert is_substantive(text)


@pytest.mark.parametrize("text", NOT_SUBSTANTIVE)
def test_structural_lines_are_not_substantive(text):
    assert is_structural(text)
    assert not is_substantive(text)


def test_length_floor_applies_only_to_the_distiller():
    text = "Ask one question."
    assert len(text) < MIN_SUBSTANTIVE_CHARS == 20
    assert not is_structural(text)  # boundary detection keeps it
    assert not is_substantive(text)  # the distiller skips it
    assert is_substantive(text, min_chars=10)
    assert not is_substantive("", 0) and not is_substantive(None)  # type: ignore[arg-type]


async def test_boundary_detection_keeps_short_advice_and_enumerated_tips():
    """Review P2-5: boundaries are dropped by shape only, never by length."""
    job = await BoundaryDetectionStage().execute(_job(SHORT_ADVICE[:6] + [NOT_SUBSTANTIVE[1]]))
    assert [u.text for u in job.units] == SHORT_ADVICE[:6]
    assert job.metadata["boundary_detection"]["skipped_non_substantive"] == 1


# ---------- RUB-05: anchoring ----------


def test_exact_anchor_is_verified_with_a_real_span():
    source = "Intro line.\n\nAlways file the synthetic notice early. Then wait."
    unit = "Always file the synthetic notice early."
    anchor = resolve_anchor(unit, source)
    assert anchor is not None and anchor.verified and anchor.score == 1.0
    assert source[anchor.start:anchor.end] == unit == anchor.snippet


def test_near_anchor_is_verified_and_span_matches_snippet():
    source = "Preface.\n\nAlways  file the synthetic notice early, then wait for the reply."
    unit = "Always file the synthetic notice early, then wait for the reply."
    anchor = resolve_anchor(unit, source)
    assert anchor is not None and anchor.verified
    assert MIN_ANCHOR_SCORE <= anchor.score < 1.0
    assert source[anchor.start:anchor.end] == anchor.snippet


def test_unrelated_text_is_returned_unverified_and_empty_input_is_none():
    source = "Completely different synthetic material about lanterns and docks."
    anchor = resolve_anchor("Quorum widgets require zephyr filings.", source)
    assert anchor is not None and not anchor.verified
    assert source[anchor.start:anchor.end] == anchor.snippet
    assert resolve_anchor("", source) is None
    assert resolve_anchor("anything", "") is None


# ---------- boundary detection: B6 + RUB-05 + B7 ----------


def _element(text: str, start: int, kind: str = "paragraph") -> dict:
    return {
        "text": text,
        "element_type": kind,
        "section_path": ["Synthetic Part"],
        "level": 1 if kind == "heading" else 0,
        "char_offset_start": start,
        "char_offset_end": start + len(text),
    }


def _job(paragraphs: list[str], *, ingested: bool = True) -> InsightsJob:
    elements, offset = [], 0
    for text in paragraphs:
        elements.append(_element(text, offset))
        offset += len(text) + 2
    metadata = {"structured": {"synthetic.md": elements}}
    if ingested:
        metadata["ingested"] = {"synthetic.md": {"text": "\n\n".join(paragraphs)}}
    return InsightsJob(corpus_name="synthetic", source_dir=Path("/nonexistent"), metadata=metadata)


async def test_non_substantive_boundaries_are_dropped_and_counted():
    job = await BoundaryDetectionStage().execute(_job([SUBSTANTIVE[0], NOT_SUBSTANTIVE[0],
                                                       NOT_SUBSTANTIVE[3], SUBSTANTIVE[1]]))
    assert [u.text for u in job.units] == [SUBSTANTIVE[0], SUBSTANTIVE[1]]
    assert job.metadata["boundary_detection"]["skipped_non_substantive"] == 2


async def test_units_carry_verified_anchors_into_the_ingested_text():
    paragraphs = [SUBSTANTIVE[0], SUBSTANTIVE[1]]
    job = await BoundaryDetectionStage().execute(_job(paragraphs))
    source = "\n\n".join(paragraphs)
    for unit in job.units:
        assert unit.anchor_verified and unit.anchor_score == 1.0
        span = unit.original_span
        assert source[span.start:span.end] == unit.source_snippet == unit.text


async def test_units_without_ingested_text_keep_offsets_unverified():
    job = await BoundaryDetectionStage().execute(_job([SUBSTANTIVE[2]], ingested=False))
    (unit,) = job.units
    assert not unit.anchor_verified and unit.source_snippet == "" and unit.anchor_score == 0.0


def _long_paragraph(n: int = 12) -> str:
    return " ".join(
        f"Synthetic sentence number {i} explains one more step of the invented procedure."
        for i in range(n)
    )


async def test_long_paragraph_splits_deterministically_without_llm(monkeypatch):
    stage = BoundaryDetectionStage()

    async def _no_tier2(boundary):  # noqa: ARG001
        return None

    async def _tier3_must_not_run(boundary):  # noqa: ARG001
        raise AssertionError("Tier 3 is opt-in and must not run by default")

    monkeypatch.setattr(stage, "_run_tier2", _no_tier2)
    monkeypatch.setattr(stage, "_run_tier3", _tier3_must_not_run)
    paragraph = _long_paragraph()
    job = await stage.execute(_job([paragraph]))
    cap = get_settings().boundary_max_unit_chars
    assert len(job.units) > 1
    assert all(len(u.text) <= cap for u in job.units)
    # Content-preserving: the units are the paragraph's sentences, in order.
    assert " ".join(u.text for u in job.units) == paragraph
    assert all(any(e.detail == "method=sentence_group" for e in u.lineage) for u in job.units)
    assert all(u.anchor_verified for u in job.units)


async def test_tier3_runs_only_when_enabled(monkeypatch):
    monkeypatch.setenv("FOLIO_INSIGHTS_BOUNDARY_LLM_REFINE", "true")
    get_settings.cache_clear()
    stage = BoundaryDetectionStage()
    calls = []

    async def _no_tier2(boundary):  # noqa: ARG001
        return None

    async def _tier3(boundary):
        calls.append(boundary.text)
        half = len(boundary.text) // 2
        return [
            Boundary(start=boundary.start, end=boundary.start + half, source_file=boundary.source_file,
                     text=boundary.text[:half], section_path=boundary.section_path,
                     confidence=0.7, method="llm"),
            Boundary(start=boundary.start + half, end=boundary.end, source_file=boundary.source_file,
                     text=boundary.text[half:], section_path=boundary.section_path,
                     confidence=0.7, method="llm"),
        ]

    monkeypatch.setattr(stage, "_run_tier2", _no_tier2)
    monkeypatch.setattr(stage, "_run_tier3", _tier3)
    await stage.execute(_job([_long_paragraph(8)]))
    assert len(calls) == 1


async def test_ambiguous_paragraphs_are_refined_concurrently_under_the_bound(monkeypatch):
    monkeypatch.setenv("FOLIO_INSIGHTS_BOUNDARY_TIER_CONCURRENCY", "3")
    get_settings.cache_clear()
    stage = BoundaryDetectionStage()
    active = peak = 0

    async def _slow_tier2(boundary):  # noqa: ARG001
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1
        return None

    monkeypatch.setattr(stage, "_run_tier2", _slow_tier2)
    paragraphs = [_long_paragraph(8).replace("number", f"group {g} number") for g in range(7)]
    job = await stage.execute(_job(paragraphs))
    assert peak == 3  # concurrent, and never above the bound
    # Order is preserved across the concurrent refinement.
    firsts = [u.text for u in job.units if u.text.startswith("Synthetic sentence group")]
    groups = [int(t.split()[3]) for t in firsts if t.split()[4] == "number" and t.split()[5] == "0"]
    assert groups == sorted(groups) == list(range(7))


def test_settings_defaults():
    s = Settings()
    assert s.boundary_llm_refine is False
    assert s.boundary_tier_concurrency == 8
    assert s.boundary_max_unit_chars == 600
    assert s.min_substantive_chars == MIN_SUBSTANTIVE_CHARS
    assert s.require_deterministic_iri is True


# ---------- distiller defence in depth ----------


async def test_distiller_skips_non_substantive_units_without_a_model_call():
    from folio_insights.pipeline.stages.distiller import DistillerStage

    class _NoLLM:
        def get_llm_for_task(self, task):  # noqa: ARG002
            raise AssertionError("a non-substantive unit must not reach the model")

    unit = KnowledgeUnit(
        text=NOT_SUBSTANTIVE[0],
        original_span=Span(start=0, end=10, source_file="synthetic.md"),
        unit_type=KnowledgeType.ADVICE,
        source_file="synthetic.md",
    )
    await DistillerStage()._distill_unit(unit, _NoLLM())
    assert unit.text == NOT_SUBSTANTIVE[0]
    assert unit.lineage[-1].action == "distill_skipped"


# ---------- ingestion: elementless bridge output on a binary container ----------


async def test_elementless_docx_uses_bridge_text_not_raw_bytes(tmp_path, monkeypatch):
    from folio_insights.pipeline.stages.ingestion import IngestionStage

    source = tmp_path / "input"
    source.mkdir()
    (source / "synthetic.docx").write_bytes(b"PK\x03\x04" + b"\x00binary-container" * 50)
    extracted = f"{SUBSTANTIVE[0]}\n\n{SUBSTANTIVE[1]}"

    class _Bridge:
        def detect_and_ingest(self, path):  # noqa: ARG002
            return extracted, []  # text, but no structural elements (like the Word ingestor)

    monkeypatch.setattr("folio_insights.pipeline.stages.ingestion.IngestionBridge", _Bridge)
    monkeypatch.setattr("folio_insights.pipeline.stages.ingestion.MapperBridge", lambda: None)
    stage = IngestionStage(Settings(output_dir=tmp_path / "out"))
    job = await stage.execute(InsightsJob(corpus_name="synthetic", source_dir=source))
    (data,) = job.metadata["ingested"].values()
    assert [e["text"] for e in data["elements"]] == [SUBSTANTIVE[0], SUBSTANTIVE[1]]
    assert all("PK" not in e["text"] and "\x00" not in e["text"] for e in data["elements"])
