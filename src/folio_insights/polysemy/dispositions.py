"""Phase 1 DispositionRecord + ProposedFork — canonical schema locks Phase 15 consumer contract.

Revision 1 note: detector_verdict is a dict snapshot (full RuleVerdict/LLMVerdict
model_dump) — NOT a float (Pitfall A6 guard). The CLI (01-05) populates it via
verdict.model_dump(); the FP audit (01-06) reads it back via read_dispositions().

Phase 9 U6:

* ``labeler`` records who made the disposition: ``"human"`` (the review CLI)
  or ``"agent"`` (a first-pass label, e.g. the synthetic labeled set). Phase 1
  records predate the field and read as ``None`` (not recorded). A human
  label alone establishes no authority: fork release also verifies a registered
  reviewer's ``signed_decision`` bound to the complete record and corpus.
* A ``reject`` needs a non-empty rationale (KTD9): a reject is the false-
  positive signal, and an unexplained one measures disposition quality, not a
  detector miscall. ``append_disposition`` refuses to write one. Reading stays
  tolerant, so Phase 1 logs that hold such rejects still load (the FP gate
  reports them as invalid and leaves them out of N).
"""
from __future__ import annotations

import json
import fcntl
import os
from datetime import datetime
from pathlib import Path
from typing import Iterator, Literal

from pydantic import BaseModel, Field

from folio_insights.proposals.signed_decisions import (
    DecisionReplayed, DecisionSignaturePolicy, SignedDecision, resolve_policy,
)

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
    fork_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


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
    corpus: str | None = None
    signed_decision: SignedDecision | None = None
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


class DispositionLogDamaged(ValueError):
    """The existing log is not complete JSONL; it is preserved unchanged."""


def append_disposition(
    record: DispositionRecord, path: Path = LOG_PATH, *,
    policy: DecisionSignaturePolicy | None = None, now: datetime | None = None,
) -> DispositionRecord:
    """Verify and append under one lock, with exact retries and per-signer nonces.

    Unsigned legacy records remain descriptive. Signed records always require a
    registered reviewer. A damaged log is refused, never repaired or truncated.
    """
    from folio_insights.polysemy.signing import disposition_integrity_problem, verify_disposition

    check_disposition(record)
    effective = resolve_policy(record.corpus or "default", policy)
    if record.signed_decision is None:
        effective.check_unsigned()
    else:
        verify_disposition(record, policy=effective)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("a+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        fh.seek(0)
        raw = fh.read()
        try:
            if raw and not raw.endswith("\n"):
                raise ValueError("unterminated record")
            existing = [DispositionRecord.model_validate_json(line)
                        for line in raw.splitlines() if line.strip()]
            if any(disposition_integrity_problem(previous) for previous in existing):
                raise ValueError("damaged signed record")
        except ValueError:
            raise DispositionLogDamaged("dispositions log is damaged; nothing was appended") from None
        if record.signed_decision is not None:
            signed = record.signed_decision
            for previous in existing:
                old = previous.signed_decision
                if old is not None and (old.body.decided_by, old.body.nonce) == (
                    signed.body.decided_by, signed.body.nonce,
                ):
                    if old.body == signed.body:
                        verify_disposition(previous, policy=effective)
                        return previous
                    raise DecisionReplayed("the reviewer's nonce already names another disposition")
            verify_disposition(record, policy=effective, now=now, check_freshness=True)
        fh.seek(0, os.SEEK_END)
        fh.write(record.model_dump_json(exclude_none=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return record


def read_dispositions(path: Path = LOG_PATH) -> Iterator[DispositionRecord]:
    """Yield one DispositionRecord per JSONL line. Blank lines skipped (B4)."""
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            yield DispositionRecord.model_validate(json.loads(line))
