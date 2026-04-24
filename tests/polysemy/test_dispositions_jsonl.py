"""DispositionRecord canonical schema + append-only JSONL + read_dispositions tests (D-3, B3/B4/B6/B7)."""
import json
from pathlib import Path

import pytest

from folio_insights.polysemy import (
    DispositionRecord,
    ProposedFork,
    append_disposition,
    read_dispositions,
)

pytestmark = pytest.mark.polysemy_spike


def _sample_record(decision: str = "accept") -> DispositionRecord:
    return DispositionRecord(
        cluster_id="fi:PrototypeCluster_a3f81c4e",
        term="consideration",
        proposed_fork=ProposedFork(
            cluster_id="fi:PrototypeCluster_a3f81c4e",
            term="consideration",
            frameworks=["CommonLaw", "Restatement", "FRE"],
            uses_analogousTo=True,
            prime_analogate="fi:Consideration_CommonLaw",
            proportional_relation="common-law bargain::civil-law cause",
            distinction_kind="analogica",
            suggested_child_iris=[
                "fi:Consideration_CommonLaw",
                "fi:Consideration_Restatement",
            ],
        ),
        decision=decision,
        rationale="Reviewed via fixture seed",
        reviewer_did="did:key:z6MkpzW3hVDsLMxk8Hq9j8g4FqTVQxN3Ycr2PRSbNb7GwLmP",
        reviewed_at_iso="2026-04-23T12:00:00+00:00",
        detector_verdict={
            "kind": "rule",
            "decision": "polysemy",
            "rule_confidence": 0.72,
            "matched_rules": ["R1-R2-R3-pass"],
            "evidence_score": 0.81,
        },
    )


def test_jsonl_schema_matches_phase15_contract() -> None:
    rec = _sample_record()
    payload = rec.model_dump_json()
    parsed = json.loads(payload)
    # Canonical (revision 1) fields — no detector_confidence float (B6):
    assert parsed["schema_version"] == "1"
    assert set(parsed.keys()) >= {
        "schema_version",
        "cluster_id",
        "term",
        "proposed_fork",
        "decision",
        "rationale",
        "reviewer_did",
        "reviewed_at_iso",
        "detector_verdict",
        "signature",
        "audit_label",
        "audit_agreement",
    }
    # detector_confidence must NOT exist in the canonical schema (B6 regression guard)
    assert "detector_confidence" not in parsed
    assert isinstance(parsed["detector_verdict"], dict)
    # ProposedFork.uses_analogousTo is present (B7)
    assert parsed["proposed_fork"]["uses_analogousTo"] is True
    # Literal enforcement:
    with pytest.raises(Exception):
        DispositionRecord.model_validate_json(
            payload.replace('"accept"', '"maybe"')
        )


def test_append_only(tmp_path: Path) -> None:
    log = tmp_path / "dispositions.jsonl"
    append_disposition(_sample_record("accept"), path=log)
    append_disposition(_sample_record("reject"), path=log)
    append_disposition(_sample_record("modify"), path=log)
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    decisions = [json.loads(line)["decision"] for line in lines]
    assert decisions == ["accept", "reject", "modify"]
    assert json.loads(lines[0])["decision"] == "accept"


def test_read_dispositions_yields_records(tmp_path: Path) -> None:
    """B4 — read_dispositions() consumed by 01-06 FP audit."""
    log = tmp_path / "dispositions.jsonl"
    append_disposition(_sample_record("accept"), path=log)
    append_disposition(_sample_record("reject"), path=log)
    # Embed a blank line (should be skipped):
    with log.open("a", encoding="utf-8") as fh:
        fh.write("\n")
    append_disposition(_sample_record("modify"), path=log)

    records = list(read_dispositions(log))
    assert len(records) == 3
    assert [r.decision for r in records] == ["accept", "reject", "modify"]
    assert all(isinstance(r, DispositionRecord) for r in records)
    # Round-trip detector_verdict preservation (no lossy float coercion)
    assert records[0].detector_verdict["evidence_score"] == 0.81
