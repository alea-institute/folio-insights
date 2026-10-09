"""Rubric harness test helpers: synthetic units, runs and shard corpora.

Everything is synthetic and built in temp directories: invented litigation-practice
prose, generated did:key identities (``tests.storage.conftest``), the frozen fixture
oracle. No operator key, credential or book text is read.
"""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from folio_insights.identity import sign_attestation
from folio_insights.revision.content_edit import canonical_content_hash
from folio_insights.rubric.oracle import FixtureOracle
from folio_insights.storage import CorpusStorageContext

from tests.storage.conftest import new_identity, shard

FIXTURES = Path(__file__).parent / "fixtures"
GOLD_DIR = FIXTURES / "books_gold"
ORACLE_PATH = FIXTURES / "folio_oracle.json"

F = "https://folio.openlegalstandard.org/"
DAUBERT = F + "RT7xQmfA7w5HT02clIpAe"  # Daubert Motion Practice (Service)
RUSSIA = F + "R53E5e3A8871d86E4f7D1166"  # Russian Federation (Location)
CROSS = F + "RCz1SYWoNDDTDvPr0kSJBq"  # Cross-Examination of Witness (Event, Service)
ARB = F + "RXO2u2WBkUUcEG1jczLIcA"  # Arbitration Practice (Service)
SYNTHETIC_IRI = F + "SYNTHETIC-NOT-A-REAL-CONCEPT"

SOURCE = (
    "Witness Preparation\n\n"
    "Meet the witness a week before trial and review every exhibit together. "
    "Keep each question on cross short, and confine it to a single fact the witness "
    "must admit. Ask leading questions so the witness can only agree.\n"
)
SOURCE_FILE = "prep.txt"


@pytest.fixture
def oracle() -> FixtureOracle:
    return FixtureOracle.from_file(ORACLE_PATH)


def tag(iri: str, label: str = "concept", branch: str = "", path: str = "entity_ruler") -> dict:
    return {"iri": iri, "label": label, "confidence": 0.8, "extraction_path": path,
            "branch": branch}


def unit(
    uid: str,
    text: str,
    *,
    span: tuple[int, int] | None = None,
    source: str = SOURCE,
    source_file: str = SOURCE_FILE,
    tags: list[dict] | None = None,
    snippet: str | None = None,
    anchor_score: float | None = None,
    anchor_verified: bool | None = None,
    content_hash: str | None = None,
) -> dict[str, Any]:
    """A KnowledgeUnit dict. ``span=None`` anchors ``text`` exactly where it occurs."""
    if span is None:
        start = source.index(text)
        span = (start, start + len(text))
    data: dict[str, Any] = {
        "id": uid,
        "text": text,
        "original_span": {"start": span[0], "end": span[1], "source_file": source_file},
        "unit_type": "advice",
        "source_file": source_file,
        "source_section": ["Witness Preparation"],
        "folio_tags": tags or [],
        "confidence": 0.9,
        "content_hash": content_hash or hashlib.sha256(text.encode()).hexdigest(),
    }
    if snippet is not None:
        data["source_snippet"] = snippet
    if anchor_score is not None:
        data["anchor_score"] = anchor_score
    if anchor_verified is not None:
        data["anchor_verified"] = anchor_verified
    return data


def write_run(tmp: Path, units: list[dict], sources: dict[str, str] | None = None) -> tuple[Path, Path]:
    """Write ``extraction.json`` and a sources directory; return both paths."""
    src_dir = tmp / "sources"
    src_dir.mkdir(parents=True, exist_ok=True)
    for name, text in (sources if sources is not None else {SOURCE_FILE: SOURCE}).items():
        (src_dir / name).write_text(text, encoding="utf-8")
    run = tmp / "extraction.json"
    run.write_text(json.dumps({"corpus": "synthetic", "units": units}), encoding="utf-8")
    return run, src_dir


def judged_all(score: float = 3, *, unit_ids: list[str], **overrides: Any) -> dict[str, Any]:
    """A judged-scores object covering all nine judged criteria and the [LLM] half of the
    RUB-EXTRACT-05 gate (every anchored passage supports its claim, graded 3 per unit),
    without which no story is publishable."""
    scores: dict[str, Any] = {
        "RUB-EXTRACT-01": score, "RUB-EXTRACT-02": score, "RUB-EXTRACT-04": score,
        "RUB-EXTRACT-05": {"per_unit": {uid: 3 for uid in unit_ids}},
        "RUB-EXTRACT-06": {"per_unit": {uid: 3 for uid in unit_ids}},
        "RUB-EXTRACT-07": score, "RUB-EXTRACT-08": score, "RUB-EXTRACT-12": score,
        "RUB-EXTRACT-13": score, "RUB-EXTRACT-14": score,
    }
    scores.update(overrides)
    return {"format": 1, "rubric_version": "v1.0", "judge": "synthetic test judge",
            "scores": scores}


SHARD_SPANS = (
    "Meet the witness a week before trial and review every exhibit together.",
    "Keep each question on cross short, and confine it to a single fact the witness must admit.",
)
SHARD_SENSES = (
    "Prepare witnesses well before trial.",
    "Cross-examination questions should each establish one fact.",
)


def signed(s: Any, signer: Any) -> Any:
    s.signatures.append(sign_attestation(
        canonical_content_hash(s), signer.sk, signer.did, "extract",
        signing_key_id=signer.key_id, did_doc_snapshot_at=None,
        now=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
    ))
    return s


async def build_corpus(
    root: Path,
    corpus: str = "rubric-corpus",
    *,
    spans: tuple[str, ...] = SHARD_SPANS,
    senses: tuple[str, ...] = SHARD_SENSES,
    reference: str = CROSS,
    sign: bool = True,
    extra: dict[int, dict[str, Any]] | None = None,
) -> list[Any]:
    """Ingest one synthetic shard per span (source ``urn:synthetic:source/prep.txt``)."""
    signer = new_identity()
    shards = []
    for n, (span, sense) in enumerate(zip(spans, senses, strict=True), start=1):
        fields = {"source_uri": f"urn:synthetic:source/{SOURCE_FILE}", "source_span": span,
                  "sense": sense, "reference": reference, **(extra or {}).get(n, {})}
        s = shard(n, **fields)
        # The storage fixture's generic triple states an unrelated example claim.
        # This corpus exercises grounded assertions about these synthetic passages.
        s = s.model_copy(update={"triple": s.triple.model_copy(update={
            "object": span, "object_datatype": "http://www.w3.org/2001/XMLSchema#string",
        })})
        shards.append(signed(s, signer) if sign else s)
    ctx = await CorpusStorageContext.open(root, corpus)
    try:
        await ctx.ingest_shards(shards)
    finally:
        await ctx.close()
    return shards
