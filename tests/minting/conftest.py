"""Drain U8 minter test harness: synthetic runs, a fake LLM provider, governed corpora.

Everything is synthetic and lives in pytest temp directories:

* the source text and units are invented litigation-practice prose built in code
  (never committed as fixture files, so ``scripts/check_exclusions.py`` has
  nothing to flag);
* the LLM is the real port + SDK + instructor stack over an ``httpx.MockTransport``
  (``tests.llm.conftest.Recorder``) with a fake key carrying the ``FAKEKEY``
  marker, so a byte scan proves no key leaked;
* signing identities are freshly generated ed25519 ``did:key``s signing at the
  real current time (U6: governance refuses events far from the server clock).
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from folio_insights.llm.templates import CONCEPT, DISTILL
from folio_insights.rubric.oracle import FixtureOracle
from folio_insights.storage import CorpusStorageContext

from tests.llm.conftest import FAKE_KEYS, LEAK_MARKER, Recorder, make_context, make_port
from tests.storage.conftest import Identity, new_identity, role_assertion

ORACLE_PATH = Path(__file__).resolve().parents[1] / "rubric" / "fixtures" / "folio_oracle.json"
F = "https://folio.openlegalstandard.org/"
DAUBERT = F + "RT7xQmfA7w5HT02clIpAe"  # Daubert Motion Practice (branch Service)
ARB = F + "RXO2u2WBkUUcEG1jczLIcA"  # Arbitration Practice (branch Service)
RUN_CORPUS = "synthetic-practice"  # the extraction run's corpus (source namespace)
CORPUS = "mint-corpus"
SOURCE_FILE = "sources/practice.txt"
MODEL = "gpt-4.1-mini"

SOURCE = (
    "Cross-Examination Practice\n\n"
    "Ask only leading questions on cross-examination so the witness can do nothing but agree. "
    "Never ask a hostile witness why, because an open question hands the witness the floor. "
    "Object to hearsay before the answer comes in, not after the jury has heard it.\n"
)
SENTENCES = (
    "Ask only leading questions on cross-examination so the witness can do nothing but agree.",
    "Never ask a hostile witness why, because an open question hands the witness the floor.",
    "Object to hearsay before the answer comes in, not after the jury has heard it.",
)
# Fluent, plausible, and NOT in the source: partial ratio 0.6184 against SOURCE (AE1).
FABRICATED = "Use leading questions on redirect so the jury hears the witness agree twice."
HEADING = "Cross-Examination Practice"


def ruler_tag(iri: str = DAUBERT, confidence: float = 0.9) -> dict[str, Any]:
    return {"iri": iri, "label": "synthetic concept", "confidence": confidence,
            "extraction_path": "entity_ruler", "branch": ""}


def llm_tag(iri: str = ARB, judge_status: str | None = "judged",
            confidence: float = 0.8) -> dict[str, Any]:
    return {"iri": iri, "label": "synthetic concept", "confidence": confidence,
            "extraction_path": "llm", "branch": "", "judge_status": judge_status}


def lineage(*, concept: bool = False) -> list[dict[str, Any]]:
    events = [
        {"stage": "boundary_detection", "action": "split", "detail": "method=structural"},
        {"stage": "distiller", "action": "distill", "detail": "distilled",
         "template_id": DISTILL.id, "template_hash": DISTILL.hash},
        {"stage": "folio_tagger", "action": "tag", "detail": "1 concepts",
         **({"template_id": CONCEPT.id, "template_hash": CONCEPT.hash} if concept else {})},
    ]
    return events


def unit(
    uid: str,
    sentence: str,
    *,
    text: str | None = None,
    snippet: str | None = None,
    span: tuple[int, int] | None = None,
    anchor_score: float = 1.0,
    anchor_verified: bool = True,
    tags: list[dict[str, Any]] | None = None,
    unit_type: str = "advice",
    events: list[dict[str, Any]] | None = None,
    cross_references: list[str] | None = None,
    section: tuple[str, ...] = ("Cross-Examination Practice",),
    source: str = SOURCE,
) -> dict[str, Any]:
    """A KnowledgeUnit dict anchored on ``sentence`` (its exact span, unless given)."""
    if span is None:
        start = source.index(sentence)
        span = (start, start + len(sentence))
    body = text if text is not None else sentence
    return {
        "id": uid,
        "text": body,
        "original_span": {"start": span[0], "end": span[1], "source_file": SOURCE_FILE},
        "source_snippet": snippet if snippet is not None else source[span[0]:span[1]],
        "anchor_verified": anchor_verified,
        "anchor_score": anchor_score,
        "unit_type": unit_type,
        "source_file": SOURCE_FILE,
        "source_section": list(section),
        "folio_tags": tags if tags is not None else [ruler_tag()],
        "confidence": 0.9,
        "content_hash": hashlib.sha256(body.encode()).hexdigest(),
        "lineage": events if events is not None else lineage(),
        "cross_references": cross_references or [],
    }


def write_run(tmp: Path, units: list[dict[str, Any]], *, b9: bool = True,
              source: str = SOURCE) -> tuple[Path, Path]:
    """``extraction.json`` + a sources directory holding ``SOURCE_FILE``."""
    src = tmp / "ingested"
    (src / SOURCE_FILE).parent.mkdir(parents=True, exist_ok=True)
    (src / SOURCE_FILE).write_text(source, encoding="utf-8")
    tagger: dict[str, Any] = {"deterministic_iri_path": "active", "judge_enabled": True}
    if b9:
        tagger["carried_iris_rejected"] = 0
    run = tmp / "extraction.json"
    run.write_text(json.dumps({
        "corpus": RUN_CORPUS,
        "total_units": len(units),
        "units": units,
        "summary": {
            "folio_tagger": tagger,
            "llm": {"calls": 1, "by_task": [
                {"task": "distiller", "provider": "openai", "model": MODEL, "calls": 1},
            ], "templates": {DISTILL.id: DISTILL.hash}},
        },
    }), encoding="utf-8")
    return run, src


# ── the fake provider ────────────────────────────────────────────────────


def default_fields(**overrides: Any) -> dict[str, Any]:
    fields = {
        "sense": {"value": "Leading questions keep a cross-examination under control.",
                  "confidence": 0.92},
        "reference": {"value": "cross-examination technique", "confidence": 0.88},
        "logical_form_imputed": {"value": "SHOULD(examiner, ask_leading, cross)",
                                 "confidence": 0.8},
        "layer": {"value": "L2_composed", "confidence": 0.75},
        "predication_mode": {"value": "per_accidens", "confidence": 0.7},
        "fork": {"value": "synthetic_a_posteriori", "confidence": 0.85},
        "speech_act": {"value": "practitioner_advice", "confidence": 0.95},
    }
    for name, value in overrides.items():
        fields[name] = value
    return fields


def tool_response(name: str, arguments: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json={
        "choices": [{
            "finish_reason": "tool_calls", "index": 0,
            "message": {"content": None, "role": "assistant", "tool_calls": [{
                "function": {"arguments": json.dumps(arguments), "name": name},
                "id": "call_0", "type": "function",
            }]},
        }],
        "created": 1759622400, "id": "chatcmpl-synthetic-mint",
        "model": "gpt-4.1-mini-2025-04-14", "object": "chat.completion",
        "usage": {"completion_tokens": 37, "prompt_tokens": 412, "total_tokens": 449},
    })


@dataclass
class FakeProvider:
    """Answers ``MintFieldsOutput`` calls; anything else is a test failure."""

    fields: Callable[[dict[str, Any]], dict[str, Any]] = field(
        default=lambda _body: default_fields())
    recorder: Recorder = field(init=False)

    def __post_init__(self) -> None:
        self.recorder = Recorder([self._answer])

    def _answer(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        name = body["tools"][0]["function"]["name"]
        if name != "MintFieldsOutput":
            return httpx.Response(400, json={"error": {"message": f"unexpected {name}"}})
        return tool_response(name, self.fields(body))

    @property
    def requests(self) -> list[httpx.Request]:
        return self.recorder.requests

    def port(self):  # noqa: ANN201
        return make_port(self.recorder)

    def context(self):  # noqa: ANN201
        return make_context("openai", MODEL)


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def oracle() -> FixtureOracle:
    return FixtureOracle.from_file(ORACLE_PATH)


@pytest.fixture(autouse=True)
def _isolated_llm_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import os

    for name in list(os.environ):
        if name.startswith("LLM_") and (name.endswith("_PROVIDER") or name.endswith("_MODEL")):
            monkeypatch.delenv(name, raising=False)
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FOLIO_INSIGHTS_QUEUE_DB", str(tmp_path / "queue.sqlite3"))


# ── governed corpora ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class Governed:
    root: Path
    corpus: str
    admin: Identity
    extractor: Identity


async def governed_corpus(root: Path, corpus: str = CORPUS) -> Governed:
    """A corpus whose genesis admin granted a separate identity the extractor role."""
    admin, extractor = new_identity(), new_identity()
    ctx = await CorpusStorageContext.open(root, corpus)
    try:
        now = datetime.now(UTC)
        await ctx.governance.append(role_assertion(corpus, admin, admin.did, "corpus_admin", now))
        await ctx.governance.append(
            role_assertion(corpus, admin, extractor.did, "extractor", datetime.now(UTC)))
    finally:
        await ctx.close()
    return Governed(root, corpus, admin, extractor)


def scan_for(root: Path, needles: list[bytes]) -> list[str]:
    """Every file under ``root`` containing any needle (path names only)."""
    hits = []
    for path in root.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            if any(n in data for n in needles):
                hits.append(str(path.relative_to(root)))
    return hits


__all__ = [
    "ARB", "CORPUS", "DAUBERT", "FABRICATED", "FAKE_KEYS", "HEADING", "LEAK_MARKER", "MODEL",
    "RUN_CORPUS", "SENTENCES", "SOURCE", "SOURCE_FILE", "FakeProvider", "Governed",
    "default_fields", "governed_corpus", "lineage", "llm_tag", "ruler_tag", "scan_for", "unit",
    "write_run",
]
