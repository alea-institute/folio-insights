"""Signed review decisions: format, verification, policy, ledger store and CLI (drain U9, R16).

Synthetic data only: every key is generated in the test, every label is invented, and
nothing touches ``~/.folio-insights``. Covers the plan's U9 scenarios on the library and
store side:

* a decision signed by a generated did:key verifies, and the ledger records the signer;
* a tampered body, a wrong key, an expired ``issued_at`` and a replayed nonce are refused,
  and nothing is appended;
* with signatures required, an unsigned decision is refused; without, it is stored with
  ``signature_verified`` false;
* the fold re-verifies a stored signature, so a raw append cannot claim a signer;
* ``folio-insights proposals sign-decision`` and ``apply_approvals.py`` signed input.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from click.testing import CliRunner
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from folio_insights.config import get_settings
from folio_insights.governance.clock import SIGNING_SKEW
from folio_insights.proposals import ProposalStore
from folio_insights.proposals.decisions import decision_row_problem
from folio_insights.proposals.registry import KIND_DECISION
from folio_insights.proposals.signed_decisions import (
    KIND_PROPOSED_CLASS,
    KIND_UNIT_REVIEW,
    DecisionPolicyMisconfigured,
    DecisionReplayed,
    DecisionSignatureInvalid,
    DecisionSignatureMalformed,
    DecisionSignatureMismatch,
    DecisionSignaturePolicy,
    DecisionSignatureRequired,
    DecisionSignatureStale,
    DecisionSignerUnregistered,
    ExpectedDecision,
    SignedDecision,
    SignersFileError,
    did_key_of,
    load_policy,
    load_signers_file,
    operator_record,
    parse_signers,
    reset_signers_cache,
    sign_decision,
    stored_signature_problem,
    verify_signed_decision,
)
from folio_insights.proposals.store import ReviewerRequired
from folio_insights.storage import CorpusStorageContext

from tests.proposals._synthetic import pc

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS = "corpus-a"
REVIEWER = "human:synthetic-reviewer"
LABELS = ["Zephyr Quorum Widget", "Synthetic Docket Lantern", "Synthetic Filing Rituals"]
OPEN = DecisionSignaturePolicy()


def _key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def _unit_fields(**over):
    fields = {"kind": KIND_UNIT_REVIEW, "corpus": CORPUS, "target": "unit-001",
              "verdict": "approved", "rationale": "Synthetic rationale."}
    fields.update(over)
    return fields


def _unit_expected(**over) -> ExpectedDecision:
    base = dict(kind=KIND_UNIT_REVIEW, corpus=CORPUS, target="unit-001", verdict="approved",
                rationale="Synthetic rationale.")
    base.update(over)
    return ExpectedDecision(**base)


def _tamper(signed: SignedDecision, **body_changes) -> dict:
    record = signed.to_record()
    record["body"].update(body_changes)
    return record


# ---- format and verification ------------------------------------------------------------


async def test_signed_decision_verifies_and_binds_the_signer():
    key = _key()
    signed = sign_decision(_unit_fields(), signing_key=key)
    assert signed.body.decided_by == signed.signature.did == did_key_of(key)
    assert signed.signature.signing_key_id == f"{signed.signature.did}#" + \
        signed.signature.did.removeprefix("did:key:")
    assert signed.signature.over_content_hash == signed.body.canonical_hash()
    # The wire form round-trips and still verifies.
    wire = json.loads(json.dumps(signed.to_record()))
    verified = await verify_signed_decision(wire, expected=_unit_expected(), policy=OPEN)
    assert verified.signer_did == did_key_of(key)
    assert verified.signer_handle is None
    assert verified.body_hash == signed.body.canonical_hash()


async def test_tampered_body_is_refused():
    signed = sign_decision(_unit_fields(), signing_key=_key())
    for change in ({"verdict": "rejected"}, {"rationale": "Changed."}, {"target": "unit-002"},
                   {"nonce": "f" * 32}):
        record = _tamper(signed, **change)
        expected = _unit_expected(**{k: v for k, v in change.items() if k != "nonce"})
        with pytest.raises(DecisionSignatureInvalid, match="changed after signing"):
            await verify_signed_decision(record, expected=expected, policy=OPEN)


async def test_tampered_hash_and_signature_are_refused():
    signed = sign_decision(_unit_fields(), signing_key=_key())
    other = sign_decision(_unit_fields(verdict="rejected"), signing_key=_key())
    record = signed.to_record()
    record["body"]["verdict"] = "rejected"
    record["signature"]["over_content_hash"] = SignedDecision.model_validate(
        record).body.canonical_hash()  # hash matches the tampered body, signature does not
    with pytest.raises(DecisionSignatureInvalid, match="does not verify"):
        await verify_signed_decision(record, expected=_unit_expected(verdict="rejected"),
                                     policy=OPEN)
    record = signed.to_record()
    record["signature"]["signature"] = other.signature.signature
    with pytest.raises(DecisionSignatureInvalid):
        await verify_signed_decision(record, expected=_unit_expected(), policy=OPEN)


async def test_wrong_key_is_refused():
    """A signature by one key presented as another DID's decision never verifies."""
    signer, victim = _key(), _key()
    victim_did = did_key_of(victim)
    forged = sign_decision(_unit_fields(), signing_key=signer)
    record = forged.to_record()
    # Claim the victim's DID everywhere the DID appears; the hash is recomputed so only
    # the signature itself can fail.
    record["body"]["decided_by"] = victim_did
    record["signature"]["did"] = victim_did
    record["signature"]["signing_key_id"] = f"{victim_did}#{victim_did.removeprefix('did:key:')}"
    record["signature"]["over_content_hash"] = SignedDecision.model_validate(
        record).body.canonical_hash()
    with pytest.raises(DecisionSignatureInvalid, match="does not verify"):
        await verify_signed_decision(record, expected=_unit_expected(), policy=OPEN)


async def test_decided_by_must_be_the_signer():
    signed = sign_decision(_unit_fields(), signing_key=_key())
    record = signed.to_record()
    record["body"]["decided_by"] = did_key_of(_key())
    with pytest.raises(DecisionSignatureMismatch, match="decided_by must be the signer"):
        await verify_signed_decision(record, expected=_unit_expected(), policy=OPEN)


@pytest.mark.parametrize("offset", [SIGNING_SKEW + timedelta(seconds=1),
                                    -(SIGNING_SKEW + timedelta(seconds=1)),
                                    timedelta(days=30)])
async def test_issued_at_outside_the_signing_skew_is_refused(offset):
    now = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
    signed = sign_decision(_unit_fields(), signing_key=_key(), now=now - offset)
    with pytest.raises(DecisionSignatureStale, match="not within"):
        await verify_signed_decision(signed.to_record(), expected=_unit_expected(),
                                     policy=OPEN, now=now)


async def test_issued_at_inside_the_skew_verifies():
    now = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
    signed = sign_decision(_unit_fields(), signing_key=_key(),
                           now=now - SIGNING_SKEW + timedelta(seconds=1))
    await verify_signed_decision(signed.to_record(), expected=_unit_expected(), policy=OPEN,
                                 now=now)


async def test_moved_signed_at_is_refused():
    signed = sign_decision(_unit_fields(), signing_key=_key())
    record = signed.to_record()
    record["signature"]["signed_at"] = "2020-01-01T00:00:00Z"
    with pytest.raises(DecisionSignatureMismatch, match="signed_at"):
        await verify_signed_decision(record, expected=_unit_expected(), policy=OPEN)


@pytest.mark.parametrize("field,value", [
    ("kind", "task_review"), ("corpus", "corpus-b"), ("target", "unit-999"),
    ("verdict", "rejected"), ("rationale", "Other."), ("detail", {"edited_text": "x"}),
])
async def test_a_signature_cannot_be_moved_to_another_decision(field, value):
    signed = sign_decision(_unit_fields(), signing_key=_key())
    expected = _unit_expected(**{field: value})
    with pytest.raises(DecisionSignatureMismatch, match=field) as info:
        await verify_signed_decision(signed.to_record(), expected=expected, policy=OPEN)
    assert str(value) not in str(info.value)  # names the field, never the value


@pytest.mark.parametrize("bad", [
    None, "a string", {"body": {}}, {"body": {}, "signature": {}, "extra": 1},
])
async def test_malformed_signature_objects_are_refused(bad):
    with pytest.raises(DecisionSignatureMalformed):
        await verify_signed_decision(bad, expected=_unit_expected(), policy=OPEN)


async def test_only_did_key_signers_are_accepted():
    signed = sign_decision(_unit_fields(), signing_key=_key())
    record = signed.to_record()
    record["body"]["decided_by"] = record["signature"]["did"] = "did:web:example.test"
    with pytest.raises(DecisionSignatureMalformed, match="did"):
        await verify_signed_decision(record, expected=_unit_expected(), policy=OPEN)


def test_signing_refuses_caller_chosen_identity_fields():
    for extra in ({"decided_by": "did:key:zX"}, {"nonce": "a" * 32},
                  {"issued_at": "2026-10-09T00:00:00Z"}):
        with pytest.raises(DecisionSignatureMalformed, match="set by the signer"):
            sign_decision({**_unit_fields(), **extra}, signing_key=_key())


def test_every_signing_has_a_fresh_nonce():
    key = _key()
    a, b = (sign_decision(_unit_fields(), signing_key=key) for _ in range(2))
    assert a.body.nonce != b.body.nonce
    assert a.signature.over_content_hash != b.signature.over_content_hash


def test_stored_signature_problem_reverifies():
    key = _key()
    signed = sign_decision(_unit_fields(), signing_key=key)
    did = did_key_of(key)
    assert stored_signature_problem(signed.to_record(), expected=_unit_expected(),
                                    signer_did=did) is None
    assert stored_signature_problem(signed.to_record(), expected=_unit_expected(),
                                    signer_did=did_key_of(_key())) is not None
    forged = signed.to_record()
    forged["signature"]["signature"] = sign_decision(
        _unit_fields(), signing_key=_key()).signature.signature
    assert stored_signature_problem(forged, expected=_unit_expected(),
                                    signer_did=did) == "stored signature does not verify"
    late = (datetime.now(UTC) + SIGNING_SKEW * 2).isoformat()
    assert "skew" in stored_signature_problem(signed.to_record(), expected=_unit_expected(),
                                              signer_did=did, committed_at=late)


def test_operator_record_never_keeps_an_email():
    assert operator_record("ops-1") == "ops-1"
    recorded = operator_record("someone@example.test")
    assert recorded.startswith("sha256:") and "@" not in recorded
    assert operator_record(None) is None


# ---- policy and signers file -------------------------------------------------------------


def _signers_file(tmp_path: Path, lines: list[str], mode: int = 0o600) -> Path:
    path = tmp_path / "signers.txt"
    path.write_text("\n".join(["# synthetic reviewers", *lines, ""]), encoding="utf-8")
    path.chmod(mode)
    return path


@pytest.fixture
def settings_env(monkeypatch):
    monkeypatch.delenv("FOLIO_INSIGHTS_REQUIRE_SIGNED_DECISIONS", raising=False)
    monkeypatch.delenv("FOLIO_INSIGHTS_DECISION_SIGNERS_FILE", raising=False)
    get_settings.cache_clear()
    reset_signers_cache()
    yield monkeypatch
    get_settings.cache_clear()
    reset_signers_cache()


def _set(monkeypatch, **env):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    reset_signers_cache()


def test_default_policy_accepts_unsigned(settings_env):
    policy = load_policy()
    assert policy.require_signed is False and policy.signers is None
    policy.check_unsigned()


def test_required_without_signers_file_is_misconfigured(settings_env):
    _set(settings_env, FOLIO_INSIGHTS_REQUIRE_SIGNED_DECISIONS="1")
    with pytest.raises(DecisionPolicyMisconfigured, match="SIGNERS_FILE"):
        load_policy()


def test_required_policy_refuses_unsigned(settings_env, tmp_path):
    did = did_key_of(_key())
    path = _signers_file(tmp_path, [f"{did} synthetic-reviewer"])
    _set(settings_env, FOLIO_INSIGHTS_REQUIRE_SIGNED_DECISIONS="1",
         FOLIO_INSIGHTS_DECISION_SIGNERS_FILE=str(path))
    policy = load_policy()
    assert policy.signers == {did: "human:synthetic-reviewer"}
    with pytest.raises(DecisionSignatureRequired):
        policy.check_unsigned()


async def test_registered_signer_maps_to_its_handle_and_others_are_refused(tmp_path):
    key = _key()
    policy = DecisionSignaturePolicy(signers=parse_signers(f"{did_key_of(key)} alice\n"))
    verified = await verify_signed_decision(
        sign_decision(_unit_fields(), signing_key=key).to_record(),
        expected=_unit_expected(), policy=policy,
    )
    assert verified.signer_handle == "human:alice"
    with pytest.raises(DecisionSignerUnregistered):
        await verify_signed_decision(
            sign_decision(_unit_fields(), signing_key=_key()).to_record(),
            expected=_unit_expected(), policy=policy,
        )


@pytest.mark.parametrize("text,match", [
    ("did:web:example.test alice\n", "line 1"),
    ("did:key:zNotAKey alice\n", "line 1"),
    ("{did} bad handle!\n", "line 1"),
    ("{did} alice\n{did} bob\n", "line 2 repeats"),
    ("{did}\n", "line 1"),
])
def test_malformed_signers_files_are_refused_by_line(text, match):
    did = did_key_of(_key())
    with pytest.raises(SignersFileError, match=match) as info:
        parse_signers(text.format(did=did))
    assert did not in str(info.value)


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits")
def test_writable_by_others_signers_file_is_refused(tmp_path):
    path = _signers_file(tmp_path, [f"{did_key_of(_key())} alice"], mode=0o666)
    with pytest.raises(SignersFileError, match="other users write"):
        load_signers_file(path)
    path.chmod(0o644)  # world-readable is fine: the file holds public DIDs only
    assert len(load_signers_file(path)) == 1


# ---- the proposal ledger ------------------------------------------------------------------


async def _seed(ctx: CorpusStorageContext) -> dict[str, str]:
    store = ProposalStore(ctx)
    await store.collect_run("run-1", [pc(label, f"u{i}") for i, label in enumerate(LABELS)])
    reg = await store.load()
    return {label: reg.by_label(label).proposal_id for label in LABELS}


def _proposal_fields(pid: str, verdict: str = "approve", **over):
    fields = {"kind": KIND_PROPOSED_CLASS, "corpus": CORPUS, "target": pid,
              "verdict": verdict, "rationale": "Synthetic note."}
    fields.update(over)
    return fields


@pytest.fixture
async def ledger(tmp_path):
    async with await CorpusStorageContext.open(tmp_path / "storage", CORPUS) as ctx:
        ids = await _seed(ctx)
        yield ctx, ids


async def test_signed_proposal_decision_records_the_signer(ledger):
    ctx, ids = ledger
    pid = ids["Zephyr Quorum Widget"]
    key = _key()
    signed = sign_decision(_proposal_fields(pid), signing_key=key)
    store = ProposalStore(ctx)
    result = await store.record_decisions(
        [{"proposal_id": pid, "status": "approve", "note": "Synthetic note.",
          "signature": signed.to_record()}],
        op_id="signed:1", decided_by=REVIEWER, operator="ops-1", policy=OPEN,
    )
    assert result["recorded"] == 1
    decision = (await store.load()).get(pid).decision
    assert decision["status"] == "approved"
    assert decision["signer_did"] == did_key_of(key)
    assert decision["signature_verified"] is True
    assert decision["decided_by"] == REVIEWER  # no signers file: the server's attribution
    assert decision["operator"] == "ops-1"
    assert SignedDecision.model_validate(decision["signature"]) == signed


async def test_registered_signer_is_the_author_without_a_reviewer(ledger):
    ctx, ids = ledger
    pid = ids["Zephyr Quorum Widget"]
    key = _key()
    policy = DecisionSignaturePolicy(signers={did_key_of(key): "human:alice"})
    signed = sign_decision(_proposal_fields(pid), signing_key=key)
    store = ProposalStore(ctx)
    await store.record_decisions(
        [{"proposal_id": pid, "status": "approve", "note": "Synthetic note.",
          "signature": signed.to_record()}],
        op_id="signed:alice", decided_by=None, policy=policy,
    )
    decision = (await store.load()).get(pid).decision
    assert decision["decided_by"] == "human:alice"
    assert decision["signer_did"] == did_key_of(key)
    # An unsigned decision still needs a reviewer.
    with pytest.raises(ReviewerRequired):
        await store.record_decisions([{"proposal_id": pid, "status": "reject"}],
                                     op_id="unsigned:none", decided_by=None, policy=policy)


async def test_unsigned_decision_is_stored_unverified_by_default(ledger):
    ctx, ids = ledger
    pid = ids["Synthetic Docket Lantern"]
    store = ProposalStore(ctx)
    await store.record_decisions([{"proposal_id": pid, "status": "reject"}],
                                 op_id="unsigned:1", decided_by=REVIEWER, policy=OPEN)
    decision = (await store.load()).get(pid).decision
    assert decision["signature_verified"] is False
    assert decision["signer_did"] is None
    assert "signature" not in decision


async def test_required_signatures_refuse_unsigned_and_append_nothing(ledger):
    ctx, ids = ledger
    store = ProposalStore(ctx)
    head = (await store.load()).head
    required = DecisionSignaturePolicy(require_signed=True, signers={})
    with pytest.raises(DecisionSignatureRequired, match="decision item 0"):
        await store.record_decisions([{"proposal_id": ids["Zephyr Quorum Widget"],
                                       "status": "approve"}],
                                     op_id="unsigned:2", decided_by=REVIEWER, policy=required)
    assert (await store.load()).head == head


async def test_tampered_wrong_key_and_expired_are_refused_by_the_store(ledger):
    ctx, ids = ledger
    pid = ids["Zephyr Quorum Widget"]
    store = ProposalStore(ctx)
    head = (await store.load()).head
    signed = sign_decision(_proposal_fields(pid), signing_key=_key())
    # Tampered: the request approves, the signature rejected something else.
    tampered = _tamper(signed, verdict="reject")
    stale = sign_decision(_proposal_fields(pid), signing_key=_key(),
                          now=datetime.now(UTC) - SIGNING_SKEW * 2)
    cases = [
        ({"status": "reject", "signature": tampered}, DecisionSignatureInvalid),
        ({"status": "reject", "signature": signed.to_record()}, DecisionSignatureMismatch),
        ({"status": "approve", "signature": stale.to_record()}, DecisionSignatureStale),
    ]
    for index, (item, error) in enumerate(cases):
        with pytest.raises(error, match="decision item 0"):
            await store.record_decisions(
                [{"proposal_id": pid, "note": "Synthetic note.", **item}],
                op_id=f"bad:{index}", decided_by=REVIEWER, policy=OPEN,
            )
    assert (await store.load()).head == head


async def test_replayed_nonce_is_refused_but_op_id_retry_replays(ledger):
    ctx, ids = ledger
    pid = ids["Zephyr Quorum Widget"]
    store = ProposalStore(ctx)
    signed = sign_decision(_proposal_fields(pid), signing_key=_key()).to_record()
    item = {"proposal_id": pid, "status": "approve", "note": "Synthetic note.",
            "signature": signed}
    first = await store.record_decisions([item], op_id="signed:a", decided_by=REVIEWER,
                                         policy=OPEN)
    # A retry of the same operation returns the committed result (nothing new recorded),
    # even after the signing skew has passed.
    again = await store.record_decisions(
        [item], op_id="signed:a", decided_by=REVIEWER, policy=OPEN,
        now=datetime.now(UTC) + SIGNING_SKEW * 3,
    )
    assert again["replayed"] is True and again["position"] == first["position"]
    head = (await store.load()).head
    # The same signed decision under a new operation is a replay attack.
    with pytest.raises(DecisionReplayed, match="nonce was already used"):
        await store.record_decisions([item], op_id="signed:b", decided_by=REVIEWER,
                                     policy=OPEN)
    # So is a second use of the nonce inside one batch.
    other = ids["Synthetic Docket Lantern"]
    key = _key()
    dup_nonce = [
        {"proposal_id": p, "status": "approve", "note": "Synthetic note.",
         "signature": sign_decision(_proposal_fields(p), signing_key=key,
                                    nonce="b" * 32).to_record()}
        for p in (other, ids["Synthetic Filing Rituals"])
    ]
    with pytest.raises(DecisionReplayed, match="decision item 1"):
        await store.record_decisions(dup_nonce, op_id="signed:c", decided_by=REVIEWER,
                                     policy=OPEN)
    assert (await store.load()).head == head


async def test_merge_signature_must_name_the_merge_target(ledger):
    ctx, ids = ledger
    src, dst = ids["Synthetic Filing Rituals"], ids["Synthetic Docket Lantern"]
    store = ProposalStore(ctx)
    key = _key()
    no_target = sign_decision(_proposal_fields(src, "merge"), signing_key=key)
    with pytest.raises(DecisionSignatureMismatch, match="detail"):
        await store.record_decisions(
            [{"proposal_id": src, "status": "merge", "merge_into": dst,
              "note": "Synthetic note.", "signature": no_target.to_record()}],
            op_id="merge:1", decided_by=REVIEWER, policy=OPEN,
        )
    signed = sign_decision(_proposal_fields(src, "merge", detail={"merge_into": dst}),
                           signing_key=key)
    await store.record_decisions(
        [{"proposal_id": src, "status": "merge", "merge_into": dst,
          "note": "Synthetic note.", "signature": signed.to_record()}],
        op_id="merge:2", decided_by=REVIEWER, policy=OPEN,
    )
    assert (await store.load()).get(src).decision["signer_did"] == did_key_of(key)


async def test_signing_an_unsigned_decision_makes_a_new_current_decision(ledger):
    ctx, ids = ledger
    pid = ids["Zephyr Quorum Widget"]
    store = ProposalStore(ctx)
    await store.record_decisions([{"proposal_id": pid, "status": "approve",
                                   "note": "Synthetic note."}],
                                 op_id="u:1", decided_by=REVIEWER, policy=OPEN)
    signed = sign_decision(_proposal_fields(pid), signing_key=_key())
    await store.record_decisions([{"proposal_id": pid, "status": "approve",
                                   "note": "Synthetic note.", "signature": signed.to_record()}],
                                 op_id="s:1", decided_by=REVIEWER, policy=OPEN)
    p = (await store.load()).get(pid)
    assert len(p.decision_history) == 2
    assert [d["signature_verified"] for d in p.decision_history] == [False, True]


async def test_fold_refuses_a_raw_append_that_claims_a_signer(ledger):
    """A row that bypassed the store cannot claim a verified signer (or forge one)."""
    ctx, ids = ledger
    pid = ids["Zephyr Quorum Widget"]
    store = ProposalStore(ctx)
    victim = _key()
    signed = sign_decision(_proposal_fields(pid, "reject"), signing_key=_key()).to_record()
    raw_items = [
        # Claims verified with no signature.
        {"proposal_id": pid, "status": "approved", "note": "", "decided_by": REVIEWER,
         "merge_into": None, "signer_did": did_key_of(victim), "signature_verified": True},
        # A real signature for a different verdict.
        {"proposal_id": pid, "status": "approved", "note": "Synthetic note.",
         "decided_by": REVIEWER, "merge_into": None,
         "signer_did": signed["signature"]["did"], "signature_verified": True,
         "signature": signed},
    ]
    for index, item in enumerate(raw_items):
        await ctx.proposals.append(KIND_DECISION, {"decisions": [item]}, op_id=f"raw:{index}")
    reg = await store.load()
    assert reg.get(pid).decision["status"] == "pending"
    assert len(reg.invalid_decisions) == 2


def test_decision_row_problem_accepts_a_store_written_signed_row():
    key = _key()
    pid = "PC-" + "0" * 32
    signed = sign_decision(_proposal_fields(pid), signing_key=key).to_record()
    item = {"proposal_id": pid, "status": "approved", "note": "Synthetic note.",
            "decided_by": REVIEWER, "merge_into": None, "signer_did": did_key_of(key),
            "signature_verified": True, "signature": signed, "operator": "ops-1"}
    proposals = {pid: object()}
    assert decision_row_problem(item, proposals, corpus=CORPUS,
                                committed_at=datetime.now(UTC).isoformat()) is None
    assert decision_row_problem(item, proposals, corpus="corpus-b") is not None
    assert decision_row_problem({**item, "operator": "a@b.test"}, proposals,
                                corpus=CORPUS) is not None
    assert decision_row_problem({**item, "signature_verified": False}, proposals,
                                corpus=CORPUS) is not None


# ---- CLI: sign-decision and apply_approvals.py ---------------------------------------------


def _jwk_key(tmp_path: Path) -> tuple[Path, str]:
    from folio_insights.identity.keys import generate_keypair

    path = tmp_path / "keys" / "reviewer.jwk"
    did = generate_keypair(path)
    return path, did


def test_cli_sign_decision_prints_a_verifiable_signed_decision(tmp_path):
    from folio_insights.cli import cli

    key_path, did = _jwk_key(tmp_path)
    body = tmp_path / "decision.json"
    body.write_text(json.dumps(_unit_fields()), encoding="utf-8")
    result = CliRunner().invoke(cli, ["proposals", "sign-decision", "--key", str(key_path),
                                      "--body", str(body)])
    assert result.exit_code == 0, result.output
    signed = SignedDecision.model_validate(json.loads(result.output))
    assert signed.body.decided_by == did
    assert '"d"' not in result.output  # the private JWK member never appears


def test_cli_sign_decision_refuses_bad_input(tmp_path):
    from folio_insights.cli import cli

    key_path, _ = _jwk_key(tmp_path)
    body = tmp_path / "decision.json"
    body.write_text(json.dumps({**_unit_fields(), "nonce": "a" * 32}), encoding="utf-8")
    result = CliRunner().invoke(cli, ["proposals", "sign-decision", "--key", str(key_path),
                                      "--body", str(body)])
    assert result.exit_code != 0 and "set by the signer" in result.output
    key_path.chmod(0o644)
    body.write_text(json.dumps(_unit_fields()), encoding="utf-8")
    result = CliRunner().invoke(cli, ["proposals", "sign-decision", "--key", str(key_path),
                                      "--body", str(body)])
    assert result.exit_code != 0 and "PermissionError" in result.output


def _script(name: str):
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        return __import__(name)
    finally:
        sys.path.remove(str(REPO_ROOT / "scripts"))


async def _seed_root(root: Path) -> dict[str, str]:
    async with await CorpusStorageContext.open(root, CORPUS) as ctx:
        return await _seed(ctx)


async def _decision(root: Path, pid: str) -> dict:
    async with await CorpusStorageContext.open(root, CORPUS) as ctx:
        return (await ProposalStore(ctx).load()).get(pid).decision


@pytest.mark.storage
async def test_apply_approvals_accepts_signed_input(tmp_path, settings_env):
    import asyncio

    root = tmp_path / "storage"
    ids = await _seed_root(root)
    pid = ids["Zephyr Quorum Widget"]
    key = _key()
    signed = sign_decision(_proposal_fields(pid), signing_key=key).to_record()
    path = _signers_file(tmp_path, [f"{did_key_of(key)} alice"])
    _set(settings_env, FOLIO_INSIGHTS_DECISION_SIGNERS_FILE=str(path))
    decisions = tmp_path / "signed.json"
    decisions.write_text(json.dumps({"schema": "proposed-class-signed-decisions/v1",
                                     "corpus": CORPUS, "signed": [signed]}))
    mod = _script("apply_approvals")
    args = mod.build_parser().parse_args(["apply", "--corpus", CORPUS, "--corpus-root",
                                          str(root), "--decisions", str(decisions)])
    result = await mod._run(args)  # no --decided-by: the signer's handle is the author
    assert result["recorded"] == 1
    decision = await _decision(root, pid)
    assert decision["decided_by"] == "human:alice"
    assert decision["signer_did"] == did_key_of(key)
    assert decision["signature_verified"] is True
    # A per-decision signature in the paste-back format works too; a replay is refused.
    paste = tmp_path / "paste.json"
    paste.write_text(json.dumps({"schema": "proposed-class-approvals/v1", "corpus": CORPUS,
                                 "decisions": {pid: {"status": "approve",
                                                     "note": "Synthetic note.",
                                                     "signature": signed}}}))
    with pytest.raises(SystemExit, match="refused: .*nonce was already used"):
        await asyncio.to_thread(mod.main, ["apply", "--corpus", CORPUS, "--corpus-root",
                                           str(root), "--decisions", str(paste)])


@pytest.mark.storage
async def test_apply_approvals_require_signed_refuses_unsigned(tmp_path, settings_env):
    import asyncio

    root = tmp_path / "storage"
    ids = await _seed_root(root)
    pid = ids["Zephyr Quorum Widget"]
    path = _signers_file(tmp_path, [f"{did_key_of(_key())} alice"])
    _set(settings_env, FOLIO_INSIGHTS_REQUIRE_SIGNED_DECISIONS="1",
         FOLIO_INSIGHTS_DECISION_SIGNERS_FILE=str(path))
    paste = tmp_path / "paste.json"
    paste.write_text(json.dumps({"schema": "proposed-class-approvals/v1", "corpus": CORPUS,
                                 "decisions": {pid: {"status": "approve"}}}))
    mod = _script("apply_approvals")
    with pytest.raises(SystemExit, match="refused: .*requires signed decisions"):
        await asyncio.to_thread(mod.main, ["apply", "--corpus", CORPUS, "--corpus-root",
                                           str(root), "--decisions", str(paste),
                                           "--decided-by", REVIEWER])
    assert (await _decision(root, pid))["status"] == "pending"
