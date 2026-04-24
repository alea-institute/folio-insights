"""Phase 1 DispositionRecord + ProposedFork — canonical schema locks Phase 15 consumer contract.

Revision 1 note: detector_verdict is a dict snapshot (full RuleVerdict/LLMVerdict
model_dump) — NOT a float (Pitfall A6 guard). The CLI (01-05) populates it via
verdict.model_dump(); the FP audit (01-06) reads it back via read_dispositions().
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator, Literal

from pydantic import BaseModel

LOG_PATH = Path(".planning/phases/01-polysemy-distinguo-spike/dispositions.jsonl")


class ProposedFork(BaseModel):
    cluster_id: str
    term: str
    frameworks: list[str] = []
    uses_analogousTo: bool = False  # B7 — consumed by 01-04 distinguo emission
    prime_analogate: str | None = None
    proportional_relation: str | None = None
    distinction_kind: Literal[
        "realis",
        "rationis",
        "rationis_cum_fundamento_in_re",
        "analogica",
    ] | None = None
    suggested_child_iris: list[str] = []


class DispositionRecord(BaseModel):
    schema_version: Literal["1"] = "1"
    cluster_id: str
    term: str
    proposed_fork: ProposedFork
    decision: Literal["accept", "reject", "modify"]
    rationale: str
    reviewer_did: str
    reviewed_at_iso: str
    detector_verdict: dict  # full verdict snapshot — NOT a float (B6)
    signature: str | None = None
    audit_label: str | None = None
    audit_agreement: bool | None = None


def append_disposition(record: DispositionRecord, path: Path = LOG_PATH) -> None:
    """Append one JSON line; POSIX O_APPEND atomic for <PIPE_BUF writes."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(record.model_dump_json(exclude_none=False) + "\n")


def read_dispositions(path: Path = LOG_PATH) -> Iterator[DispositionRecord]:
    """Yield one DispositionRecord per JSONL line. Blank lines skipped (B4)."""
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            yield DispositionRecord.model_validate(json.loads(line))
