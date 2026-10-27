"""Corpus-scoped policy is a floor at the actual decision store boundary."""
from __future__ import annotations

import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from folio_insights.config import Settings, get_settings
from folio_insights.proposals import ProposalStore
from folio_insights.proposals.signed_decisions import (
    DecisionPolicyMisconfigured,
    DecisionSignatureMismatch,
    DecisionSignaturePolicy,
    DecisionSignatureRequired,
    DecisionSignerUnregistered,
    did_key_of,
    load_policy,
    reset_signers_cache,
    sign_decision,
)
from folio_insights.storage import CorpusStorageContext
from tests.proposals._synthetic import pc


@pytest.fixture
def policy_env(monkeypatch, tmp_path):
    for name in ("REQUIRE_SIGNED_DECISIONS", "REQUIRE_SIGNED_DECISION_CORPORA", "DECISION_SIGNERS_FILE"):
        monkeypatch.delenv(f"FOLIO_INSIGHTS_{name}", raising=False)
    key = Ed25519PrivateKey.generate()
    path = tmp_path / "reviewers.txt"
    path.write_text(f"{did_key_of(key)} synthetic-reviewer\n")
    path.chmod(0o600)
    monkeypatch.setenv("FOLIO_INSIGHTS_DECISION_SIGNERS_FILE", str(path))
    get_settings.cache_clear()
    reset_signers_cache()
    yield monkeypatch, key
    get_settings.cache_clear()
    reset_signers_cache()


@pytest.mark.parametrize("global_required", [False, True])
@pytest.mark.parametrize("selected", [False, True])
def test_policy_matrix_and_two_corpora(policy_env, global_required, selected):
    mp, _ = policy_env
    mp.setenv("FOLIO_INSIGHTS_REQUIRE_SIGNED_DECISIONS", str(int(global_required)))
    mp.setenv("FOLIO_INSIGHTS_REQUIRE_SIGNED_DECISION_CORPORA", json.dumps(["corpus-a"] if selected else []))
    get_settings.cache_clear()
    for corpus in ("corpus-a", "corpus-b"):
        required = global_required or (selected and corpus == "corpus-a")
        policy = load_policy(corpus)
        assert policy.require_signed is required
        if required:
            with pytest.raises(DecisionSignatureRequired):
                policy.check_unsigned()
        else:
            policy.check_unsigned()
    assert load_policy().require_signed is global_required


@pytest.mark.parametrize("bad", ["../corpus-a", "corpus/a", "", "a b", "a" * 129])
def test_settings_reject_invalid_corpus_ids(bad):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, require_signed_decision_corpora=[bad])


@pytest.mark.parametrize("bad", ['["../corpus-a"]', '"corpus-a"', 'not-json'])
def test_invalid_corpus_configuration_is_controlled(policy_env, bad):
    mp, _ = policy_env
    mp.setenv("FOLIO_INSIGHTS_REQUIRE_SIGNED_DECISION_CORPORA", bad)
    get_settings.cache_clear()
    with pytest.raises(DecisionPolicyMisconfigured):
        load_policy("corpus-a")


async def _seed(ctx):
    store = ProposalStore(ctx)
    await store.collect_run("synthetic", [pc("Synthetic Corpus Widget", "unit-1")])
    return store, (await store.load()).by_label("Synthetic Corpus Widget").proposal_id


@pytest.mark.parametrize("global_required", [False, True])
async def test_explicit_open_policy_cannot_bypass_bound_corpus(policy_env, tmp_path, global_required):
    mp, _ = policy_env
    mp.setenv("FOLIO_INSIGHTS_REQUIRE_SIGNED_DECISIONS", str(int(global_required)))
    mp.setenv("FOLIO_INSIGHTS_REQUIRE_SIGNED_DECISION_CORPORA", '["corpus-a"]')
    get_settings.cache_clear()
    for corpus in ("corpus-a", "corpus-b"):
        async with await CorpusStorageContext.open(tmp_path / corpus, corpus) as ctx:
            store, pid = await _seed(ctx)
            before = await ctx.proposals.entries()
            request = [{"proposal_id": pid, "status": "approve"}]
            if global_required or corpus == "corpus-a":
                with pytest.raises(DecisionSignatureRequired):
                    await store.record_decisions(request, op_id="decision", decided_by="human:synthetic", policy=DecisionSignaturePolicy())
                assert await ctx.proposals.entries() == before
                assert not (await store.load()).decision_nonces
            else:
                await store.record_decisions(request, op_id="decision", decided_by="human:synthetic", policy=DecisionSignaturePolicy())
                assert (await store.load()).get(pid).decision["signature_verified"] is False


async def test_selected_corpus_missing_registry_refuses_before_append(policy_env, tmp_path):
    mp, _ = policy_env
    mp.delenv("FOLIO_INSIGHTS_DECISION_SIGNERS_FILE")
    mp.setenv("FOLIO_INSIGHTS_REQUIRE_SIGNED_DECISION_CORPORA", '["corpus-a"]')
    get_settings.cache_clear()
    assert load_policy("corpus-b").require_signed is False
    async with await CorpusStorageContext.open(tmp_path / "storage", "corpus-a") as ctx:
        store, pid = await _seed(ctx)
        before = await ctx.proposals.entries()
        with pytest.raises(DecisionPolicyMisconfigured):
            await store.record_decisions([{"proposal_id": pid, "status": "approve"}], op_id="decision", decided_by="human:synthetic", policy=DecisionSignaturePolicy())
        assert await ctx.proposals.entries() == before
        assert not (await store.load()).decision_nonces


async def test_registered_signature_is_bound_to_store_corpus(policy_env, tmp_path):
    mp, key = policy_env
    mp.setenv("FOLIO_INSIGHTS_REQUIRE_SIGNED_DECISION_CORPORA", '["corpus-a"]')
    get_settings.cache_clear()
    async with await CorpusStorageContext.open(tmp_path / "storage", "corpus-a") as ctx:
        store, pid = await _seed(ctx)
        fields = {"kind": "proposed_class", "corpus": "corpus-b", "target": pid, "verdict": "approve", "rationale": ""}
        item = {"proposal_id": pid, "status": "approve", "signature": sign_decision(fields, signing_key=key).to_record()}
        before = await ctx.proposals.entries()
        with pytest.raises(DecisionSignatureMismatch):
            await store.record_decisions([item], op_id="decision", decided_by=None)
        assert await ctx.proposals.entries() == before
        fields["corpus"] = "corpus-a"
        item["signature"] = sign_decision(fields, signing_key=key).to_record()
        await store.record_decisions([item], op_id="decision", decided_by=None)
        decision = (await store.load()).get(pid).decision
        assert decision["signer_registered"] is True
        assert decision["decided_by"] == "human:synthetic-reviewer"


async def test_explicit_registry_cannot_admit_unconfigured_signer(policy_env, tmp_path):
    mp, _ = policy_env
    mp.setenv("FOLIO_INSIGHTS_REQUIRE_SIGNED_DECISION_CORPORA", '["corpus-a"]')
    get_settings.cache_clear()
    attacker = Ed25519PrivateKey.generate()
    async with await CorpusStorageContext.open(tmp_path / "storage", "corpus-a") as ctx:
        store, pid = await _seed(ctx)
        signed = sign_decision({"kind": "proposed_class", "corpus": "corpus-a", "target": pid, "verdict": "approve"}, signing_key=attacker)
        before = await ctx.proposals.entries()
        with pytest.raises(DecisionSignerUnregistered):
            await store.record_decisions([{"proposal_id": pid, "status": "approve", "signature": signed.to_record()}], op_id="decision", decided_by=None, policy=DecisionSignaturePolicy(signers={did_key_of(attacker): "human:injected"}))
        assert await ctx.proposals.entries() == before
