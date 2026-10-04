"""Worklist generation (offline, no model call) and restart provenance (U2).

Synthetic data only. The cross-process tests run real OS subprocesses: one
writes, a fresh one reads, and the offline test runs the CLI under a guard
that refuses sockets and model-client imports.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from folio_insights.proposals import ProposalStore, build_worklist
from folio_insights.storage import CorpusStorageContext

from tests.proposals._synthetic import IRI_TORT, SOURCE_TEXT_SENTINEL, lexicon, pc

pytestmark = pytest.mark.storage

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_module(module: str, *args: str, timeout: float = 60.0) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(REPO_ROOT / "src"), str(REPO_ROOT), env.get("PYTHONPATH", "")]
    )
    result = subprocess.run(
        [sys.executable, "-m", module, *args],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"{module} exited {result.returncode}\nstdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.fixture
def storage_root(tmp_path: Path) -> Path:
    return tmp_path / "storage"


async def _seed(root: Path) -> None:
    async with await CorpusStorageContext.open(root, "corpus-a") as ctx:
        store = ProposalStore(ctx)
        await store.collect_run("run-1", [
            pc("Synthetic Tort Doctrine", "u1"),       # primary hit: deduped away
            pc("Synthetic Wrong Rule", "u2"),          # alias: stays in the worklist
            pc("Synthetic Remedy Principal", "u3"),    # near a FOLIO label
            pc("Zephyr Quorum Widget", "u4"),          # nothing near: floored
            pc("Synthetic Filing Rituals", "u5"),
        ], spans_by_unit={"u3": [5, 30]})
        await store.collect_run("run-2", [pc("Synthetic Filing Ritual", "u6")])
        await store.apply_dedupe(lexicon())


async def test_worklist_splits_survivors_and_carries_no_source_text(storage_root: Path):
    await _seed(storage_root)
    async with await CorpusStorageContext.open(storage_root, "corpus-a") as ctx:
        reg = await ProposalStore(ctx).load()
    wl = build_worklist(reg, lexicon())
    assert wl == build_worklist(reg, lexicon())  # deterministic
    items = {i["proposed_label"]: i for i in wl["items"]}
    floored = {i["proposed_label"]: i for i in wl["floored"]}
    assert set(items) == {"Synthetic Wrong Rule", "Synthetic Remedy Principal"}
    assert set(floored) == {"Zephyr Quorum Widget", "Synthetic Filing Rituals"}
    alias = items["Synthetic Wrong Rule"]
    assert alias["current_judgment"]["verdict"] == "ALIAS_CANDIDATE"
    assert any(c["iri"] == IRI_TORT and c["definition"] for c in alias["candidates"])
    near = items["Synthetic Remedy Principal"]
    assert near["candidates"][0]["label"] == "Synthetic Remedy Principle"
    assert near["provenance"]["units"] == [
        {"run": "run-1", "unit_id": "u3", "source_span": [5, 30]}
    ]
    assert floored["Zephyr Quorum Widget"]["recommendation"] == "NOVEL"
    dumped = json.dumps(wl)
    assert SOURCE_TEXT_SENTINEL not in dumped
    assert "excerpt" not in dumped and "source_text" not in dumped


def test_restart_preserves_provenance_across_processes(storage_root: Path):
    written = _run_module("tests.proposals._proc", "write", str(storage_root), "corpus-a")
    read = _run_module("tests.proposals._proc", "read", str(storage_root), "corpus-a")
    assert read == written
    by_label = {p["proposed_label"]: p for p in read["proposals"]}
    alias = by_label["Synthetic Wrong Rule"]
    assert alias["provenance"]["runs"] == ["run-1", "run-2"]
    assert alias["label_variants"] == ["Synthetic Wrong Rule", "synthetic wrong-rule"]
    assert [(s["run"], s["unit_id"]) for s in alias["supporting_units"]] == [
        ("run-1", "u3"), ("run-2", "u8")
    ]
    # The human judgment survives the restart and the later dedupe.
    assert alias["judgment"]["judged_by"] == "human:synthetic-reviewer"
    assert [h["op_id"] for h in alias["judgment_history"]] == ["proc:judgment:1"]
    assert by_label["Synthetic Tort Doctrine"]["supporting_units"][0]["source_span"] == [0, 12]
    assert by_label["Synthetic Filing Ritual"]["judgment"]["verdict"] == "MERGE_WITH"
    assert read["runs"]["run-1"]["op_id"] == "proposals:collect:run-1"
    assert read["runs"]["run-2"]["position"] == 1
    assert read["ledger_head"] == 3


def _write_run_dir(path: Path) -> Path:
    path.mkdir(parents=True)
    rows = [pc("Synthetic Wrong Rule", "u1"), pc("Synthetic Remedy Principal", "u2"),
            pc("Zephyr Quorum Widget", "u3")]
    (path / "proposed_classes.json").write_text(json.dumps({"proposed_classes": rows}))
    (path / "discovery.json").write_text(json.dumps({"knowledge_units": [
        {"id": "u2", "original_span": {"start": 3, "end": 9}},
    ]}))
    return path


def test_cli_worklist_generation_makes_no_model_or_network_call(tmp_path: Path):
    root = tmp_path / "storage"
    run_dir = _write_run_dir(tmp_path / "runs" / "run-1")
    lex_path = tmp_path / "lexicon.json"
    lexicon().to_json(lex_path)
    out = tmp_path / "review" / "worklist.json"
    common = ["--corpus", "corpus-a", "--corpus-root", str(root)]
    report = _run_module(
        "tests.proposals._offline",
        json.dumps(["collect", *common, "--run-dir", str(run_dir)]),
        json.dumps(["dedupe", *common, "--lexicon", str(lex_path)]),
        json.dumps(["worklist", *common, "--lexicon", str(lex_path), "--out", str(out)]),
    )
    assert report["exit_codes"] == [0, 0, 0]
    assert report["preloaded"] == []
    assert report["refused_imports"] == []
    assert report["refused_connections"] == []
    wl = json.loads(out.read_text())
    assert wl["counts"] == {"items": 2, "floored": 1}
    assert {i["proposed_label"] for i in wl["items"]} == {
        "Synthetic Wrong Rule", "Synthetic Remedy Principal"
    }
    assert SOURCE_TEXT_SENTINEL not in out.read_text()


def test_cli_refuses_a_worklist_inside_the_repository(tmp_path: Path):
    lex_path = tmp_path / "lexicon.json"
    lexicon().to_json(lex_path)
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        import judge_proposals
    finally:
        sys.path.remove(str(REPO_ROOT / "scripts"))
    for bad in (REPO_ROOT / "data" / "governance" / "worklist.json",
                tmp_path / "storage" / "worklist.json"):
        with pytest.raises(SystemExit, match="refusing"):
            judge_proposals.main([
                "worklist", "--corpus", "corpus-a", "--corpus-root", str(tmp_path / "storage"),
                "--lexicon", str(lex_path), "--out", str(bad),
            ])
    assert not (REPO_ROOT / "data" / "governance" / "worklist.json").exists()


def test_offline_guard_is_live_negative_control():
    """The guard used above really refuses a model-client import and a
    connection, so empty refusal lists are evidence, not a blind spot."""
    from tests.proposals import _offline

    finder = _offline._RefuseModelClients()
    sys.meta_path.insert(0, finder)
    try:
        with pytest.raises(ImportError, match="offline guard"):
            __import__("litellm.synthetic_probe")
    finally:
        sys.meta_path.remove(finder)
    with pytest.raises(OSError, match="offline guard"):
        _offline._refuse("socket.connect")(("192.0.2.1", 443))
    assert "litellm.synthetic_probe" in _offline.refused_imports or \
        "litellm" in _offline.refused_imports
    assert "socket.connect" in _offline.refused_connections
