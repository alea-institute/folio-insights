"""Signed review decisions through the API (drain plan U9, R16, KTD11).

Synthetic data only; every key is generated here. Covers:

* unit review, unit bulk approval, review reset, task review, task bulk approval and the
  proposed-class review accept an optional ``signature`` and store the verified signer;
* tampered body, wrong key, expired ``issued_at``, replayed nonce and a signature moved to
  another unit are refused (400/403/409) and nothing is written;
* with ``FOLIO_INSIGHTS_REQUIRE_SIGNED_DECISIONS=1`` an unsigned decision is refused (403),
  and requiring signatures without a signers file refuses everything (503);
* by default an unsigned decision is stored with ``signature_verified`` false;
* operator authentication and decision authorship are both recorded: the operator handle
  from the bearer token and the signer DID from the signature;
* an existing review.db gains the signed-decision columns on its first write, and old rows
  read as unsigned.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from api import auth
from api import main as api_main
from api.main import app
from folio_insights.config import get_settings
from folio_insights.governance.clock import SIGNING_SKEW
from folio_insights.persistence.review_db import SCHEMA_SQL
from folio_insights.proposals import ProposalStore
from folio_insights.proposals.signed_decisions import (
    did_key_of,
    reset_signers_cache,
    sign_decision,
)
from folio_insights.storage import CorpusStorageContext

from tests.proposals._synthetic import pc

CORPUS = "default"
UNITS = [
    {"id": f"unit-00{i}", "text": f"Synthetic unit text {i}.", "confidence": c,
     "folio_tags": [], "original_span": {"start": 0, "end": 10, "source_file": "s.md"},
     "unit_type": "advice", "source_file": "s.md", "source_section": [],
     "surprise_score": 0.5, "content_hash": f"h{i}", "lineage": [], "cross_references": []}
    for i, c in ((1, 0.9), (2, 0.85), (3, 0.4))
]


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    out = tmp_path / "out"  # served output; the corpus storage root sits outside it
    corpus_dir = out / CORPUS
    corpus_dir.mkdir(parents=True)
    (corpus_dir / "extraction.json").write_text(json.dumps({
        "corpus": CORPUS, "generated_at": "2026-10-09T00:00:00Z", "total_units": len(UNITS),
        "by_confidence": {}, "units": UNITS,
    }))
    api_main.configure(output_dir=out, corpus_name=CORPUS)
    api_main._extraction_data.clear()
    api_main.load_extraction(CORPUS)
    monkeypatch.delenv("FOLIO_INSIGHTS_REQUIRE_SIGNED_DECISIONS", raising=False)
    monkeypatch.delenv("FOLIO_INSIGHTS_DECISION_SIGNERS_FILE", raising=False)
    get_settings.cache_clear()
    reset_signers_cache()
    yield {"tmp": tmp_path, "db": corpus_dir / "review.db", "client": TestClient(app),
           "mp": monkeypatch}
    get_settings.cache_clear()
    reset_signers_cache()


def _configure(env, **variables: str) -> None:
    for name, value in variables.items():
        env["mp"].setenv(name, value)
    get_settings.cache_clear()
    reset_signers_cache()


def _signers(env, *lines: str) -> Path:
    path = env["tmp"] / "signers.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def _key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def _sign(key, **fields):
    base = {"corpus": CORPUS, "rationale": ""}
    base.update(fields)
    return sign_decision(base, signing_key=key).to_record()


def _unit_sig(key, unit="unit-001", verdict="approved", rationale="Synthetic note.", **kw):
    return _sign(key, kind="unit_review", target=unit, verdict=verdict, rationale=rationale,
                 **kw)


def _rows(env) -> dict[str, dict]:
    if not env["db"].exists():
        return {}
    conn = sqlite3.connect(env["db"])
    conn.row_factory = sqlite3.Row
    try:
        return {r["unit_id"]: dict(r) for r in conn.execute("SELECT * FROM review_decisions")}
    finally:
        conn.close()


def _review(env, unit="unit-001", **body):
    body.setdefault("status", "approved")
    body.setdefault("note", "Synthetic note.")
    return env["client"].post(f"/api/v1/units/{unit}/review", params={"corpus": CORPUS},
                              json=body)


# ---- unit review ---------------------------------------------------------------------------


def test_signed_unit_review_stores_the_signer(env):
    key = _key()
    r = _review(env, signature=_unit_sig(key))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["signer_did"] == did_key_of(key)
    assert body["signature_verified"] is True
    assert body["operator"] == auth.LOOPBACK_HANDLE
    row = _rows(env)["unit-001"]
    assert row["signer_did"] == did_key_of(key)
    assert row["signature_verified"] == 1
    assert json.loads(row["decision_signature"])["body"]["target"] == "unit-001"
    # The read path shows it too.
    units = env["client"].get("/api/v1/units", params={"corpus": CORPUS,
                                                        "concept_iri": "__all__"}).json()
    shown = next(u for u in units if u["id"] == "unit-001")
    assert shown["signer_did"] == did_key_of(key) and shown["signature_verified"] is True


def test_unsigned_unit_review_is_stored_unverified_by_default(env):
    r = _review(env)
    assert r.status_code == 200, r.text
    assert r.json()["signature_verified"] is False and r.json()["signer_did"] is None
    row = _rows(env)["unit-001"]
    assert row["signature_verified"] == 0 and row["signer_did"] is None


def test_unsigned_review_after_a_signed_one_clears_the_signer(env):
    assert _review(env, signature=_unit_sig(_key())).status_code == 200
    assert _review(env, status="rejected", note="").status_code == 200
    row = _rows(env)["unit-001"]
    assert row["status"] == "rejected"
    assert row["signer_did"] is None and row["decision_signature"] is None
    assert row["signature_verified"] == 0


def test_tampered_signed_body_is_refused(env):
    sig = _unit_sig(_key())
    sig["body"]["verdict"] = "rejected"
    r = _review(env, status="rejected", signature=sig)
    assert r.status_code == 403
    assert "changed after signing" in r.json()["detail"]
    assert _rows(env) == {}


def test_wrong_key_is_refused(env):
    victim = did_key_of(_key())
    sig = _unit_sig(_key())
    sig["body"]["decided_by"] = sig["signature"]["did"] = victim
    sig["signature"]["signing_key_id"] = f"{victim}#{victim.removeprefix('did:key:')}"
    from folio_insights.proposals.signed_decisions import SignedDecision

    sig["signature"]["over_content_hash"] = SignedDecision.model_validate(sig).body.canonical_hash()
    r = _review(env, signature=sig)
    assert r.status_code == 403 and "does not verify" in r.json()["detail"]
    assert _rows(env) == {}


def test_expired_signature_is_refused(env):
    key = _key()
    old = sign_decision({"kind": "unit_review", "corpus": CORPUS, "target": "unit-001",
                         "verdict": "approved", "rationale": "Synthetic note."},
                        signing_key=key,
                        now=datetime.now(UTC) - SIGNING_SKEW - timedelta(minutes=1))
    r = _review(env, signature=old.to_record())
    assert r.status_code == 403 and "not within" in r.json()["detail"]
    assert _rows(env) == {}


def test_replayed_signature_is_refused(env):
    sig = _unit_sig(_key())
    assert _review(env, signature=sig).status_code == 200
    r = _review(env, signature=sig)
    assert r.status_code == 409 and "nonce was already used" in r.json()["detail"]
    nonces = sqlite3.connect(env["db"]).execute("SELECT count(*) FROM decision_nonces")
    assert nonces.fetchone()[0] == 1


def test_signature_for_another_unit_or_verdict_is_refused(env):
    key = _key()
    r = _review(env, unit="unit-002", signature=_unit_sig(key, unit="unit-001"))
    assert r.status_code == 400 and "target" in r.json()["detail"]
    r = _review(env, status="rejected", signature=_unit_sig(key))
    assert r.status_code == 400 and "verdict" in r.json()["detail"]
    r = _review(env, status="edited", edited_text="Synthetic edit.",
                signature=_unit_sig(key, verdict="edited"))
    assert r.status_code == 400 and "detail" in r.json()["detail"]
    assert _rows(env) == {}


def test_malformed_signature_is_400(env):
    r = _review(env, signature={"body": {"kind": "unit_review"}})
    assert r.status_code == 400 and "signature" in r.json()["detail"]


# ---- policy ---------------------------------------------------------------------------------


def test_require_signed_refuses_unsigned_and_accepts_registered(env):
    key = _key()
    _configure(env, FOLIO_INSIGHTS_REQUIRE_SIGNED_DECISIONS="1",
               FOLIO_INSIGHTS_DECISION_SIGNERS_FILE=str(
                   _signers(env, f"{did_key_of(key)} alice")))
    r = _review(env)
    assert r.status_code == 403 and "requires signed decisions" in r.json()["detail"]
    r = env["client"].post("/api/v1/units/bulk-approve", params={"corpus": CORPUS},
                           json={"unit_ids": ["unit-001"]})
    assert r.status_code == 403
    r = env["client"].post("/api/v1/review/reset", params={"corpus": CORPUS})
    assert r.status_code == 403
    assert _rows(env) == {}
    # An unregistered signer is refused; the registered one is attributed to its handle.
    r = _review(env, signature=_unit_sig(_key()))
    assert r.status_code == 403 and "not a registered" in r.json()["detail"]
    r = _review(env, signature=_unit_sig(key))
    assert r.status_code == 200, r.text
    assert r.json()["decided_by"] == "human:alice"
    assert _rows(env)["unit-001"]["decided_by"] == "human:alice"


def test_require_signed_without_signers_file_is_503(env):
    _configure(env, FOLIO_INSIGHTS_REQUIRE_SIGNED_DECISIONS="1")
    r = _review(env, signature=_unit_sig(_key()))
    assert r.status_code == 503
    assert _rows(env) == {}


# ---- operator and signer are both recorded ---------------------------------------------------


def test_operator_token_and_signer_are_recorded_separately(env):
    token = auth.generate_token()
    tokens = env["tmp"] / "tokens"
    tokens.write_text(auth.entry_line(token, "ops-synthetic") + "\n", encoding="utf-8")
    tokens.chmod(0o600)
    _configure(env, **{auth.AUTH_MODE_ENV: auth.MODE_REQUIRED,
                       auth.TOKENS_FILE_ENV: str(tokens)})
    auth.reset_cache()
    key = _key()
    assert _review(env, signature=_unit_sig(key)).status_code == 401  # no token
    r = env["client"].post("/api/v1/units/unit-001/review", params={"corpus": CORPUS},
                           headers={"Authorization": f"Bearer {token}"},
                           json={"status": "approved", "note": "Synthetic note.",
                                 "signature": _unit_sig(key)})
    assert r.status_code == 200, r.text
    row = _rows(env)["unit-001"]
    assert row["operator"] == "ops-synthetic"
    assert row["signer_did"] == did_key_of(key)
    assert token not in json.dumps(row)


# ---- bulk approve and reset ------------------------------------------------------------------


def test_signed_bulk_approve_by_ids_and_by_confidence(env):
    key = _key()
    sig = _sign(key, kind="unit_bulk_approve", target="*", verdict="approved",
                detail={"unit_ids": ["unit-001", "unit-002"]})
    r = env["client"].post("/api/v1/units/bulk-approve", params={"corpus": CORPUS},
                           json={"unit_ids": ["unit-001", "unit-002"], "signature": sig})
    assert r.status_code == 200, r.text
    assert r.json()["signer_did"] == did_key_of(key)
    rows = _rows(env)
    assert {u: rows[u]["signer_did"] for u in rows} == {"unit-001": did_key_of(key),
                                                         "unit-002": did_key_of(key)}
    # A signature over one selection does not cover another.
    r = env["client"].post("/api/v1/units/bulk-approve", params={"corpus": CORPUS},
                           json={"unit_ids": ["unit-003"], "signature": _sign(
                               key, kind="unit_bulk_approve", target="*",
                               verdict="approved", detail={"unit_ids": ["unit-001"]})})
    assert r.status_code == 400
    assert "unit-003" not in _rows(env)
    sig = _sign(key, kind="unit_bulk_approve", target="*", verdict="approved",
                detail={"confidence_min": 0.3})
    r = env["client"].post("/api/v1/units/bulk-approve", params={"corpus": CORPUS},
                           json={"confidence_min": 0.3, "signature": sig})
    assert r.status_code == 200, r.text
    assert _rows(env)["unit-003"]["signature_verified"] == 1


def test_signed_reset_records_its_nonce(env):
    assert _review(env).status_code == 200
    key = _key()
    sig = _sign(key, kind="unit_review_reset", target="*", verdict="reset")
    r = env["client"].post("/api/v1/review/reset", params={"corpus": CORPUS},
                           json={"signature": sig})
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == 1 and r.json()["signer_did"] == did_key_of(key)
    used = sqlite3.connect(env["db"]).execute(
        "SELECT signer_did, kind FROM decision_nonces").fetchall()
    assert used == [(did_key_of(key), "unit_review_reset")]
    # The unsigned reset (no body) still works by default.
    assert env["client"].post("/api/v1/review/reset",
                              params={"corpus": CORPUS}).status_code == 200


# ---- migration of an existing review.db ------------------------------------------------------


def test_existing_review_db_is_migrated_on_first_write(env):
    conn = sqlite3.connect(env["db"])
    conn.executescript(SCHEMA_SQL)  # the pre-U9 schema: no signed-decision columns
    conn.execute("INSERT INTO review_decisions (unit_id, corpus_name, status) "
                 "VALUES ('unit-003', ?, 'approved')", (CORPUS,))
    conn.commit()
    conn.close()
    # Reading does not migrate, and old rows read as unsigned.
    units = env["client"].get("/api/v1/units", params={"corpus": CORPUS,
                                                        "concept_iri": "__all__"}).json()
    assert next(u for u in units if u["id"] == "unit-003")["signature_verified"] is False
    cols = {r[1] for r in sqlite3.connect(env["db"]).execute(
        "PRAGMA table_info(review_decisions)")}
    assert "signer_did" not in cols
    assert _review(env, signature=_unit_sig(_key())).status_code == 200
    rows = _rows(env)
    assert rows["unit-001"]["signature_verified"] == 1
    assert rows["unit-003"]["signature_verified"] == 0 and rows["unit-003"]["signer_did"] is None


# ---- tasks (discovery routes) ----------------------------------------------------------------


def _seed_tasks(env) -> None:
    conn = sqlite3.connect(env["db"])
    conn.executescript(SCHEMA_SQL)
    for tid in ("task-a", "task-b"):
        conn.execute("INSERT INTO task_decisions (task_id, corpus_name, label, status) "
                     "VALUES (?, ?, ?, 'unreviewed')", (tid, CORPUS, f"Synthetic {tid}"))
    conn.commit()
    conn.close()


def _tasks(env) -> dict[str, dict]:
    conn = sqlite3.connect(env["db"])
    conn.row_factory = sqlite3.Row
    try:
        return {r["task_id"]: dict(r) for r in conn.execute("SELECT * FROM task_decisions")}
    finally:
        conn.close()


def test_signed_task_review_and_bulk_approve(env):
    _seed_tasks(env)
    key = _key()
    sig = _sign(key, kind="task_review", target="task-a", verdict="edited",
                rationale="Synthetic.", detail={"edited_label": "Synthetic label"})
    r = env["client"].post(f"/api/v1/corpus/{CORPUS}/tasks/task-a/review",
                           json={"status": "edited", "edited_label": "Synthetic label",
                                 "note": "Synthetic.", "signature": sig})
    assert r.status_code == 200, r.text
    assert _tasks(env)["task-a"]["signer_did"] == did_key_of(key)
    # Replay and a moved signature are refused.
    r = env["client"].post(f"/api/v1/corpus/{CORPUS}/tasks/task-a/review",
                           json={"status": "edited", "edited_label": "Synthetic label",
                                 "note": "Synthetic.", "signature": sig})
    assert r.status_code == 409
    r = env["client"].post(f"/api/v1/corpus/{CORPUS}/tasks/task-b/review",
                           json={"status": "edited", "edited_label": "Synthetic label",
                                 "note": "Synthetic.", "signature": sig})
    assert r.status_code == 400
    assert _tasks(env)["task-b"]["status"] == "unreviewed"
    sig = _sign(key, kind="task_bulk_approve", target="*", verdict="approved",
                detail={"task_ids": ["task-b"]})
    r = env["client"].post(f"/api/v1/corpus/{CORPUS}/tasks/bulk-approve",
                           json={"task_ids": ["task-b"], "signature": sig})
    assert r.status_code == 200, r.text
    row = _tasks(env)["task-b"]
    assert row["status"] == "approved" and row["signature_verified"] == 1


def test_require_signed_refuses_unsigned_task_review(env):
    _seed_tasks(env)
    _configure(env, FOLIO_INSIGHTS_REQUIRE_SIGNED_DECISIONS="1",
               FOLIO_INSIGHTS_DECISION_SIGNERS_FILE=str(
                   _signers(env, f"{did_key_of(_key())} alice")))
    r = env["client"].post(f"/api/v1/corpus/{CORPUS}/tasks/task-a/review",
                           json={"status": "approved"})
    assert r.status_code == 403
    r = env["client"].post(f"/api/v1/corpus/{CORPUS}/tasks/bulk-approve",
                           json={"task_ids": ["task-a"]})
    assert r.status_code == 403
    assert _tasks(env)["task-a"]["status"] == "unreviewed"


# ---- proposed classes (the proposal ledger) --------------------------------------------------

LEDGER = "corpus-a"
LABEL = "Zephyr Quorum Widget"


@pytest.fixture
def ledger_env(env, monkeypatch):
    root = env["tmp"] / "corpora"

    async def seed() -> str:
        async with await CorpusStorageContext.open(root, LEDGER) as ctx:
            store = ProposalStore(ctx)
            await store.collect_run("run-1", [pc(LABEL, "u1")])
            return (await store.load()).by_label(LABEL).proposal_id

    pid = asyncio.run(seed())
    monkeypatch.setattr(api_main, "_corpus_root", root)
    monkeypatch.setattr(api_main, "_reviewer", "synthetic-reviewer")
    monkeypatch.setenv("FOLIO_INSIGHTS_ALLOW_UNAUTHENTICATED_DECISIONS", "1")
    client = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000),
                        headers={"host": "127.0.0.1"})
    return {**env, "root": root, "pid": pid, "client": client}


def _decision(ledger_env) -> dict:
    async def load():
        async with await CorpusStorageContext.open(ledger_env["root"], LEDGER) as ctx:
            return (await ProposalStore(ctx).load()).get(ledger_env["pid"]).decision

    return asyncio.run(load())


def _pc_review(ledger_env, **body):
    return ledger_env["client"].post(f"/api/v1/proposed-classes/{LABEL}/review",
                                     params={"corpus": LEDGER}, json=body)


def _pc_sig(key, pid, verdict="approve", rationale="Synthetic note."):
    return sign_decision({"kind": "proposed_class", "corpus": LEDGER, "target": pid,
                          "verdict": verdict, "rationale": rationale},
                         signing_key=key).to_record()


def test_signed_proposed_class_decision_records_signer_and_operator(ledger_env):
    key = _key()
    r = _pc_review(ledger_env, status="approve", note="Synthetic note.",
                   signature=_pc_sig(key, ledger_env["pid"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["signer_did"] == did_key_of(key) and body["operator"] == auth.LOOPBACK_HANDLE
    assert body["decision"]["signature_verified"] is True
    decision = _decision(ledger_env)
    assert decision["signer_did"] == did_key_of(key)
    assert decision["decided_by"] == "human:synthetic-reviewer"
    assert decision["operator"] == auth.LOOPBACK_HANDLE
    # The signed decision cannot be recorded again under another request.
    r = _pc_review(ledger_env, status="approve", note="Synthetic note.", op_id="other-key",
                   signature=_pc_sig(key, ledger_env["pid"]))
    assert r.status_code == 200  # a fresh signature is fine
    replay = _decision(ledger_env)["signature"]
    r = _pc_review(ledger_env, status="approve", note="Synthetic note.", op_id="replay-key",
                   signature=replay)
    assert r.status_code == 409 and "nonce" in r.json()["detail"]


def test_proposed_class_tampered_and_unsigned_required(ledger_env):
    key = _key()
    head_decision = _decision(ledger_env)
    sig = _pc_sig(key, ledger_env["pid"])
    sig["body"]["verdict"] = "reject"
    r = _pc_review(ledger_env, status="reject", note="Synthetic note.", signature=sig)
    assert r.status_code == 403
    r = _pc_review(ledger_env, status="reject", note="Synthetic note.",
                   signature=_pc_sig(key, ledger_env["pid"]))
    assert r.status_code == 400 and "verdict" in r.json()["detail"]
    _configure(ledger_env, FOLIO_INSIGHTS_REQUIRE_SIGNED_DECISIONS="1",
               FOLIO_INSIGHTS_DECISION_SIGNERS_FILE=str(
                   _signers(ledger_env, f"{did_key_of(key)} alice")))
    r = _pc_review(ledger_env, status="approve")
    assert r.status_code == 403 and "requires signed decisions" in r.json()["detail"]
    assert _decision(ledger_env) == head_decision


def test_registered_signer_needs_no_configured_reviewer(ledger_env, monkeypatch):
    key = _key()
    monkeypatch.setattr(api_main, "_reviewer", None)
    monkeypatch.delenv("FOLIO_INSIGHTS_REVIEWER", raising=False)
    # Without a signers file the signed decision still needs the configured reviewer.
    r = _pc_review(ledger_env, status="approve", note="Synthetic note.",
                   signature=_pc_sig(key, ledger_env["pid"]))
    assert r.status_code == 403 and "no reviewer is configured" in r.json()["detail"]
    _configure(ledger_env, FOLIO_INSIGHTS_DECISION_SIGNERS_FILE=str(
        _signers(ledger_env, f"{did_key_of(key)} alice")))
    r = _pc_review(ledger_env, status="approve", note="Synthetic note.",
                   signature=_pc_sig(key, ledger_env["pid"]))
    assert r.status_code == 200, r.text
    assert _decision(ledger_env)["decided_by"] == "human:alice"
    # Unsigned is still refused for want of a reviewer.
    assert _pc_review(ledger_env, status="reject").status_code == 403
