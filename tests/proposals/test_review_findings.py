"""Regressions for the U1+U2 independent review (P2-1..P2-8 and nits).

Synthetic data only. Each test failed against the code before its fix.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from folio_insights.proposals import (
    FolioLexicon,
    ProposalStore,
    build_worklist,
    collect_payload,
    normalize_label,
    proposal_id,
)
from folio_insights.proposals.judgments import judgment_view
from folio_insights.proposals.store import LexiconTooSmall
from folio_insights.storage import CorpusStorageContext, PiiRejected
from folio_insights.storage.backup import (
    SNAPSHOT_MANIFEST,
    SnapshotError,
    restore_storage,
    snapshot_storage,
)
from folio_insights.storage.journal import JOURNAL_FILENAME

from tests.proposals._synthetic import IRI_TORT, SOURCE_TEXT_SENTINEL, lexicon, pc

pytestmark = pytest.mark.storage

REPO_ROOT = Path(__file__).resolve().parents[2]
PHONE = "(212) 555-0142"  # NANP fictional-range number


@pytest.fixture
def storage_root(tmp_path: Path) -> Path:
    return tmp_path / "storage"


async def _one_proposal(root: Path, label: str = "Zephyr Quorum Widget") -> str:
    async with await CorpusStorageContext.open(root, "corpus-a") as ctx:
        store = ProposalStore(ctx)
        await store.collect_run("run-1", [pc(label, "u1"), pc("Synthetic Novel Rite", "u2")])
        return (await store.load()).by_label(label).proposal_id


def _ledger_rows(root: Path) -> list[tuple]:
    with sqlite3.connect(root / JOURNAL_FILENAME) as conn:
        return conn.execute(
            "SELECT corpus, position, op_id, payload FROM proposal_ledger ORDER BY position"
        ).fetchall()


# ---------- P2-1: the refuse-replace trigger is exercised ----------


async def test_replace_paths_at_a_new_contiguous_position_are_refused(storage_root: Path):
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        store = ProposalStore(ctx)
        await store.collect_run("run-1", [pc("Synthetic Tort Doctrine A", "u1")])
        await store.collect_run("run-2", [pc("Synthetic Tort Doctrine B", "u2")])
    before = _ledger_rows(storage_root)
    cols = ("corpus, 2, op_id, request_sha256, kind, record_schema_version, payload, "
            "payload_sha256, committed_at")
    statements = (
        # position 2 is the next contiguous one, so only refuse_replace can stop these
        f"INSERT OR REPLACE INTO proposal_ledger SELECT {cols} FROM proposal_ledger "
        "WHERE position = 0",
        f"INSERT INTO proposal_ledger SELECT {cols} FROM proposal_ledger WHERE position = 0 "
        "ON CONFLICT(corpus, op_id) DO UPDATE SET kind = 'x'",
        f"INSERT OR IGNORE INTO proposal_ledger SELECT {cols} FROM proposal_ledger "
        "WHERE position = 0",
    )
    with sqlite3.connect(storage_root / JOURNAL_FILENAME) as conn:
        for sql in statements:
            with pytest.raises(sqlite3.DatabaseError, match="insert over a committed row"):
                conn.execute(sql)
    assert _ledger_rows(storage_root) == before


# ---------- P2-2: PII gate covers op_id and integers; errors never echo input ----------


async def test_pii_in_a_caller_op_id_is_refused(storage_root: Path):
    pid = await _one_proposal(storage_root)
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        with pytest.raises(PiiRejected) as err:
            await ProposalStore(ctx).record_judgments(
                [{"proposal_id": pid, "verdict": "NOVEL", "judged_by": "human:r"}],
                op_id=f"review by {PHONE}",
            )
        assert PHONE not in str(err.value)
        assert await ctx.proposals.head() == 0


@pytest.mark.parametrize("field", ["proposal_id", "verdict", "judged_by"])
async def test_judgment_validation_errors_never_echo_input(storage_root: Path, field: str):
    pid = await _one_proposal(storage_root)
    item = {"proposal_id": pid, "verdict": "NOVEL", "judged_by": "human:r"}
    item[field] = f"{item[field]} {PHONE}" if field != "judged_by" else "x" * 101 + PHONE
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        with pytest.raises(ValueError) as err:
            await ProposalStore(ctx).record_judgments([item], op_id="t:echo")
    assert PHONE not in str(err.value) and "judgment item 0" in str(err.value)


def _aba_int() -> int:
    """A synthetic 9-digit integer that passes the ABA checksum (prefix 21)."""
    for n in range(210_000_000, 210_001_000):
        d = [int(c) for c in str(n)]
        if (3 * (d[0] + d[3] + d[6]) + 7 * (d[1] + d[4] + d[7]) + d[2] + d[5] + d[8]) % 10 == 0:
            return n
    raise AssertionError("no checksum-valid synthetic number found")


async def test_integer_leaves_are_scanned_by_the_ledger(storage_root: Path):
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        with pytest.raises(PiiRejected, match="aba_routing"):
            await ctx.proposals.append(
                "judgment", {"judgments": [], "n": _aba_int()}, op_id="t:int"
            )
        # An integer is scanned as its decimal text: no separators, no phone match.
        await ctx.proposals.append("judgment", {"judgments": [], "n": 2125550142}, op_id="ok")
        assert await ctx.proposals.head() == 0


# ---------- P2-3: no excerpts through judgments, labels or the worklist ----------


@pytest.mark.parametrize(
    "extra",
    [
        {"nearest": [{"iri": IRI_TORT, "excerpt": SOURCE_TEXT_SENTINEL}]},
        {"nearest": [{"iri": IRI_TORT, "definition": SOURCE_TEXT_SENTINEL}]},
        {"excerpt": SOURCE_TEXT_SENTINEL},
        {"reasoning": "r" * 501},
    ],
)
async def test_judgments_cannot_carry_excerpts(storage_root: Path, extra: dict):
    pid = await _one_proposal(storage_root)
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        with pytest.raises(ValueError):
            await ProposalStore(ctx).record_judgments(
                [{"proposal_id": pid, "verdict": "NEEDS_WORK", "judged_by": "model:x", **extra}],
                op_id="t:excerpt",
            )
        assert await ctx.proposals.head() == 0
    assert all(SOURCE_TEXT_SENTINEL.encode() not in r[3] for r in _ledger_rows(storage_root))


async def test_text_keys_are_refused_anywhere_in_a_ledger_payload(storage_root: Path):
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        for payload in ({"a": [{"b": {"source_text": "x"}}]}, {"Excerpt": "x"}):
            with pytest.raises(ValueError, match="forbidden text key"):
                await ctx.proposals.append("judgment", payload, op_id="t:text")
        assert await ctx.proposals.head() == -1


def test_passage_length_labels_are_dropped_and_counted():
    payload = collect_payload("corpus-a", "run-1", [
        pc("SYNTHETIC LONG PASSAGE " * 20, "u1"), pc("   ", "u2"), pc("!!!", "u3"),
        pc("Synthetic Novel Rite", "u4"),
    ])
    assert [o["unit_id"] for o in payload["observations"]] == ["u4"]
    assert payload["dropped"] == {"empty": 2, "too_long": 1}


def test_worklist_emits_only_validated_judgment_fields():
    stored = {
        "verdict": "NEEDS_WORK", "judged_by": "model:x", "reasoning": "ok",
        "target_iri": None, "target_proposal_id": None,
        "nearest": [{"iri": IRI_TORT, "label": "L", "match_form": "alt", "score": 1.0,
                     "excerpt": SOURCE_TEXT_SENTINEL}],
        "source_text": SOURCE_TEXT_SENTINEL, "ledger_position": 3,
    }
    view = judgment_view(stored)
    assert SOURCE_TEXT_SENTINEL not in json.dumps(view)
    assert set(view["nearest"][0]) == {"iri", "label", "match_form", "score"}


async def test_probe_p3_shape_cannot_reach_the_worklist(storage_root: Path):
    pid = await _one_proposal(storage_root)
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        store = ProposalStore(ctx)
        with pytest.raises(ValueError):
            await store.record_judgments([{
                "proposal_id": pid, "verdict": "ALIAS_CANDIDATE", "judged_by": "model:x",
                "reasoning": "unit says: <synthetic>",
                "nearest": [{"excerpt": SOURCE_TEXT_SENTINEL, "source_text": SOURCE_TEXT_SENTINEL}],
            }], op_id="m1")
        reg = await store.load()
    assert SOURCE_TEXT_SENTINEL not in json.dumps(build_worklist(reg, lexicon()))


# ---------- P2-4: worklist destination inside any git checkout ----------


def _script():
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        import judge_proposals
    finally:
        sys.path.remove(str(REPO_ROOT / "scripts"))
    return judge_proposals


def test_worklist_refused_inside_another_git_work_tree(tmp_path: Path):
    other = tmp_path / "other-checkout"
    other.mkdir()
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    jp = _script()
    with pytest.raises(SystemExit, match="git work tree"):
        jp.check_worklist_destination(other / "docs" / "new-dir" / "w.json", tmp_path / "root")
    with pytest.raises(SystemExit, match="git work tree"):
        jp.check_worklist_destination(other / ".git" / "w.json", tmp_path / "root")


def test_worklist_destination_is_resolved_through_symlinks(tmp_path: Path):
    jp = _script()
    link = tmp_path / "link-to-repo"
    link.symlink_to(REPO_ROOT, target_is_directory=True)
    with pytest.raises(SystemExit, match="refusing"):
        jp.check_worklist_destination(link / "docs" / "w.json", tmp_path / "root")
    real = tmp_path / "review"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    assert jp.check_worklist_destination(alias / "w.json", tmp_path / "root") == (
        real / "w.json"
    ).resolve()


# ---------- P2-5: an empty or wrong lexicon cannot clear the verdicts ----------


def test_an_empty_lexicon_file_is_refused(tmp_path: Path):
    owl = tmp_path / "not-folio.owl"
    owl.write_text("<rdf:RDF></rdf:RDF>")
    with pytest.raises(ValueError, match="no FOLIO classes"):
        FolioLexicon.load(owl)


async def test_dedupe_refuses_a_tiny_lexicon(storage_root: Path):
    await _one_proposal(storage_root, "Synthetic Tort Doctrine")
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        store = ProposalStore(ctx)
        await store.apply_dedupe(lexicon())
        head = await ctx.proposals.head()
        with pytest.raises(LexiconTooSmall):
            await store.apply_dedupe(FolioLexicon.from_concepts([]))
        assert await ctx.proposals.head() == head
        assert (await store.load()).by_label("Synthetic Tort Doctrine").judgment is not None


# ---------- P2-6: Unicode-aware normalization ----------


def test_normalization_is_unicode_aware():
    assert normalize_label("Société Anonyme") == normalize_label("societe anonyme")
    assert normalize_label("Ärzterecht") != normalize_label("Ürzterecht")
    assert normalize_label("合同法") == "合同法"
    assert normalize_label("Δίκαιο") == "δικαιο"
    assert normalize_label("synthetic_tort__doctrine") == "synthetic tort doctrine"
    assert proposal_id("c", normalize_label("Café")) == proposal_id("c", normalize_label("cafe"))
    payload = collect_payload("c", "r", [{"proposed_label": "合同法", "source_unit_id": "u"}])
    assert len(payload["observations"]) == 1 and payload["dropped"]["empty"] == 0


# ---------- P2-7: snapshot and restore carry and verify the ledger ----------


async def test_snapshot_manifest_and_restore_cover_ledger_only_corpora(tmp_path: Path):
    root = tmp_path / "root"
    async with await CorpusStorageContext.open(root, "ledger-only") as ctx:
        await ProposalStore(ctx).collect_run("run-1", [pc("Synthetic Tort Doctrine", "u1")])
    snap = await snapshot_storage(root, tmp_path / "snap")
    entry = snap.manifest["corpora"]["ledger-only"]
    assert entry["journal_head"] == -1 and entry["proposal_head"] == 0
    assert entry["proposal_rows"] == 1 and len(entry["proposal_head_payload_sha256"]) == 64
    restored = await restore_storage(tmp_path / "snap", tmp_path / "restored")
    assert "ledger-only" in restored.corpora
    async with await CorpusStorageContext.open(restored.path, "ledger-only") as ctx:
        assert len((await ProposalStore(ctx).load()).proposals) == 1


async def test_restore_refuses_a_manifest_that_misstates_the_ledger(tmp_path: Path):
    root = tmp_path / "root"
    async with await CorpusStorageContext.open(root, "corpus-a") as ctx:
        await ProposalStore(ctx).collect_run("run-1", [pc("Synthetic Tort Doctrine", "u1")])
    await snapshot_storage(root, tmp_path / "snap")
    manifest_path = tmp_path / "snap" / SNAPSHOT_MANIFEST
    manifest = json.loads(manifest_path.read_text())
    legacy = json.loads(json.dumps(manifest))
    manifest["corpora"]["corpus-a"]["proposal_head"] = 5
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(SnapshotError):
        await restore_storage(tmp_path / "snap", tmp_path / "r1")
    # A pre-ledger manifest (no proposal fields) cannot vouch for ledger rows.
    for v in legacy["corpora"].values():
        for k in ("proposal_head", "proposal_head_payload_sha256", "proposal_rows"):
            v.pop(k)
    manifest_path.write_text(json.dumps(legacy))
    with pytest.raises(SnapshotError):
        await restore_storage(tmp_path / "snap", tmp_path / "r2")


async def test_snapshot_refuses_an_unknown_ledger_schema(tmp_path: Path):
    root = tmp_path / "root"
    async with await CorpusStorageContext.open(root, "corpus-a") as ctx:
        await ProposalStore(ctx).collect_run("run-1", [pc("Synthetic Tort Doctrine", "u1")])
    with sqlite3.connect(root / JOURNAL_FILENAME) as conn:
        conn.execute("DROP TRIGGER storage_meta_refuse_update")
        conn.execute(
            "UPDATE storage_meta SET value = '99' WHERE key = 'proposal_ledger_schema_version'"
        )
    with pytest.raises(SnapshotError, match="proposal ledger schema"):
        await snapshot_storage(root, tmp_path / "snap")


# ---------- P2-8: deeper judgment validation and reserved op_ids ----------


@pytest.mark.parametrize(
    "bad",
    [
        {"verdict": "MERGE_WITH"},
        {"verdict": "MERGE_WITH", "target_proposal_id": "PC-" + "0" * 32},
        {"verdict": "DUPLICATE_OF"},
        {"verdict": "SYNONYM_OF", "target_proposal_id": "PC-" + "0" * 32,
         "target_iri": IRI_TORT},
        {"verdict": "ALIAS_CANDIDATE"},
    ],
)
async def test_verdicts_need_valid_targets(storage_root: Path, bad: dict):
    pid = await _one_proposal(storage_root)
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        with pytest.raises(ValueError):
            await ProposalStore(ctx).record_judgments(
                [{"proposal_id": pid, "judged_by": "human:r", **bad}], op_id="t:target"
            )
        assert await ctx.proposals.head() == 0


async def test_valid_merge_and_duplicate_judgments_are_recorded(storage_root: Path):
    pid = await _one_proposal(storage_root)
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        store = ProposalStore(ctx)
        other = (await store.load()).by_label("Synthetic Novel Rite").proposal_id
        r = await store.record_judgments([
            {"proposal_id": pid, "verdict": "MERGE_WITH", "target_proposal_id": other,
             "judged_by": "human:r"},
            {"proposal_id": other, "verdict": "DUPLICATE_OF", "target_iri": IRI_TORT,
             "judged_by": "human:r"},
        ], op_id="t:valid")
    assert r["recorded"] == 2


async def test_reserved_op_id_prefix_is_refused(storage_root: Path):
    pid = await _one_proposal(storage_root)
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        with pytest.raises(ValueError, match="reserved"):
            await ProposalStore(ctx).record_judgments(
                [{"proposal_id": pid, "verdict": "NOVEL", "judged_by": "human:r"}],
                op_id="proposals:collect:run-9",
            )


# ---------- nits ----------


async def test_an_id_that_maps_to_two_labels_is_refused_on_fold(storage_root: Path):
    pid = proposal_id("corpus-a", "synthetic label one")
    obs = {"proposal_id": pid, "proposed_label": "x", "unit_id": "u", "source_span": None,
           "extraction_path": "", "confidence": 0.5}
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        await ctx.proposals.append("collect", {"run": "r1", "observations": [
            {**obs, "normalized_label": "synthetic label one"}]}, op_id="t:c1")
        await ctx.proposals.append("collect", {"run": "r2", "observations": [
            {**obs, "normalized_label": "synthetic label two"}]}, op_id="t:c2")
        with pytest.raises(ValueError, match="more than one normalized label"):
            await ProposalStore(ctx).load()
