"""bridge-ingest fixtures: synthetic enrich records and a disposable storage root.

All data is synthetic. ``FIXTURE_RECORD`` is the committed enrich export the
end-to-end test drives; replacing that file with a real export needs no code
change.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from folio_propositions import (
    ActorRef,
    GeneratorInfo,
    Proposition,
    PropositionDocumentRecord,
    stamp_content_iris,
)

FIXTURE_RECORD = Path(__file__).parent / "fixtures" / "enrich-propositions-record.json"
SOURCE_URI = "https://opinions.example.org/synthetic/bridge-test"
CORPUS = "bridge-test"


def fixture_record_dict() -> dict[str, Any]:
    return json.loads(FIXTURE_RECORD.read_text(encoding="utf-8"))


def proposition(
    pid: str,
    text: str | None,
    ptype: str = "Judicial Legal Conclusion",
    *,
    role: str | None = "court",
    individual_id: str | None = None,
    **extra: Any,
) -> Proposition:
    start, end = (0, len(text)) if text is not None else (None, None)
    asserter = None if role is None else ActorRef(role=role, individual_id=individual_id)
    return Proposition(
        id=pid, start_char=start, end_char=end, text=text, proposition_type=ptype,
        asserter=asserter, validator=None, disposition="accepted", **extra,
    )


def make_record(
    *propositions: Proposition,
    source_uri: str | None = SOURCE_URI,
    document_id: str = "doc-1",
    stamp: bool = True,
    metadata: dict[str, Any] | None = None,
) -> PropositionDocumentRecord:
    record = PropositionDocumentRecord(
        document_id=document_id,
        source_uri=source_uri,
        propositions=list(propositions),
        generator=GeneratorInfo(tool="folio-enrich", version="9.9.9-test"),
        document_metadata=metadata if metadata is not None else {"proposition_lexicon_version": "lex-1"},
    )
    return stamp_content_iris(record) if stamp and source_uri else record


@pytest.fixture
def storage_root(tmp_path: Path) -> Path:
    return tmp_path / "corpora"
