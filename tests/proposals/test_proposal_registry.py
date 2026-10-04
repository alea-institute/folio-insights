"""Registry and run ledger on the Phase 13 storage context (U2).

Synthetic data only. Covers: repeated runs create no duplicates, corpus
isolation, deterministic corpus-keyed IDs, case-variant collapse, provenance
merge across runs, the PII gate, append-only enforcement and no source text in
persisted state.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from folio_insights.proposals import ProposalStore, normalize_label, proposal_id
from folio_insights.proposals.registry import SUPPORTING_UNIT_CAP
from folio_insights.storage import (
    CorpusStorageContext,
    JournalStateChanged,
    OperationIdConflict,
    PiiRejected,
)
from folio_insights.storage.journal import JOURNAL_FILENAME

from tests.proposals._synthetic import SOURCE_TEXT_SENTINEL, pc

pytestmark = pytest.mark.storage


@pytest.fixture
def storage_root(tmp_path: Path) -> Path:
    return tmp_path / "storage"


def _raw_ledger(root: Path) -> list[tuple]:
    with sqlite3.connect(root / JOURNAL_FILENAME) as conn:
        return conn.execute(
            "SELECT corpus, position, op_id, kind, payload FROM proposal_ledger "
            "ORDER BY corpus, position"
        ).fetchall()


def test_normalize_and_ids_are_deterministic_and_corpus_keyed():
    assert normalize_label("  Synthetic-Tort  Doctrine A! ") == "synthetic tort doctrine a"
    a = proposal_id("corpus-a", "synthetic tort doctrine a")
    assert a == proposal_id("corpus-a", "synthetic tort doctrine a")
    assert a.startswith("PC-") and len(a) == 35
    assert a != proposal_id("corpus-b", "synthetic tort doctrine a")
    with pytest.raises(ValueError):
        proposal_id("corpus-a", "")


async def test_collect_creates_pending_proposals_without_source_text(storage_root: Path):
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        store = ProposalStore(ctx)
        stats = await store.collect_run(
            "run-1",
            [pc("Synthetic Tort Doctrine A", "u1"), pc("Synthetic Filing Ritual", "u2")],
            spans_by_unit={"u1": [10, 42]},
        )
        reg = await store.load()
    assert stats == {"run": "run-1", "position": 0, "replayed": False,
                     "observations": 2, "new": 2, "dropped": {"empty": 0, "too_long": 0}}
    p = reg.by_label("synthetic tort doctrine a")
    assert p is not None and p.decision["status"] == "pending" and p.judgment is None
    assert p.runs == ["run-1"] and p.occurrences == 1
    assert p.supporting_units[0]["source_span"] == [10, 42]
    assert reg.runs["run-1"]["op_id"] == "proposals:collect:run-1"
    for row in _raw_ledger(storage_root):
        assert SOURCE_TEXT_SENTINEL.encode() not in row[4]
    assert SOURCE_TEXT_SENTINEL not in str(reg.to_dict())


async def test_repeated_run_creates_no_duplicate(storage_root: Path):
    rows = [pc("Synthetic Tort Doctrine A", "u1"), pc("Synthetic Tort Doctrine A", "u2")]
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        store = ProposalStore(ctx)
        first = await store.collect_run("run-1", rows)
        state = (await store.load()).to_dict()
        again = await store.collect_run("run-1", list(reversed(rows)))
        assert again["replayed"] is True and again["new"] == 0
        assert again["position"] == first["position"]
        assert (await store.load()).to_dict() == state
        assert await ctx.proposals.head() == 0
    assert len(_raw_ledger(storage_root)) == 1
    assert len(state["proposals"]) == 1 and state["proposals"][0]["occurrences"] == 2


async def test_same_run_name_with_different_input_is_refused(storage_root: Path):
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        store = ProposalStore(ctx)
        await store.collect_run("run-1", [pc("Synthetic Tort Doctrine A", "u1")])
        with pytest.raises(OperationIdConflict):
            await store.collect_run("run-1", [pc("Synthetic Tort Doctrine B", "u1")])
        assert await ctx.proposals.head() == 0


async def test_new_run_merges_provenance_and_case_variants(storage_root: Path):
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        store = ProposalStore(ctx)
        await store.collect_run("run-1", [pc("Synthetic Tort Doctrine A", "u1")])
        stats = await store.collect_run(
            "run-2", [pc("synthetic tort-doctrine a", "u9"), pc("Synthetic Novel Rite", "u8")]
        )
        reg = await store.load()
    assert stats["new"] == 1
    assert len(reg.proposals) == 2
    p = reg.by_label("Synthetic Tort Doctrine A")
    assert p.proposed_label == "Synthetic Tort Doctrine A"  # first-seen form
    assert p.label_variants == ["Synthetic Tort Doctrine A", "synthetic tort-doctrine a"]
    assert p.runs == ["run-1", "run-2"]
    assert p.run_occurrences == {"run-1": 1, "run-2": 1} and p.occurrences == 2
    assert (p.first_seen_run, p.last_seen_run) == ("run-1", "run-2")
    assert [(s["run"], s["unit_id"]) for s in p.supporting_units] == [
        ("run-1", "u1"), ("run-2", "u9")
    ]


async def test_supporting_units_are_capped(storage_root: Path):
    rows = [pc("Synthetic Tort Doctrine A", f"u{i:02d}") for i in range(SUPPORTING_UNIT_CAP + 5)]
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        store = ProposalStore(ctx)
        await store.collect_run("run-1", rows)
        p = (await store.load()).by_label("Synthetic Tort Doctrine A")
    assert p.occurrences == SUPPORTING_UNIT_CAP + 5
    assert len(p.supporting_units) == SUPPORTING_UNIT_CAP


async def test_corpus_isolation(storage_root: Path):
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as a:
        await ProposalStore(a).collect_run("run-1", [pc("Synthetic Tort Doctrine A", "u1")])
    async with await CorpusStorageContext.open(storage_root, "corpus-b") as b:
        store_b = ProposalStore(b)
        assert (await store_b.load()).proposals == {}
        # The same run name and label in another corpus is a separate operation
        # and a separate proposal.
        stats = await store_b.collect_run("run-1", [pc("Synthetic Tort Doctrine A", "u1")])
        reg_b = await store_b.load()
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as a:
        reg_a = await ProposalStore(a).load()
    assert stats["replayed"] is False and stats["position"] == 0
    (pa,), (pb,) = reg_a.all(), reg_b.all()
    assert pa.proposal_id != pb.proposal_id
    assert pa.proposal_id == proposal_id("corpus-a", "synthetic tort doctrine a")
    assert {r[0] for r in _raw_ledger(storage_root)} == {"corpus-a", "corpus-b"}


async def test_pii_gate_refuses_before_the_journal(storage_root: Path):
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        with pytest.raises(PiiRejected):
            await ProposalStore(ctx).collect_run(
                "run-1", [pc("Synthetic Doctrine 123-45-6789", "u1")]
            )
        assert await ctx.proposals.head() == -1
    assert _raw_ledger(storage_root) == []


async def test_ledger_needs_explicit_op_id_and_honours_expected_head(storage_root: Path):
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        with pytest.raises(ValueError):
            await ctx.proposals.append("collect", {"run": "r"}, op_id="")
        await ctx.proposals.append("collect", {"run": "r", "observations": []}, op_id="op-1")
        with pytest.raises(JournalStateChanged):
            await ctx.proposals.append("judgment", {"judgments": []}, op_id="op-2",
                                       expected_head=-1)
        # A replay of a committed op_id answers before the head check.
        entry, replayed = await ctx.proposals.append(
            "collect", {"run": "r", "observations": []}, op_id="op-1", expected_head=-1
        )
        assert replayed and entry.position == 0
        assert await ctx.proposals.head() == 0


async def test_ledger_is_append_only_and_leaves_the_projection_alone(storage_root: Path):
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        before = await ctx.status()
        await ProposalStore(ctx).collect_run("run-1", [pc("Synthetic Tort Doctrine A", "u1")])
        after = await ctx.status()
    assert (after.journal_head, after.projection_watermark) == (
        before.journal_head, before.projection_watermark
    )
    with sqlite3.connect(storage_root / JOURNAL_FILENAME) as conn:
        for sql in (
            "UPDATE proposal_ledger SET kind = 'x'",
            "DELETE FROM proposal_ledger",
            "INSERT OR REPLACE INTO proposal_ledger SELECT * FROM proposal_ledger",
            "INSERT INTO proposal_ledger (corpus, position, op_id, request_sha256, kind, "
            "record_schema_version, payload, payload_sha256, committed_at) "
            "VALUES ('corpus-a', 5, 'gap', '', 'collect', 1, X'7B7D', '', '')",
        ):
            with pytest.raises(sqlite3.DatabaseError):
                conn.execute(sql)
        assert conn.execute("SELECT COUNT(*) FROM proposal_ledger").fetchone()[0] == 1
        assert conn.execute(
            "SELECT value FROM storage_meta WHERE key = 'proposal_ledger_schema_version'"
        ).fetchone() == ("1",)


def _strip_proposal_ledger(root: Path, *, version: str | None) -> None:
    """Rewind a journal file to its pre-ledger shape (or plant ``version``)."""
    with sqlite3.connect(root / JOURNAL_FILENAME) as conn:
        conn.execute("DROP TABLE proposal_ledger")
        conn.execute("DROP TRIGGER storage_meta_refuse_delete")
        conn.execute("DELETE FROM storage_meta WHERE key = 'proposal_ledger_schema_version'")
        if version is not None:
            conn.execute(
                "INSERT INTO storage_meta VALUES ('proposal_ledger_schema_version', ?)",
                (version,),
            )


async def test_a_journal_from_before_the_ledger_gains_it_on_open(storage_root: Path):
    async with await CorpusStorageContext.open(storage_root, "corpus-a"):
        pass
    _strip_proposal_ledger(storage_root, version=None)
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        await ProposalStore(ctx).collect_run("run-1", [pc("Synthetic Tort Doctrine A", "u1")])
    assert len(_raw_ledger(storage_root)) == 1


async def test_an_unknown_ledger_schema_version_is_refused(storage_root: Path):
    from folio_insights.storage import UnsupportedStorageSchema

    async with await CorpusStorageContext.open(storage_root, "corpus-a"):
        pass
    _strip_proposal_ledger(storage_root, version="99")
    with pytest.raises(UnsupportedStorageSchema):
        await CorpusStorageContext.open(storage_root, "corpus-a")
