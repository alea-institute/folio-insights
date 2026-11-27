"""Reviewer authority is cryptographic, not a self-asserted human label."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from folio_insights.polysemy.dispositions import (
    DispositionLogDamaged, append_disposition, read_dispositions,
)
from folio_insights.polysemy.distinguo import ForkNotReleased, emit_distinguo_fork_ttl
from folio_insights.polysemy.signing import verify_disposition
from folio_insights.proposals.signed_decisions import (
    DecisionReplayed, DecisionSignatureRefused, DecisionSignatureStale,
    DecisionSignerUnregistered,
)
from tests.polysemy._signed import signed_record
from tests.polysemy.test_review_fixes import _disposition, _fork

pytestmark = pytest.mark.usefixtures("registered_polysemy_reviewer")


def test_legacy_human_label_cannot_release_a_fork(tmp_path):
    fork = _fork()
    record = _disposition(fork.to_proposed_fork()).model_copy(update={"signed_decision": None})
    log = tmp_path / "dispositions.jsonl"
    append_disposition(record, log)
    assert list(read_dispositions(log)) == [record]
    with pytest.raises(ForkNotReleased, match="signature"):
        emit_distinguo_fork_ttl(fork, record, dispositions_path=log)


@pytest.mark.parametrize("decision", ["accept", "modify"])
def test_registered_signature_releases_only_logged_exact_fork(tmp_path, decision):
    fork = _fork()
    record = _disposition(fork.to_proposed_fork(), decision=decision)
    log = tmp_path / "dispositions.jsonl"
    with pytest.raises(ForkNotReleased, match="log"):
        emit_distinguo_fork_ttl(fork, record, dispositions_path=log)
    assert append_disposition(record, log) == record
    assert "fi:distinguishes" in emit_distinguo_fork_ttl(fork, record, dispositions_path=log)
    other = _fork(framework_ids=["us.common_law", "us.louisiana.civil_code", "uk.england.common_law"])
    with pytest.raises(ForkNotReleased, match="proposed fork"):
        emit_distinguo_fork_ttl(other, record, dispositions_path=log)


@pytest.mark.parametrize(("field", "value"), [
    ("corpus", "another-corpus"), ("cluster_id", "another-cluster"), ("term", "lease"),
    ("decision", "modify"), ("rationale", "changed"), ("reviewer_did", "did:key:zOther"),
    ("reviewed_at_iso", "2020-01-01T00:00:00Z"), ("labeler", "agent"),
    ("audit_label", "another-case"),
    ("detector_verdict", {"kind": "rule", "decision": "homonymy"}),
])
def test_every_signed_semantic_field_is_bound(tmp_path, field, value):
    fork = _fork()
    record = _disposition(fork.to_proposed_fork())
    altered = record.model_copy(update={field: value})
    log = tmp_path / "dispositions.jsonl"
    with pytest.raises(DecisionSignatureRefused):
        append_disposition(altered, log)
    assert not log.exists()
    log.write_text(altered.model_dump_json() + "\n")  # a raw writer cannot create authority
    with pytest.raises(ForkNotReleased):
        emit_distinguo_fork_ttl(fork, altered, dispositions_path=log)


@pytest.mark.parametrize(("field", "value"), [
    ("frameworks", ["us.common_law"]), ("uses_analogousTo", False),
    ("prime_analogate", "urn:test:other"), ("proportional_relation", "different"),
    ("distinction_kind", "rationis"), ("suggested_child_iris", ["urn:test:other"]),
])
def test_fork_components_are_bound(field, value):
    record = _disposition(_fork().to_proposed_fork())
    altered = record.model_copy(update={
        "proposed_fork": record.proposed_fork.model_copy(update={field: value}),
    })
    with pytest.raises(DecisionSignatureRefused):
        verify_disposition(altered)


def test_stale_submission_refuses_but_exact_retry_and_historical_read_succeed(tmp_path):
    fork = _fork()
    issued = datetime.now(UTC) - timedelta(days=1)
    record = signed_record(_disposition(fork.to_proposed_fork()), now=issued)
    log = tmp_path / "dispositions.jsonl"
    with pytest.raises(DecisionSignatureStale):
        append_disposition(record, log)
    assert not log.exists() or not log.read_bytes()
    append_disposition(record, log, now=issued)
    before = log.read_bytes()
    assert append_disposition(record, log) == record
    assert log.read_bytes() == before
    reopened = list(read_dispositions(log))[0]
    assert "fi:distinguishes" in emit_distinguo_fork_ttl(fork, reopened, dispositions_path=log)


def test_nonce_is_atomic_and_changed_body_cannot_reuse_it(tmp_path):
    record = _disposition(_fork().to_proposed_fork())
    log = tmp_path / "dispositions.jsonl"
    with ThreadPoolExecutor(max_workers=6) as pool:
        assert list(pool.map(lambda _: append_disposition(record, log), range(12))) == [record] * 12
    assert list(read_dispositions(log)) == [record]
    changed = record.model_copy(update={"rationale": "different rationale"})
    changed = signed_record(changed, nonce=record.signed_decision.body.nonce)
    before = log.read_bytes()
    with pytest.raises(DecisionReplayed):
        append_disposition(changed, log)
    assert log.read_bytes() == before


@pytest.mark.parametrize("damage", ['{"partial":', '{"not": "a disposition"}\n'])
def test_damaged_log_is_never_repaired_or_extended(tmp_path, damage):
    record = _disposition(_fork().to_proposed_fork())
    log = tmp_path / "dispositions.jsonl"
    log.write_text(damage)
    before = log.read_bytes()
    with pytest.raises(DispositionLogDamaged):
        append_disposition(record, log)
    assert log.read_bytes() == before


def test_damaged_signed_row_refuses_even_unrelated_append(tmp_path):
    record = _disposition(_fork().to_proposed_fork())
    log = tmp_path / "dispositions.jsonl"
    altered = record.model_copy(update={"rationale": "corrupted"})
    log.write_text(altered.model_dump_json() + "\n")
    before = log.read_bytes()
    unrelated = _disposition(_fork().to_proposed_fork(), rationale="another decision")
    with pytest.raises(DispositionLogDamaged):
        append_disposition(unrelated, log)
    assert log.read_bytes() == before


def test_current_registration_is_required_at_release(tmp_path, registered_polysemy_reviewer):
    fork = _fork()
    record = _disposition(fork.to_proposed_fork())
    log = tmp_path / "dispositions.jsonl"
    append_disposition(record, log)
    registered_polysemy_reviewer.write_text("")
    with pytest.raises(ForkNotReleased, match="signature"):
        emit_distinguo_fork_ttl(fork, record, dispositions_path=log)
    with pytest.raises(DecisionSignerUnregistered):
        append_disposition(record, log)


def test_signature_without_registered_reviewer_is_insufficient(tmp_path, monkeypatch):
    from folio_insights.config import get_settings

    monkeypatch.delenv("FOLIO_INSIGHTS_DECISION_SIGNERS_FILE")
    get_settings.cache_clear()
    record = _disposition(_fork().to_proposed_fork())
    with pytest.raises(DecisionSignerUnregistered):
        append_disposition(record, tmp_path / "dispositions.jsonl")


def test_corpus_policy_refuses_unsigned_disposition(tmp_path, monkeypatch):
    from folio_insights.config import get_settings
    from folio_insights.proposals.signed_decisions import DecisionSignatureRequired

    monkeypatch.setenv("FOLIO_INSIGHTS_REQUIRE_SIGNED_DECISION_CORPORA", '["synthetic"]')
    get_settings.cache_clear()
    record = _disposition(_fork().to_proposed_fork()).model_copy(update={"signed_decision": None})
    with pytest.raises(DecisionSignatureRequired):
        append_disposition(record, tmp_path / "dispositions.jsonl")


def test_fabricated_verification_flags_cannot_release(tmp_path):
    fork = _fork()
    record = _disposition(fork.to_proposed_fork()).model_copy(update={"signed_decision": None})
    log = tmp_path / "dispositions.jsonl"
    data = record.model_dump(mode="json")
    data.update(signature_verified=True, signer_registered=True)
    log.write_text(json.dumps(data) + "\n")
    with pytest.raises(ForkNotReleased, match="signature"):
        emit_distinguo_fork_ttl(fork, record, dispositions_path=log)
