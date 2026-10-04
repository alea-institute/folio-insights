"""The review API's proposed-class decisions go through the proposal ledger.

Synthetic data only. Covers the single-approval-surface plan's U2 scenarios:

* a decision made through ``POST /api/v1/proposed-classes/{label}/review``
  appears in the approved-only backlog;
* an unknown label, an invalid status, a missing or invalid reviewer, a body
  naming ``decided_by``, a bad corpus ID and PII in the note are refused, and
  nothing is written;
* replay with a client op_id returns the original result; a conflicting reuse
  is refused; a repeat without op_id keeps the original ``decided_at``;
* reads come from the ledger, not the legacy review.db table;
* ``/review/reset`` leaves the legacy table and the ledger alone;
* the API never creates a storage root and refuses one in served output.
"""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import main as api_main
from api.main import app
from folio_insights.proposals import ProposalStore, build_backlog
from folio_insights.storage import CorpusStorageContext

from tests.proposals._synthetic import pc
from tests.proposals.test_legacy_import import make_legacy_db

pytestmark = pytest.mark.storage

CORPUS = "corpus-a"
LABELS = ["Zephyr Quorum Widget", "Synthetic Docket Lantern", "Synthetic Filing Rituals"]


async def _seed(root: Path) -> dict[str, str]:
    async with await CorpusStorageContext.open(root, CORPUS) as ctx:
        store = ProposalStore(ctx)
        await store.collect_run("run-1", [pc(label, f"u{i}") for i, label in enumerate(LABELS)])
        reg = await store.load()
        return {label: reg.by_label(label).proposal_id for label in LABELS}


async def _load(root: Path):
    async with await CorpusStorageContext.open(root, CORPUS) as ctx:
        return await ProposalStore(ctx).load()


def load(root: Path):
    return asyncio.run(_load(root))


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    out = tmp_path / "out"
    out.mkdir()
    root = tmp_path / "corpora"
    monkeypatch.setattr(api_main, "_output_dir", out)
    monkeypatch.setattr(api_main, "_corpus_root", root)
    monkeypatch.setattr(api_main, "_reviewer", "synthetic-reviewer")
    monkeypatch.delenv("FOLIO_INSIGHTS_REVIEWER", raising=False)
    ids = asyncio.run(_seed(root))
    return {"out": out, "root": root, "ids": ids, "client": TestClient(app)}


def review(client: TestClient, label: str, corpus: str = CORPUS, **body):
    return client.post(f"/api/v1/proposed-classes/{label}/review",
                       params={"corpus": corpus}, json=body)


def test_api_decision_reaches_the_approved_only_backlog(env):
    r = review(env["client"], "Zephyr Quorum Widget", status="approved", note="Synthetic note.")
    assert r.status_code == 200, r.text
    body = r.json()
    pid = env["ids"]["Zephyr Quorum Widget"]
    assert body["proposal_id"] == pid
    assert body["status"] == "approved" and body["recorded"] is True
    assert body["decision"]["decided_by"] == "human:synthetic-reviewer"
    assert body["op_id"].startswith("api:review:auto:")
    assert body["reviewed_at"] == body["decided_at"]

    backlog = build_backlog(load(env["root"]))
    assert [row["proposal_id"] for row in backlog["proposals"]] == [pid]
    row = backlog["proposals"][0]["decision"]
    assert row["decided_by"] == "human:synthetic-reviewer"
    assert row["reviewer_note"] == "Synthetic note."
    assert row["op_id"] == body["op_id"]


def test_label_resolution_follows_the_registry(env):
    # A case/punctuation variant is the same proposal (one ID per normalized label).
    r = review(env["client"], "zephyr-quorum WIDGET", status="reject")
    assert r.status_code == 200, r.text
    assert r.json()["proposal_id"] == env["ids"]["Zephyr Quorum Widget"]
    assert load(env["root"]).get(env["ids"]["Zephyr Quorum Widget"]).decision["status"] == "rejected"


def test_unknown_label_is_refused_and_nothing_is_written(env):
    head = load(env["root"]).head
    r = review(env["client"], "Unknown Synthetic Label", status="approved")
    assert r.status_code == 404
    assert "no proposed class" in r.json()["detail"]
    assert load(env["root"]).head == head
    # The same label in another corpus is unknown there: IDs are corpus-keyed.
    r = review(env["client"], "Zephyr Quorum Widget", corpus="corpus-b", status="approved")
    assert r.status_code == 404
    assert load(env["root"]).head == head


@pytest.mark.parametrize("status", ["pending", "maybe", "APPROVED", ""])
def test_invalid_status_is_refused_and_nothing_is_written(env, status):
    head = load(env["root"]).head
    r = review(env["client"], "Zephyr Quorum Widget", status=status)
    assert r.status_code == 400
    assert load(env["root"]).head == head


@pytest.mark.parametrize("reviewer", [None, "", "  ", "bad handle!", "model:synthetic-judge",
                                      "someone@example.test"])
def test_missing_or_invalid_reviewer_is_refused(env, monkeypatch, reviewer):
    monkeypatch.setattr(api_main, "_reviewer", reviewer)
    head = load(env["root"]).head
    r = review(env["client"], "Zephyr Quorum Widget", status="approved")
    assert r.status_code == 403
    assert load(env["root"]).head == head


def test_reviewer_from_environment(env, monkeypatch):
    monkeypatch.setattr(api_main, "_reviewer", None)
    monkeypatch.setenv("FOLIO_INSIGHTS_REVIEWER", "human:env-reviewer")
    r = review(env["client"], "Zephyr Quorum Widget", status="approved")
    assert r.status_code == 200, r.text
    assert r.json()["decision"]["decided_by"] == "human:env-reviewer"


def test_client_cannot_name_the_reviewer(env):
    head = load(env["root"]).head
    r = review(env["client"], "Zephyr Quorum Widget", status="approved",
               decided_by="human:someone-else")
    assert r.status_code == 422
    assert load(env["root"]).head == head


def test_pii_in_the_note_is_refused(env):
    head = load(env["root"]).head
    r = review(env["client"], "Zephyr Quorum Widget", status="approved",
               note="Call 212-555-0142.")
    assert r.status_code == 422
    assert "212-555" not in r.text
    assert load(env["root"]).head == head


def test_bad_corpus_id_is_refused(env):
    r = review(env["client"], "Zephyr Quorum Widget", corpus="../escape", status="approved")
    assert r.status_code == 400
    assert env["client"].get("/api/v1/proposed-classes",
                             params={"corpus": "a b"}).status_code == 400


def test_client_op_id_replays_and_refuses_reuse(env):
    first = review(env["client"], "Zephyr Quorum Widget", status="approved", op_id="click-1")
    assert first.status_code == 200, first.text
    head = load(env["root"]).head
    again = review(env["client"], "Zephyr Quorum Widget", status="approved", op_id="click-1")
    assert again.status_code == 200
    assert again.json()["replayed"] is True
    assert again.json()["decided_at"] == first.json()["decided_at"]
    assert again.json()["op_id"] == first.json()["op_id"] == "api:review:key:click-1"
    assert load(env["root"]).head == head  # a replay appends nothing
    conflict = review(env["client"], "Zephyr Quorum Widget", status="rejected", op_id="click-1")
    assert conflict.status_code == 409
    assert load(env["root"]).head == head
    assert load(env["root"]).get(env["ids"]["Zephyr Quorum Widget"]).decision["status"] == "approved"
    bad = review(env["client"], "Zephyr Quorum Widget", status="approved", op_id="no spaces")
    assert bad.status_code == 400


def test_repeat_without_op_id_keeps_the_original_decision_time(env):
    first = review(env["client"], "Zephyr Quorum Widget", status="approve")
    second = review(env["client"], "Zephyr Quorum Widget", status="approved")
    assert first.status_code == second.status_code == 200
    assert second.json()["recorded"] is False
    assert second.json()["decided_at"] == first.json()["decided_at"]
    p = load(env["root"]).get(env["ids"]["Zephyr Quorum Widget"])
    assert len(p.decision_history) == 1


def test_changed_decision_appends_history_and_leaves_the_backlog(env):
    pid = env["ids"]["Zephyr Quorum Widget"]
    assert review(env["client"], "Zephyr Quorum Widget", status="approved").status_code == 200
    assert review(env["client"], "Zephyr Quorum Widget", status="rejected").status_code == 200
    reg = load(env["root"])
    assert [d["status"] for d in reg.get(pid).decision_history] == ["approved", "rejected"]
    assert build_backlog(reg)["proposals"] == []


def test_merge_needs_a_known_target(env):
    ids = env["ids"]
    bad = review(env["client"], "Synthetic Filing Rituals", status="merge")
    assert bad.status_code == 400
    ok = review(env["client"], "Synthetic Filing Rituals", status="merge",
                merge_into=ids["Synthetic Docket Lantern"])
    assert ok.status_code == 200, ok.text
    assert ok.json()["decision"]["merge_into"] == ids["Synthetic Docket Lantern"]
    assert ok.json()["status"] == "merged"


def test_reads_come_from_the_ledger(env):
    client, ids = env["client"], env["ids"]
    # A legacy review.db row says "approved"; the ledger has no decision: reads say pending.
    make_legacy_db(env["out"] / CORPUS / "review.db",
                   rows=[(1, "Synthetic Docket Lantern", CORPUS, "approved", "", "2026-07-01")])

    async def _decide():
        async with await CorpusStorageContext.open(env["root"], CORPUS) as ctx:
            await ProposalStore(ctx).record_decisions(
                [{"proposal_id": ids["Zephyr Quorum Widget"], "status": "approve"}],
                op_id="test:cli-decision", decided_by="human:cli-reviewer",
            )

    asyncio.run(_decide())  # a decision recorded by the CLI path, not the API
    listing = client.get("/api/v1/proposed-classes", params={"corpus": CORPUS})
    assert listing.status_code == 200
    by_id = {p["proposal_id"]: p for p in listing.json()["proposals"]}
    assert set(by_id) == set(ids.values())
    assert by_id[ids["Zephyr Quorum Widget"]]["decision"]["decided_by"] == "human:cli-reviewer"
    assert by_id[ids["Synthetic Docket Lantern"]]["decision"]["status"] == "pending"
    one = client.get("/api/v1/proposed-classes/Zephyr Quorum Widget", params={"corpus": CORPUS})
    assert one.status_code == 200
    assert one.json()["decision"]["status"] == "approved"
    missing = client.get("/api/v1/proposed-classes/Unknown Synthetic Label",
                         params={"corpus": CORPUS})
    assert missing.status_code == 404


def test_reset_keeps_legacy_rows_and_ledger_decisions(env):
    client = env["client"]
    db = make_legacy_db(env["out"] / CORPUS / "review.db",
                        rows=[(1, "Synthetic Docket Lantern", CORPUS, "approved", "", "2026-07-01")])
    assert review(client, "Zephyr Quorum Widget", status="approved").status_code == 200
    r = client.post("/api/v1/review/reset", params={"corpus": CORPUS})
    assert r.status_code == 200, r.text
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM proposed_class_decisions").fetchone()[0] == 1
    conn.close()
    status = load(env["root"]).get(env["ids"]["Zephyr Quorum Widget"]).decision["status"]
    assert status == "approved"


def test_no_storage_root_is_created(env, tmp_path, monkeypatch):
    fresh = tmp_path / "never-created"
    monkeypatch.setattr(api_main, "_corpus_root", fresh)
    listing = env["client"].get("/api/v1/proposed-classes", params={"corpus": CORPUS})
    assert listing.status_code == 200
    assert listing.json() == {"corpus": CORPUS, "ledger_head": -1, "invalid_decision_items": 0,
                              "count": 0, "proposals": []}
    assert review(env["client"], "Zephyr Quorum Widget", status="approved").status_code == 404
    assert not fresh.exists()


def test_storage_root_inside_served_output_is_refused(env, monkeypatch):
    monkeypatch.setattr(api_main, "_corpus_root", env["out"] / "corpora")
    r = review(env["client"], "Zephyr Quorum Widget", status="approved")
    assert r.status_code == 503
    assert not (env["out"] / "corpora").exists()
