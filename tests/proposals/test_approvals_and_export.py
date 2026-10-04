"""Explicit approvals and the approved-only export (governance plan U3, R4).

Synthetic data only. Covers the plan's U3 scenarios:

* a collected proposal stays pending until an explicit decision, and a model
  (or human) judgment never becomes an approval;
* pending, rejected, merged and needs-work proposals never export;
* a repeated identical approval returns the original result and timestamp;
* a changed decision appends provenance and never overwrites;
* an invalid batch (bad status, unknown ID, extra key) records nothing;
* restart then export reproduces the same bytes (real subprocesses);
* the export passes the PII gate and the forbidden-key check;
* the scripts are offline, and their outputs are refused inside git work
  trees and the corpus root.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from folio_insights.proposals import (
    DecisionInvalid,
    ProposalStore,
    build_backlog,
    check_backlog,
)
from folio_insights.proposals.destinations import canonical_json
from folio_insights.proposals.queue import build_queue, render_html
from folio_insights.storage import CorpusStorageContext, OperationIdConflict, PiiGate
from folio_insights.storage.errors import PiiRejected
from folio_insights.storage.proposals import ProposalPayloadRefused

from tests.proposals._synthetic import SOURCE_TEXT_SENTINEL, lexicon, pc

pytestmark = pytest.mark.storage

REPO_ROOT = Path(__file__).resolve().parents[2]
REVIEWER = "human:synthetic-reviewer"


@pytest.fixture
def storage_root(tmp_path: Path) -> Path:
    return tmp_path / "storage"


async def _seed(ctx: CorpusStorageContext) -> dict[str, str]:
    store = ProposalStore(ctx)
    await store.collect_run("run-1", [
        pc("Synthetic Wrong Rule", "u1"),        # alias candidate
        pc("Zephyr Quorum Widget", "u2"),        # novel
        pc("Synthetic Filing Rituals", "u3"),    # merge source
        pc("Synthetic Docket Lantern", "u4"),    # stays pending
    ], spans_by_unit={"u2": [3, 21]})
    await store.collect_run("run-2", [pc("Synthetic Filing Ritual", "u5")])
    await store.apply_dedupe(lexicon())
    reg = await store.load()
    return {
        label: reg.by_label(label).proposal_id
        for label in ("Synthetic Wrong Rule", "Zephyr Quorum Widget",
                      "Synthetic Filing Rituals", "Synthetic Filing Ritual",
                      "Synthetic Docket Lantern")
    }


async def test_collected_proposals_stay_pending_and_judgments_never_approve(storage_root):
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        ids = await _seed(ctx)
        store = ProposalStore(ctx)
        await store.record_judgments(
            [{"proposal_id": ids["Zephyr Quorum Widget"], "verdict": "NOVEL",
              "judged_by": "model:synthetic-judge", "reasoning": "Synthetic: nothing near."}],
            op_id="test:judgment:model",
        )
        reg = await store.load()
        assert {p.decision["status"] for p in reg.all()} == {"pending"}
        assert build_backlog(reg)["proposals"] == []
        # A model cannot record a decision either.
        with pytest.raises(DecisionInvalid, match="human reviewer"):
            await store.record_decisions(
                [{"proposal_id": ids["Zephyr Quorum Widget"], "status": "approve"}],
                op_id="test:decisions:model", decided_by="model:synthetic-judge",
            )
        assert all(p.decision["status"] == "pending" for p in (await store.load()).all())


async def test_only_approved_proposals_export(storage_root):
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        ids = await _seed(ctx)
        store = ProposalStore(ctx)
        result = await store.record_decisions([
            {"proposal_id": ids["Zephyr Quorum Widget"], "status": "approve",
             "note": "Synthetic refined definition."},
            {"proposal_id": ids["Synthetic Wrong Rule"], "status": "reject"},
            {"proposal_id": ids["Synthetic Filing Ritual"], "status": "merge"},
            {"proposal_id": ids["Synthetic Filing Rituals"], "status": "needs_work"},
        ], op_id="test:decisions:1", decided_by=REVIEWER)
        assert result["recorded"] == 4 and not result["replayed"]
        reg = await store.load()
    backlog = build_backlog(reg)
    assert backlog["count"] == 1
    row = backlog["proposals"][0]
    assert row["proposal_id"] == ids["Zephyr Quorum Widget"]
    assert row["decision"]["status"] == "approved"
    assert row["decision"]["reviewer_note"] == "Synthetic refined definition."
    assert row["decision"]["decided_by"] == REVIEWER
    assert row["supporting_units"] == [{"run": "run-1", "unit_id": "u2", "source_span": [3, 21]}]
    # The merge fell back to the MERGE_WITH judgment's target.
    merged = reg.get(ids["Synthetic Filing Ritual"]).decision
    assert merged["status"] == "merged"
    assert merged["merge_into"] == ids["Synthetic Filing Rituals"]
    text = canonical_json(backlog)
    assert SOURCE_TEXT_SENTINEL not in text
    for excluded in ("Synthetic Wrong Rule", "Synthetic Docket Lantern", "Synthetic Filing"):
        assert excluded not in text
    check_backlog(backlog, PiiGate())


async def test_repeated_identical_approval_returns_original_result_and_time(storage_root):
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        ids = await _seed(ctx)
        store = ProposalStore(ctx)
        batch = [{"proposal_id": ids["Zephyr Quorum Widget"], "status": "approve"}]
        first = await store.record_decisions(batch, op_id="test:decisions:a", decided_by=REVIEWER)
        head = await ctx.proposals.head()
        again = await store.record_decisions(batch, op_id="test:decisions:a", decided_by=REVIEWER)
        assert again["replayed"] is True
        assert again["position"] == first["position"]
        assert again["results"] == first["results"]
        assert again["recorded"] == first["recorded"] == 1
        assert await ctx.proposals.head() == head  # a replay appends nothing
        # The same decision under a new op_id is recorded as a no-op batch: it changes
        # nothing and keeps the original time, and a retry of it replays (review P2-1).
        same = await store.record_decisions(batch, op_id="test:decisions:b", decided_by=REVIEWER)
        assert same["recorded"] == 0 and same["unchanged"] == 1 and not same["replayed"]
        assert same["position"] == head + 1
        assert same["results"] == first["results"]
        retry = await store.record_decisions(batch, op_id="test:decisions:b", decided_by=REVIEWER)
        assert retry["replayed"] and retry["position"] == same["position"]
        # Reusing an op_id for a different request is refused.
        with pytest.raises(OperationIdConflict):
            await store.record_decisions(
                [{"proposal_id": ids["Zephyr Quorum Widget"], "status": "reject"}],
                op_id="test:decisions:a", decided_by=REVIEWER,
            )
        assert len((await store.load()).get(ids["Zephyr Quorum Widget"]).decision_history) == 1


async def test_changed_decision_appends_provenance_and_replay_keeps_original(storage_root):
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        ids = await _seed(ctx)
        store = ProposalStore(ctx)
        pid = ids["Zephyr Quorum Widget"]
        approve = [{"proposal_id": pid, "status": "approve"}]
        first = await store.record_decisions(approve, op_id="test:d:1", decided_by=REVIEWER)
        await store.record_decisions(
            [{"proposal_id": pid, "status": "reject", "note": "Synthetic second look."}],
            op_id="test:d:2", decided_by="human:second-reviewer",
        )
        await store.record_decisions(approve, op_id="test:d:3", decided_by=REVIEWER)
        reg = await store.load()
        p = reg.get(pid)
        assert [(d["status"], d["op_id"]) for d in p.decision_history] == [
            ("approved", "test:d:1"), ("rejected", "test:d:2"), ("approved", "test:d:3"),
        ]
        assert p.decision["op_id"] == "test:d:3"
        assert p.decision_history[1]["decided_by"] == "human:second-reviewer"
        positions = [d["ledger_position"] for d in p.decision_history]
        assert positions == sorted(positions) and len(set(positions)) == 3
        # Replaying the first op_id returns the original outcome, and says it is not today's.
        replay = await store.record_decisions(approve, op_id="test:d:1", decided_by=REVIEWER)
        then = {k: replay["results"][pid][k] for k in ("status", "decided_at")}
        assert replay["replayed"] and then == {
            k: first["results"][pid][k] for k in ("status", "decided_at")
        }
        assert replay["superseded_since"] == [pid]
        assert replay["results"][pid]["current_decided_at"] == p.decision["decided_at"]
        assert build_backlog(reg)["proposals"][0]["decision_history_length"] == 3


@pytest.mark.parametrize(
    ("bad", "match"),
    [
        ({"status": "banana"}, "status must be one of"),
        ({"status": "pending"}, "status must be one of"),
        ({"status": "approve", "supporting_excerpt": "x"}, "not allowed"),
        ({"status": "approve", "note": "n" * 501}, "note must be"),
        ({"status": "reject", "merge_into": "PC-0"}, "only allowed with status 'merge'"),
        ({"status": "merge"}, "merge needs merge_into"),
    ],
)
async def test_invalid_batch_records_nothing(storage_root, bad, match):
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        ids = await _seed(ctx)
        store = ProposalStore(ctx)
        head = await ctx.proposals.head()
        batch = [
            {"proposal_id": ids["Zephyr Quorum Widget"], "status": "approve"},
            {"proposal_id": ids["Synthetic Docket Lantern"], **bad},
        ]
        with pytest.raises(DecisionInvalid, match=match) as info:
            await store.record_decisions(batch, op_id="test:bad", decided_by=REVIEWER)
        assert "banana" not in str(info.value) and "x" * 3 not in str(info.value)
        assert await ctx.proposals.head() == head
        assert all(p.decision["status"] == "pending" for p in (await store.load()).all())


async def test_unknown_or_duplicate_ids_refuse_the_whole_batch(storage_root):
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        ids = await _seed(ctx)
        store = ProposalStore(ctx)
        head = await ctx.proposals.head()
        good = {"proposal_id": ids["Zephyr Quorum Widget"], "status": "approve"}
        with pytest.raises(DecisionInvalid, match="not a proposal of this corpus"):
            await store.record_decisions(
                [good, {"proposal_id": "PC-" + "0" * 32, "status": "approve"}],
                op_id="test:unknown", decided_by=REVIEWER,
            )
        with pytest.raises(DecisionInvalid, match="more than once"):
            await store.record_decisions([good, good], op_id="test:dup", decided_by=REVIEWER)
        with pytest.raises(DecisionInvalid, match="at least one"):
            await store.record_decisions([], op_id="test:empty", decided_by=REVIEWER)
        with pytest.raises(ValueError, match="reserved"):
            await store.record_decisions([good], op_id="proposals:x", decided_by=REVIEWER)
        assert await ctx.proposals.head() == head


async def test_other_corpus_ids_are_unknown(storage_root):
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        ids = await _seed(ctx)
    async with await CorpusStorageContext.open(storage_root, "corpus-b") as ctx:
        await ProposalStore(ctx).collect_run("run-1", [pc("Zephyr Quorum Widget", "u1")])
        with pytest.raises(DecisionInvalid, match="not a proposal of this corpus"):
            await ProposalStore(ctx).record_decisions(
                [{"proposal_id": ids["Zephyr Quorum Widget"], "status": "approve"}],
                op_id="test:cross", decided_by=REVIEWER,
            )


def test_check_backlog_refuses_text_keys_and_pii():
    clean = {"schema": "s", "proposals": [{"label": "Synthetic"}]}
    check_backlog(clean, PiiGate())
    with pytest.raises(ProposalPayloadRefused, match="approved-only backlog"):
        check_backlog({"proposals": [{"source_text": "synthetic"}]}, PiiGate())
    with pytest.raises(PiiRejected) as info:
        check_backlog({"proposals": [{"label": "call (212) 555-0142"}]}, PiiGate())
    assert "555-0142" not in str(info.value)


def _run_module(module: str, *args: str, timeout: float = 90.0) -> str:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(REPO_ROOT / "src"), str(REPO_ROOT), env.get("PYTHONPATH", "")]
    )
    result = subprocess.run(
        [sys.executable, "-m", module, *args],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0:
        raise AssertionError(f"{module} exited {result.returncode}\n{result.stderr}")
    return result.stdout


@pytest.mark.timeout(240)
def test_restart_then_export_reproduces_the_same_bytes(storage_root):
    written = _run_module("tests.proposals._proc", "decide", str(storage_root), "corpus-a")
    again = _run_module("tests.proposals._proc", "backlog", str(storage_root), "corpus-a")
    assert written == again
    backlog = json.loads(again)
    assert [r["label"] for r in backlog["proposals"]] == ["Synthetic Wrong Rule"]
    assert backlog["proposals"][0]["decision"]["decided_at"]
    assert SOURCE_TEXT_SENTINEL not in again


async def test_queue_lists_pending_without_preselection_or_source_text(storage_root):
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        ids = await _seed(ctx)
        store = ProposalStore(ctx)
        await store.record_judgments(
            [{"proposal_id": ids["Zephyr Quorum Widget"], "verdict": "NOVEL",
              "judged_by": "model:synthetic-judge"}],
            op_id="test:judgment:novel",
        )
        await store.record_decisions(
            [{"proposal_id": ids["Synthetic Docket Lantern"], "status": "reject"}],
            op_id="test:decide:lantern", decided_by=REVIEWER,
        )
        reg = await store.load()
    queue = build_queue(reg, lexicon())
    assert queue == build_queue(reg, lexicon())
    labels = [e["proposed_label"] for e in queue["entries"]]
    assert labels[0] == "Zephyr Quorum Widget"  # NOVEL first
    assert "Synthetic Docket Lantern" not in labels  # decided
    alias = next(e for e in queue["entries"] if e["proposed_label"] == "Synthetic Wrong Rule")
    assert alias["recommendation"] is None
    assert alias["judgment"]["nearest"] == [] or all(
        "definition" in n for n in alias["judgment"]["nearest"]
    )
    page = render_html(queue)
    assert SOURCE_TEXT_SENTINEL not in page and SOURCE_TEXT_SENTINEL not in json.dumps(queue)
    assert " checked" not in page  # nothing pre-selected
    assert "opt rec" in page  # the recommendation is only marked
    everything = build_queue(reg, include_decided=True)
    assert "Synthetic Docket Lantern" in [e["proposed_label"] for e in everything["entries"]]


def _offline(tmp_path: Path, script: str, *commands: list[str]) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(REPO_ROOT / "src"), str(REPO_ROOT), env.get("PYTHONPATH", "")]
    )
    result = subprocess.run(
        [sys.executable, "-m", "tests.proposals._offline", f"--script={script}",
         *[json.dumps(c) for c in commands]],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.mark.timeout(240)
async def test_cli_round_trip_is_offline_and_idempotent(storage_root, tmp_path):
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        ids = await _seed(ctx)
    outside = tmp_path / "review-outside"
    decisions = outside / "decisions.json"
    outside.mkdir()
    decisions.write_text(json.dumps({
        "schema": "proposed-class-approvals/v1", "corpus": "corpus-a",
        "decisions": {
            ids["Zephyr Quorum Widget"]: {"status": "approve", "note": "Synthetic note."},
            ids["Synthetic Wrong Rule"]: {"status": "reject"},
        },
    }))
    common = ["--corpus", "corpus-a", "--corpus-root", str(storage_root)]
    queue_cmd = [*common, "--out", str(outside / "queue.json"),
                 "--html", str(outside / "queue.html")]
    apply_cmd = ["apply", *common, "--decisions", str(decisions), "--decided-by", REVIEWER]
    export_cmd = ["export", *common, "--out", str(outside / "backlog.json")]
    q = _offline(tmp_path, "build_approval_queue", queue_cmd)
    a = _offline(tmp_path, "apply_approvals", apply_cmd, apply_cmd, export_cmd)
    for run in (q, a):
        assert run["refused_imports"] == [] and run["refused_connections"] == []
        assert set(run["exit_codes"]) == {0}
    first = (outside / "backlog.json").read_bytes()
    _offline(tmp_path, "apply_approvals", export_cmd)
    assert (outside / "backlog.json").read_bytes() == first
    backlog = json.loads(first)
    assert [r["proposal_id"] for r in backlog["proposals"]] == [ids["Zephyr Quorum Widget"]]
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        reg = await ProposalStore(ctx).load()
    decision = reg.get(ids["Zephyr Quorum Widget"]).decision
    assert decision["op_id"].startswith("approvals:")
    assert len(reg.get(ids["Zephyr Quorum Widget"]).decision_history) == 1  # replayed, not doubled
    queue = json.loads((outside / "queue.json").read_text())
    assert queue["counts"]["entries"] >= 1
    assert SOURCE_TEXT_SENTINEL not in (outside / "queue.html").read_text()


def _script(name: str):
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        return __import__(name)
    finally:
        sys.path.remove(str(REPO_ROOT / "scripts"))


@pytest.mark.parametrize("script", ["apply_approvals", "build_approval_queue"])
def test_outputs_refused_inside_git_trees_and_corpus_root(tmp_path, script):
    other = tmp_path / "other-checkout"
    other.mkdir()
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    root = tmp_path / "root"
    root.mkdir()
    mod = _script(script)
    if script == "apply_approvals":
        def run(out):
            return mod.main(["export", "--corpus", "c", "--corpus-root", str(root), "--out", str(out)])
    else:
        def run(out):
            return mod.main(["--corpus", "c", "--corpus-root", str(root), "--out", str(out)])
    for bad in (REPO_ROOT / "docs" / "q.json", other / "new" / "q.json", root / "q.json"):
        with pytest.raises(SystemExit, match="refusing"):
            run(bad)
    assert not (other / "new").exists() and not (root / "q.json").exists()


def test_decisions_file_validation(tmp_path):
    mod = _script("apply_approvals")
    f = tmp_path / "d.json"
    f.write_text(json.dumps({"schema": "other", "decisions": {"PC-1": {"status": "approve"}}}))
    with pytest.raises(DecisionInvalid, match="schema"):
        mod.read_decisions(f, "corpus-a")
    f.write_text(json.dumps({"schema": "proposed-class-approvals/v1", "corpus": "corpus-b",
                             "decisions": {"PC-1": {"status": "approve"}}}))
    with pytest.raises(DecisionInvalid, match="different corpus"):
        mod.read_decisions(f, "corpus-a")
    f.write_text(json.dumps({"schema": "proposed-class-approvals/v1", "decisions": {}}))
    with pytest.raises(DecisionInvalid, match="non-empty"):
        mod.read_decisions(f, "corpus-a")


# ---------- review U3+U4 findings ----------


async def test_replay_reports_current_status_when_superseded(storage_root):
    """P2-1: a replay of an approval that was later rejected shows both outcomes."""
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        ids = await _seed(ctx)
        store = ProposalStore(ctx)
        pid = ids["Zephyr Quorum Widget"]
        await store.record_decisions([{"proposal_id": pid, "status": "approve"}],
                                     op_id="opA", decided_by=REVIEWER)
        await store.record_decisions([{"proposal_id": pid, "status": "reject"}],
                                     op_id="opB", decided_by=REVIEWER)
        replay = await store.record_decisions([{"proposal_id": pid, "status": "approve"}],
                                              op_id="opA", decided_by=REVIEWER)
    assert replay["replayed"]
    assert replay["results"][pid]["status"] == "approved"
    assert replay["results"][pid]["current_status"] == "rejected"
    assert replay["superseded_since"] == [pid]


async def test_retry_of_a_no_op_batch_replays_instead_of_reapplying(storage_root):
    """P2-1: a no-op batch is recorded, so retrying its op_id after a later change replays
    rather than appending (and silently re-approving)."""
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        ids = await _seed(ctx)
        store = ProposalStore(ctx)
        pid = ids["Synthetic Docket Lantern"]
        approve = [{"proposal_id": pid, "status": "approve"}]
        await store.record_decisions(approve, op_id="opC", decided_by=REVIEWER)
        noop = await store.record_decisions(approve, op_id="opD", decided_by=REVIEWER)
        await store.record_decisions([{"proposal_id": pid, "status": "reject"}],
                                     op_id="opE", decided_by=REVIEWER)
        head = await ctx.proposals.head()
        retry = await store.record_decisions(approve, op_id="opD", decided_by=REVIEWER)
        assert retry["replayed"] and retry["position"] == noop["position"]
        assert await ctx.proposals.head() == head
        assert (await store.load()).get(pid).decision["status"] == "rejected"


async def test_fold_ignores_raw_decision_rows_that_bypass_validation(storage_root):
    """P2-2: a raw ledger append cannot approve through a model reviewer, a bogus status,
    an unknown proposal or a bad merge; the rows are reported, nothing exports."""
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        ids = await _seed(ctx)
        z, lantern = ids["Zephyr Quorum Widget"], ids["Synthetic Docket Lantern"]
        raw = [
            {"proposal_id": z, "status": "approved", "note": "", "decided_by": "model:judge",
             "merge_into": None},
            {"proposal_id": lantern, "status": "bogus", "decided_by": REVIEWER},
            {"proposal_id": "PC-" + "0" * 32, "status": "approved", "decided_by": REVIEWER},
            {"proposal_id": lantern, "status": "merged", "decided_by": REVIEWER,
             "merge_into": lantern},
        ]
        await ctx.proposals.append("decision", {"decisions": raw}, op_id="raw:1")
        reg = await ProposalStore(ctx).load()
    assert reg.get(z).decision["status"] == "pending"
    assert reg.get(lantern).decision["status"] == "pending"
    assert [d["item"] for d in reg.invalid_decisions] == [0, 1, 2, 3]
    backlog = build_backlog(reg)
    assert backlog["count"] == 0 and backlog["invalid_decision_items"] == 4
    assert reg.to_dict()["invalid_decisions"][0]["reason"].startswith("decided_by")


@pytest.mark.parametrize(
    "decided_by",
    ["human:jane.doe@example.com", "human:did:key:z6Mkabc", "human:<script>",
     "human:\u200b", "human:role/reviewer", "human:", "model:judge"],
)
async def test_decided_by_must_be_a_plain_reviewer_handle(storage_root, decided_by):
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        ids = await _seed(ctx)
        with pytest.raises(DecisionInvalid, match="human"):
            await ProposalStore(ctx).record_decisions(
                [{"proposal_id": ids["Zephyr Quorum Widget"], "status": "approve"}],
                op_id="test:who", decided_by=decided_by,
            )


def test_paste_back_body_may_not_name_a_different_proposal(tmp_path):
    """P2-3: the decisions key names the proposal; a body proposal_id is refused."""
    mod = _script("apply_approvals")
    f = tmp_path / "d.json"
    f.write_text(json.dumps({"schema": "proposed-class-approvals/v1", "corpus": "c",
                             "decisions": {"PC-A": {"proposal_id": "PC-B", "status": "approve"}}}))
    with pytest.raises(DecisionInvalid, match="must not carry proposal_id"):
        mod.read_decisions(f, "c")


def test_default_op_id_folds_in_the_ledger_head():
    mod = _script("apply_approvals")
    items = [{"proposal_id": "PC-A", "status": "approve"}]
    assert mod.default_op_id("c", REVIEWER, items, 3) == mod.default_op_id("c", REVIEWER, items, 3)
    assert mod.default_op_id("c", REVIEWER, items, 3) != mod.default_op_id("c", REVIEWER, items, 4)


@pytest.mark.timeout(240)
async def test_cli_warns_when_a_replayed_decision_was_superseded(storage_root, tmp_path):
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        ids = await _seed(ctx)
        pid = ids["Zephyr Quorum Widget"]
        store = ProposalStore(ctx)
        await store.record_decisions([{"proposal_id": pid, "status": "approve"}],
                                     op_id="manual:1", decided_by=REVIEWER)
        await store.record_decisions([{"proposal_id": pid, "status": "reject"}],
                                     op_id="manual:2", decided_by=REVIEWER)
    decisions = tmp_path / "d.json"
    decisions.write_text(json.dumps({"schema": "proposed-class-approvals/v1",
                                     "decisions": {pid: {"status": "approve"}}}))
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(REPO_ROOT / "src"), str(REPO_ROOT)])
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "apply_approvals.py"), "apply",
         "--corpus", "corpus-a", "--corpus-root", str(storage_root), "--decisions",
         str(decisions), "--decided-by", REVIEWER, "--op-id", "manual:1"],
        capture_output=True, text=True, env=env, cwd=REPO_ROOT, timeout=120, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "WARNING" in result.stderr and "current_status" in result.stderr
    out = json.loads(result.stdout)
    assert out["replayed"] and out["results"][pid]["current_status"] == "rejected"


async def test_queue_page_inputs_resist_restore_and_offer_a_merge_target(storage_root):
    """Nits: radios carry autocomplete=off, the script reads the shown state, a Merge has a
    target field prefilled from a MERGE_WITH judgment, and the note prompt asks for the
    reviewer's own words with a length cap."""
    from html.parser import HTMLParser

    from folio_insights.proposals.decisions import MAX_NOTE_CHARS

    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        ids = await _seed(ctx)
        reg = await ProposalStore(ctx).load()
    page = render_html(build_queue(reg, lexicon()))

    class _Inputs(HTMLParser):
        def __init__(self):
            super().__init__()
            self.radios, self.merge, self.notes = [], {}, []

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if tag == "input" and a.get("type") == "radio":
                self.radios.append(a)
            if tag == "input" and "data-merge-for" in a:
                self.merge[a["data-merge-for"]] = a
            if tag == "textarea" and "data-pid" in a:
                self.notes.append(a)

    parsed = _Inputs()
    parsed.feed(page)
    assert parsed.radios and all(r.get("autocomplete") == "off" for r in parsed.radios)
    assert not any("checked" in r for r in parsed.radios)
    merge_source = ids["Synthetic Filing Ritual"]
    assert parsed.merge[merge_source]["value"] == ids["Synthetic Filing Rituals"]
    assert all(n.get("maxlength") == str(MAX_NOTE_CHARS) for n in parsed.notes)
    assert "refined definition" not in page and "never paste source text" in page
    assert "if(r.checked)" in page and "merge_into" in page
