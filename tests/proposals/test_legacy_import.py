"""Legacy review.db proposed-class decisions: read-only, imported explicitly.

Synthetic data only. Covers the single-approval-surface plan's U1 scenarios:

* the import records the decided legacy rows of the corpus as ledger decisions
  by ``human:legacy-review-db``, with each row's original ``reviewed_at`` in
  provenance, and they reach the approved-only backlog;
* pending, invalid, unresolved, other-corpus, superseded and PII-bearing rows
  are reported by row ID and skipped;
* the import is idempotent (a second run imports nothing and appends nothing)
  and never overrides a decision the ledger already holds;
* a dry run writes nothing, and the legacy file is never modified;
* once the review.db schema has run, the legacy table refuses writes;
* the ``apply_approvals.py import-legacy`` CLI does the same.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

import pytest

from folio_insights.persistence.review_db import SCHEMA_SQL, read_legacy_proposed_class_rows
from folio_insights.proposals import ProposalStore, build_backlog, check_backlog
from folio_insights.proposals.legacy import (
    LEGACY_REVIEWER,
    LEGACY_SOURCE,
    import_legacy_decisions,
)
from folio_insights.storage import CorpusStorageContext

from tests.proposals._synthetic import pc

pytestmark = pytest.mark.storage

REPO_ROOT = Path(__file__).resolve().parents[2]

# The pre-ledger shape of the table, as review.db files written before this change hold it
# (no read-only triggers).
LEGACY_TABLE = """
CREATE TABLE proposed_class_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_label TEXT NOT NULL,
    corpus_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    reviewer_note TEXT DEFAULT '',
    reviewed_at TEXT,
    UNIQUE(concept_label, corpus_name)
);
"""

ZEPHYR_AT = "2026-07-01T10:00:00.123456+00:00"
LANTERN_AT = "2026-07-02T11:30:00.654321+00:00"

LEGACY_ROWS = [
    # id, label, corpus, status, note, reviewed_at
    (1, "Zephyr Quorum Widget", "corpus-a", "approved", "Synthetic legacy note.", ZEPHYR_AT),
    (2, "Synthetic Docket Lantern", "corpus-a", "rejected", "", LANTERN_AT),
    (3, "Unknown Synthetic Label", "corpus-a", "approved", "", "2026-07-03T00:00:00+00:00"),
    (4, "Synthetic Filing Rituals", "corpus-a", "pending", "", None),
    # Same proposal as row 1 (a punctuation variant), decided earlier: superseded by row 1.
    (5, "zephyr-quorum widget", "corpus-a", "rejected", "", "2026-06-01T00:00:00+00:00"),
    (6, "Zephyr Quorum Widget", "corpus-b", "approved", "", "2026-07-04T00:00:00+00:00"),
    (7, "Synthetic Gavel Prism", "corpus-a", "maybe", "", "2026-07-05T00:00:00+00:00"),
    (8, "Synthetic Ledger Beacon", "corpus-a", "approved", "Call 212-555-0142.",
     "2026-07-06T00:00:00+00:00"),
]


def make_legacy_db(path: Path, rows=LEGACY_ROWS) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(LEGACY_TABLE)
    conn.executemany(
        "INSERT INTO proposed_class_decisions "
        "(id, concept_label, corpus_name, status, reviewer_note, reviewed_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()
    return path


async def seed(ctx: CorpusStorageContext) -> dict[str, str]:
    store = ProposalStore(ctx)
    labels = ["Zephyr Quorum Widget", "Synthetic Docket Lantern", "Synthetic Filing Rituals",
              "Synthetic Gavel Prism", "Synthetic Ledger Beacon"]
    await store.collect_run("run-1", [pc(label, f"u{i}") for i, label in enumerate(labels)])
    reg = await store.load()
    return {label: reg.by_label(label).proposal_id for label in labels}


@pytest.fixture
def storage_root(tmp_path: Path) -> Path:
    return tmp_path / "storage"


async def test_import_records_decided_rows_with_original_timestamps(storage_root, tmp_path):
    db = make_legacy_db(tmp_path / "out" / "corpus-a" / "review.db")
    before = db.read_bytes()
    rows = read_legacy_proposed_class_rows(db)
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        ids = await seed(ctx)
        report = await import_legacy_decisions(ctx, rows)
        reg = await ProposalStore(ctx).load()
        backlog = build_backlog(reg)
        check_backlog(backlog, ctx.config.pii_gate)

    assert report["imported"] == [1, 2]
    assert report["skipped_pending"] == [4]
    assert report["unresolved_rows"] == [3]
    assert report["superseded_rows"] == [5]
    assert report["other_corpus_rows"] == 1
    assert report["invalid_rows"] == [7]
    assert report["pii_refused_rows"] == [8]
    assert report["op_id"].startswith("legacy-review-db:") and not report["replayed"]
    # Reports name row IDs, never labels or notes.
    assert "Zephyr" not in json.dumps(report) and "212-555" not in json.dumps(report)

    zephyr = reg.get(ids["Zephyr Quorum Widget"]).decision
    assert zephyr["status"] == "approved"
    assert zephyr["decided_by"] == LEGACY_REVIEWER
    assert zephyr["note"] == "Synthetic legacy note."
    assert zephyr["provenance"]["source"] == LEGACY_SOURCE
    assert zephyr["provenance"]["legacy_row_id"] == 1
    assert zephyr["provenance"]["legacy_reviewed_at"] == ZEPHYR_AT
    lantern = reg.get(ids["Synthetic Docket Lantern"]).decision
    assert lantern["status"] == "rejected"
    assert lantern["provenance"]["legacy_reviewed_at"] == LANTERN_AT
    for label in ("Synthetic Filing Rituals", "Synthetic Gavel Prism", "Synthetic Ledger Beacon"):
        assert reg.get(ids[label]).decision["status"] == "pending"

    # The approved legacy decision reaches the approved-only backlog, with its provenance.
    assert [r["proposal_id"] for r in backlog["proposals"]] == [ids["Zephyr Quorum Widget"]]
    assert backlog["proposals"][0]["decision"]["provenance"]["legacy_reviewed_at"] == ZEPHYR_AT
    # The legacy file is opened read-only and never changes.
    assert db.read_bytes() == before


async def test_import_is_idempotent(storage_root, tmp_path):
    db = make_legacy_db(tmp_path / "review.db")
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        ids = await seed(ctx)
        first = await import_legacy_decisions(ctx, read_legacy_proposed_class_rows(db))
        head = await ctx.proposals.head()
        decided_at = (await ProposalStore(ctx).load()).get(
            ids["Zephyr Quorum Widget"]).decision["decided_at"]
        second = await import_legacy_decisions(ctx, read_legacy_proposed_class_rows(db))
        assert await ctx.proposals.head() == head  # nothing appended
        reg = await ProposalStore(ctx).load()
    assert first["imported"] == [1, 2]
    assert second["imported"] == [] and second["op_id"] is None
    assert second["already_imported"] == [1, 2]
    zephyr = reg.get(ids["Zephyr Quorum Widget"])
    assert zephyr.decision["decided_at"] == decided_at
    assert len(zephyr.decision_history) == 1


async def test_import_never_overrides_a_ledger_decision(storage_root, tmp_path):
    db = make_legacy_db(tmp_path / "review.db")
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        ids = await seed(ctx)
        store = ProposalStore(ctx)
        await store.record_decisions(
            [{"proposal_id": ids["Synthetic Docket Lantern"], "status": "approve"}],
            op_id="test:decide:lantern", decided_by="human:synthetic-reviewer",
        )
        report = await import_legacy_decisions(ctx, read_legacy_proposed_class_rows(db))
        lantern = (await store.load()).get(ids["Synthetic Docket Lantern"]).decision
    assert report["already_decided"] == [2]
    assert report["imported"] == [1]
    assert lantern["status"] == "approved"
    assert lantern["decided_by"] == "human:synthetic-reviewer"
    assert "provenance" not in lantern


async def test_dry_run_writes_nothing(storage_root, tmp_path):
    db = make_legacy_db(tmp_path / "review.db")
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        await seed(ctx)
        head = await ctx.proposals.head()
        report = await import_legacy_decisions(
            ctx, read_legacy_proposed_class_rows(db), dry_run=True
        )
        assert await ctx.proposals.head() == head
    assert report["dry_run"] is True
    assert report["would_import"] == [1, 2] and report["imported"] == []


async def test_legacy_corpus_name_can_differ(storage_root, tmp_path):
    db = make_legacy_db(tmp_path / "review.db")
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        await seed(ctx)
        report = await import_legacy_decisions(
            ctx, read_legacy_proposed_class_rows(db), legacy_corpus="corpus-b"
        )
    assert report["imported"] == [6]
    assert report["other_corpus_rows"] == 7


def test_reading_never_creates_or_alters_a_database(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_legacy_proposed_class_rows(tmp_path / "absent.db")
    assert not (tmp_path / "absent.db").exists()
    empty = tmp_path / "empty.db"
    sqlite3.connect(empty).close()
    assert read_legacy_proposed_class_rows(empty) == []


def test_legacy_table_is_read_only_once_the_schema_runs(tmp_path):
    db = make_legacy_db(tmp_path / "review.db")
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA_SQL)  # what every review.db open does
    for statement in (
        "INSERT INTO proposed_class_decisions (concept_label, corpus_name, status) "
        "VALUES ('Synthetic New Label', 'corpus-a', 'approved')",
        "UPDATE proposed_class_decisions SET status = 'rejected' WHERE id = 1",
        "DELETE FROM proposed_class_decisions WHERE corpus_name = 'corpus-a'",
    ):
        with pytest.raises(sqlite3.DatabaseError, match="read-only legacy"):
            conn.execute(statement)
    conn.close()
    assert [r["id"] for r in read_legacy_proposed_class_rows(db)] == [1, 2, 3, 4, 5, 6, 7, 8]


def _apply_approvals():
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        return __import__("apply_approvals")
    finally:
        sys.path.remove(str(REPO_ROOT / "scripts"))


def test_cli_import_legacy_is_explicit_and_idempotent(storage_root, tmp_path, capsys):
    db = make_legacy_db(tmp_path / "out" / "corpus-a" / "review.db")

    async def _seed_only():
        async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
            await seed(ctx)

    asyncio.run(_seed_only())
    cli = _apply_approvals()
    common = ["import-legacy", "--corpus", "corpus-a", "--corpus-root", str(storage_root),
              "--review-db", str(db)]

    def run(*extra: str) -> dict:
        assert cli.main([*common, *extra]) == 0
        return json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    dry = run("--dry-run")
    assert dry["would_import"] == [1, 2] and dry["imported"] == []
    first = run()
    assert first["imported"] == [1, 2]
    again = run()
    assert again["imported"] == [] and again["already_imported"] == [1, 2]
    with pytest.raises(SystemExit, match="refused"):
        cli.main(["import-legacy", "--corpus", "corpus-a", "--corpus-root", str(storage_root),
                  "--review-db", str(tmp_path / "absent.db")])


@pytest.mark.parametrize("bad", [
    {"Not-A-Key": "x"},
    {"source": "x" * 201},
    {"source": {"nested": "x"}},
    {},
    {f"k{i}": i for i in range(9)},
])
async def test_record_decisions_refuses_bad_provenance(storage_root, bad):
    from folio_insights.proposals import DecisionInvalid

    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        ids = await seed(ctx)
        store = ProposalStore(ctx)
        head = await ctx.proposals.head()
        pid = ids["Zephyr Quorum Widget"]
        with pytest.raises(DecisionInvalid):
            await store.record_decisions(
                [{"proposal_id": pid, "status": "approve"}], op_id="test:prov:bad",
                decided_by="human:synthetic-reviewer", provenance={pid: bad},
            )
        # Provenance for a proposal outside the batch refuses it all, too.
        with pytest.raises(DecisionInvalid):
            await store.record_decisions(
                [{"proposal_id": pid, "status": "approve"}], op_id="test:prov:other",
                decided_by="human:synthetic-reviewer",
                provenance={ids["Synthetic Docket Lantern"]: {"source": "x"}},
            )
        assert await ctx.proposals.head() == head


async def test_fold_ignores_a_raw_item_with_bad_provenance(storage_root):
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        ids = await seed(ctx)
        pid = ids["Zephyr Quorum Widget"]
        await ctx.proposals.append("decision", {"decisions": [{
            "proposal_id": pid, "status": "approved", "note": "",
            "decided_by": "human:synthetic-reviewer", "merge_into": None,
            "provenance": {"source": ["not", "scalar"]},
        }]}, op_id="raw:prov:1")
        reg = await ProposalStore(ctx).load()
    assert reg.get(pid).decision["status"] == "pending"
    assert reg.invalid_decisions[0]["reason"].startswith("provenance")
