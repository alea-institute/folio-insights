"""Phase 1 DispositionRecord + ProposedFork — canonical schema locks Phase 15 consumer contract.

Revision 1 note: detector_verdict is a dict snapshot (full RuleVerdict/LLMVerdict
model_dump) — NOT a float (Pitfall A6 guard). The CLI (01-05) populates it via
verdict.model_dump(); the FP audit (01-06) reads it back via read_dispositions().

Phase 9 U6:

* ``labeler`` records who made the disposition: ``"human"`` (the review CLI)
  or ``"agent"`` (a first-pass label, e.g. the synthetic labeled set). Phase 1
  records predate the field and read as ``None`` (not recorded). Only a
  ``"human"`` disposition can release a fork (``distinguo.emit_distinguo_fork_ttl``).
* A ``reject`` needs a non-empty rationale (KTD9): a reject is the false-
  positive signal, and an unexplained one measures disposition quality, not a
  detector miscall. ``append_disposition`` refuses to write one. Reading stays
  tolerant, so Phase 1 logs that hold such rejects still load (the FP gate
  reports them as invalid and leaves them out of N).
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
    labeler: Literal["human", "agent"] | None = None

    @property
    def has_rationale(self) -> bool:
        return bool((self.rationale or "").strip())


class RejectWithoutRationale(ValueError):
    """A ``reject`` disposition with an empty rationale (KTD9)."""


def check_disposition(record: DispositionRecord) -> DispositionRecord:
    """Refuse a reject without a rationale; return the record otherwise."""
    if record.decision == "reject" and not record.has_rationale:
        raise RejectWithoutRationale(
            "a reject needs a non-empty rationale: say why the detector's call is wrong"
        )
    return record


def append_disposition(record: DispositionRecord, path: Path = LOG_PATH) -> None:
    """Append one JSON line; POSIX O_APPEND atomic for <PIPE_BUF writes.

    Refuses (``RejectWithoutRationale``) a reject with an empty rationale.
    """
    check_disposition(record)
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
