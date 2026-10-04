"""Phase 13 U3: CLI commands share persistent corpus state across processes,
and ``retract --apply`` replays a saved preview safely.

Every CLI call runs in its own OS process (``python -c 'from
folio_insights.cli import cli; cli()'``) against a disposable corpus root.
Signing identities are generated per test (``generate_keypair`` into
``tmp_path``); shards are synthetic. No operator key or credential is read.

Scenarios (plan U3):
  * corpus init and role operations in separate processes;
  * a persisted non-empty cascade survives a restart;
  * preview + shard edit (dependent or unrelated) refuses; preview + role
    revocation refuses;
  * an unchanged preview commits once; re-applying returns the same event
    and appends nothing; two racing applies commit once;
  * a missing target refuses at preview and at apply;
  * historical shards are never deleted by a retraction.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from folio_insights.identity.keys import generate_keypair
from folio_insights.storage import CorpusStorageContext

from tests.storage.conftest import shard

pytestmark = pytest.mark.governance

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS = "corpus-u3"
_CLI = "from folio_insights.cli import cli; cli()"


def _env(root: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["FOLIO_INSIGHTS_CORPUS_ROOT"] = str(root)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(REPO_ROOT / "src"), str(REPO_ROOT), env.get("PYTHONPATH", "")]
    )
    return env


def run_cli(root: Path, *args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    """One CLI invocation in a fresh OS process."""
    return subprocess.run(
        [sys.executable, "-c", _CLI, *args],
        cwd=root.parent,
        env=_env(root),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def ok(result: subprocess.CompletedProcess[str]) -> subprocess.CompletedProcess[str]:
    assert result.returncode == 0, (
        f"exit {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return result


def _in_ctx(root: Path, fn: Any) -> Any:
    """Run ``fn(ctx)`` against a context opened (and closed) in THIS process."""

    async def _go() -> Any:
        ctx = await CorpusStorageContext.open(root, CORPUS)
        try:
            return await fn(ctx)
        finally:
            await ctx.close()

    return asyncio.run(_go())


async def _snapshot(ctx: CorpusStorageContext) -> dict[str, Any]:
    events = [e async for e in ctx.governance.iter_events(CORPUS)]
    shards = {s.shard_iri: s.model_dump(mode="json") async for s in ctx.shards.iter_shards()}
    return {
        "head": (await ctx.status()).journal_head,
        "events": [(e.position, e.action) for e in events],
        "retractions": [e for e in events if e.action == "retract"],
        "shards": shards,
    }


@dataclass
class Corpus:
    root: Path
    admin_key: Path
    admin_did: str
    member_did: str
    target: str
    dependents: list[str]
    unrelated: str


@pytest.fixture
def corpus(tmp_path: Path) -> Corpus:
    root = tmp_path / "corpora"
    admin_key = tmp_path / "admin.jwk"
    admin_did = generate_keypair(admin_key)
    member_did = generate_keypair(tmp_path / "member.jwk")

    ok(run_cli(root, "corpus", "init", CORPUS, "--admin-did", admin_did, "--key-path", str(admin_key)))
    ok(
        run_cli(
            root, "governance", "assert-role", member_did, "--role", "reviewer",
            "--corpus", CORPUS, "--key-path", str(admin_key),
        )
    )

    target = shard(1)
    aporetic = shard(2, depends_on_shards=[target.shard_iri])
    review = shard(3, depends_on_precedents=[target.shard_iri], epistemic_status="contested")
    unrelated = shard(4)

    async def _seed(ctx: CorpusStorageContext) -> None:
        for s in (target, aporetic, review, unrelated):
            await ctx.shards.put(s.shard_iri, s, op_id=f"seed:{s.shard_iri}")

    _in_ctx(root, _seed)
    return Corpus(
        root=root,
        admin_key=admin_key,
        admin_did=admin_did,
        member_did=member_did,
        target=target.shard_iri,
        dependents=sorted([aporetic.shard_iri, review.shard_iri]),
        unrelated=unrelated.shard_iri,
    )


def _preview(c: Corpus, out: Path, target: str | None = None) -> dict[str, Any]:
    ok(
        run_cli(
            c.root, "governance", "retract", target or c.target, "--preview",
            "--output", str(out), "--corpus", CORPUS, "--key-path", str(c.admin_key),
        )
    )
    return json.loads(out.read_text(encoding="utf-8"))


def _apply(c: Corpus, preview_path: Path, target: str | None = None) -> subprocess.CompletedProcess[str]:
    return run_cli(
        c.root, "governance", "retract", target or c.target, "--apply", str(preview_path),
        "--corpus", CORPUS, "--key-path", str(c.admin_key),
    )


# ── corpus init + roles across processes ───────────────────────────────────


def test_init_and_role_operations_persist_across_processes(tmp_path: Path) -> None:
    root = tmp_path / "corpora"
    admin_key = tmp_path / "admin.jwk"
    admin_did = generate_keypair(admin_key)
    member_did = generate_keypair(tmp_path / "member.jwk")
    common = ("--corpus", CORPUS, "--key-path", str(admin_key))

    genesis = json.loads(
        ok(run_cli(root, "corpus", "init", CORPUS, "--admin-did", admin_did, "--key-path", str(admin_key))).stdout
    )
    assert genesis["position"] == 0

    asserted = json.loads(
        ok(run_cli(root, "governance", "assert-role", member_did, "--role", "arbiter", *common)).stdout
    )
    assert asserted["position"] == 1

    # A later process sees the earlier processes' events.
    shown = ok(run_cli(root, "governance", "show", *common)).stdout
    assert "role_assertion" in shown

    revoked = json.loads(
        ok(run_cli(root, "governance", "revoke-role", member_did, "--revoked-role", "arbiter", *common)).stdout
    )
    assert revoked["position"] == 2

    # A second init in yet another process is denied by the persisted genesis.
    again = run_cli(root, "corpus", "init", CORPUS, "--admin-did", admin_did, "--key-path", str(admin_key))
    assert again.returncode != 0
    assert "corpus_already_initialized" in again.stderr

    # The last-admin lockout reads the persisted roles too.
    lockout = run_cli(root, "governance", "revoke-role", admin_did, "--revoked-role", "corpus_admin", *common)
    assert lockout.returncode != 0
    assert "0 active corpus_admins" in lockout.stderr

    async def _roles(ctx: CorpusStorageContext) -> Any:
        from datetime import UTC, datetime

        roles = await ctx.governance.query_active_roles_at(CORPUS, datetime(2100, 1, 1, tzinfo=UTC))
        events = [e.action async for e in ctx.governance.iter_events(CORPUS)]
        return roles, events

    roles, events = _in_ctx(root, _roles)
    assert roles == {admin_did: {"corpus_admin"}}
    assert events == ["role_assertion", "role_assertion", "role_revocation"]


# ── cascade survives restart ───────────────────────────────────────────────


def test_nonempty_cascade_survives_restart(corpus: Corpus, tmp_path: Path) -> None:
    first = _preview(corpus, tmp_path / "p1.json")
    second = _preview(corpus, tmp_path / "p2.json")  # another fresh process

    for preview in (first, second):
        assert preview["aporetic"] == [shard(2).shard_iri]
        listed = sorted(preview["auto_rederive"] + preview["aporetic"] + preview["review_needed"])
        assert listed == corpus.dependents
        assert corpus.unrelated not in listed
        assert preview["review_needed"] == [shard(3).shard_iri]
        assert preview["op_id"].startswith("retract:")
        assert isinstance(preview["state_position"], int)

    # Same state, same cascade; each preview binds its own op_id into the hash.
    assert first["state_position"] == second["state_position"]
    assert first["op_id"] != second["op_id"]
    assert first["underlying_state_hash"] != second["underlying_state_hash"]


# ── stale previews refuse ──────────────────────────────────────────────────


def _assert_stale(corpus: Corpus, preview_path: Path) -> None:
    before = _in_ctx(corpus.root, _snapshot)
    result = _apply(corpus, preview_path)
    assert result.returncode == 2, result.stderr
    assert "PreviewStale" in result.stderr and "--preview" in result.stderr
    after = _in_ctx(corpus.root, _snapshot)
    assert after == before
    assert after["retractions"] == []


def test_preview_then_dependent_edit_refuses(corpus: Corpus, tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    _preview(corpus, path)

    async def _edit(ctx: CorpusStorageContext) -> None:
        dep = await ctx.shards.get(corpus.dependents[0])
        assert dep is not None
        await ctx.shards.put(
            dep.shard_iri, dep.model_copy(update={"sense": "edited after preview"}), op_id="edit-dep"
        )

    _in_ctx(corpus.root, _edit)
    _assert_stale(corpus, path)


def test_preview_then_unrelated_shard_edit_refuses(corpus: Corpus, tmp_path: Path) -> None:
    """Any shard change since the preview refuses, not only cascade members:
    the guarded append compares the whole corpus journal head."""
    path = tmp_path / "p.json"
    _preview(corpus, path)

    async def _edit(ctx: CorpusStorageContext) -> None:
        other = await ctx.shards.get(corpus.unrelated)
        assert other is not None
        await ctx.shards.put(
            other.shard_iri, other.model_copy(update={"sense": "unrelated edit"}), op_id="edit-unrelated"
        )

    _in_ctx(corpus.root, _edit)
    _assert_stale(corpus, path)


def test_preview_then_role_revocation_refuses(corpus: Corpus, tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    _preview(corpus, path)
    ok(
        run_cli(
            corpus.root, "governance", "revoke-role", corpus.member_did, "--revoked-role", "reviewer",
            "--corpus", CORPUS, "--key-path", str(corpus.admin_key),
        )
    )
    _assert_stale(corpus, path)


# ── commit once, replay returns the same event ─────────────────────────────


def test_unchanged_preview_commits_once_and_replay_returns_same_event(
    corpus: Corpus, tmp_path: Path
) -> None:
    path = tmp_path / "p.json"
    preview = _preview(corpus, path)
    before = _in_ctx(corpus.root, _snapshot)

    first = json.loads(ok(_apply(corpus, path)).stdout)
    assert first["action"] == "retract"
    assert first["shard_iri"] == corpus.target
    assert first["signature"]["did"] == corpus.admin_did

    replay = json.loads(ok(_apply(corpus, path)).stdout)
    assert replay == first

    after = _in_ctx(corpus.root, _snapshot)
    assert len(after["retractions"]) == 1
    assert after["head"] == before["head"] + 1
    assert after["head"] == preview["state_position"] + 1
    # Append-only: every shard (target included) is still there, unchanged.
    assert after["shards"] == before["shards"]

    async def _op(ctx: CorpusStorageContext) -> Any:
        return await ctx.committed_governance_op(preview["op_id"])

    committed = _in_ctx(corpus.root, _op)
    assert committed is not None and committed.position == first["position"]


def test_racing_applies_commit_once(corpus: Corpus, tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    _preview(corpus, path)
    args = [
        sys.executable, "-c", _CLI, "governance", "retract", corpus.target, "--apply", str(path),
        "--corpus", CORPUS, "--key-path", str(corpus.admin_key),
    ]
    procs = [
        subprocess.Popen(
            args, cwd=corpus.root.parent, env=_env(corpus.root),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        for _ in range(3)
    ]
    outputs = [p.communicate(timeout=90) for p in procs]
    for proc, (out, err) in zip(procs, outputs, strict=True):
        assert proc.returncode == 0, f"stdout:\n{out}\nstderr:\n{err}"
    events = [json.loads(out) for out, _ in outputs]
    assert all(e == events[0] for e in events)

    after = _in_ctx(corpus.root, _snapshot)
    assert len(after["retractions"]) == 1


# ── missing target refuses ─────────────────────────────────────────────────


def test_missing_target_refuses_at_preview(corpus: Corpus, tmp_path: Path) -> None:
    before = _in_ctx(corpus.root, _snapshot)
    missing = shard(99).shard_iri
    result = run_cli(
        corpus.root, "governance", "retract", missing, "--preview",
        "--output", str(tmp_path / "p.json"), "--corpus", CORPUS, "--key-path", str(corpus.admin_key),
    )
    assert result.returncode == 1
    assert "no such shard" in result.stderr
    assert not (tmp_path / "p.json").exists()
    assert _in_ctx(corpus.root, _snapshot) == before


def test_missing_target_refuses_at_apply(corpus: Corpus, tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    preview = _preview(corpus, path)
    missing = shard(99).shard_iri
    preview["retracted_shard_iri"] = missing
    forged = tmp_path / "forged.json"
    forged.write_text(json.dumps(preview), encoding="utf-8")
    before = _in_ctx(corpus.root, _snapshot)

    result = _apply(corpus, forged, target=missing)
    assert result.returncode == 1
    assert "no such shard" in result.stderr
    assert _in_ctx(corpus.root, _snapshot) == before


def test_apply_refuses_preview_for_other_target(corpus: Corpus, tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    _preview(corpus, path)
    result = _apply(corpus, path, target=corpus.unrelated)
    assert result.returncode == 1
    assert "preview file is for" in result.stderr


def test_unauthorized_apply_is_denied_first(corpus: Corpus, tmp_path: Path) -> None:
    path = tmp_path / "p.json"
    _preview(corpus, path)
    outsider_key = tmp_path / "outsider.jwk"
    generate_keypair(outsider_key)
    before = _in_ctx(corpus.root, _snapshot)
    result = run_cli(
        corpus.root, "governance", "retract", corpus.target, "--apply", str(path),
        "--corpus", CORPUS, "--key-path", str(outsider_key),
    )
    assert result.returncode == 1
    assert "unauthorized" in result.stderr
    assert _in_ctx(corpus.root, _snapshot) == before


def test_race_loser_reports_winner_instead_of_stale(
    corpus: Corpus, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A concurrent apply that missed the op_id lookup and then saw the
    winner's commit as a state change reports the committed event (exit 0),
    not PreviewStale. Deterministic: the first lookup is forced to miss."""
    from click.testing import CliRunner

    from folio_insights.cli import cli

    path = tmp_path / "p.json"
    _preview(corpus, path)
    winner = json.loads(ok(_apply(corpus, path)).stdout)

    real = CorpusStorageContext.committed_governance_op
    calls = {"n": 0}

    async def _miss_first(self: CorpusStorageContext, op_id: str) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return await real(self, op_id)

    monkeypatch.setattr(CorpusStorageContext, "committed_governance_op", _miss_first)
    monkeypatch.setenv("FOLIO_INSIGHTS_CORPUS_ROOT", str(corpus.root))
    result = CliRunner().invoke(
        cli,
        [
            "governance", "retract", corpus.target, "--apply", str(path),
            "--corpus", CORPUS, "--key-path", str(corpus.admin_key),
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == winner
    assert calls["n"] == 2
    assert len(_in_ctx(corpus.root, _snapshot)["retractions"]) == 1


async def test_builder_uses_typed_dependents_seam() -> None:
    """KTD4: the cascade comes from ``ShardStore.dependents_of``. A store
    with no private ``_d`` dictionary still yields the full cascade."""
    from folio_insights.governance.log import InMemoryGovernanceLog
    from folio_insights.governance.retract import build_cascade_preview
    from folio_insights.revision.store import InMemoryShardStore

    class OpaqueStore:
        def __init__(self) -> None:
            self.__inner = InMemoryShardStore(CORPUS)

        @property
        def corpus(self) -> str:
            return CORPUS

        async def get(self, iri: str) -> Any:
            return await self.__inner.get(iri)

        async def put(self, iri: str, s: Any) -> None:
            await self.__inner.put(iri, s)

        def iter_shards(self) -> Any:
            return self.__inner.iter_shards()

        async def dependents_of(self, iri: str) -> Any:
            return await self.__inner.dependents_of(iri)

    store = OpaqueStore()
    assert not hasattr(store, "_d")
    target = shard(1)
    dep = shard(2, depends_on_axioms=[target.shard_iri])
    for s in (target, dep, shard(3)):
        await store.put(s.shard_iri, s)
    preview = await build_cascade_preview(
        target.shard_iri, CORPUS, store=store, log=InMemoryGovernanceLog()  # type: ignore[arg-type]
    )
    assert preview.aporetic == [dep.shard_iri]
    assert preview.state_position is None and preview.op_id.startswith("retract:")  # type: ignore[union-attr]

    source = (REPO_ROOT / "src/folio_insights/governance/retract.py").read_text(encoding="utf-8")
    assert "_d" not in {tok.strip(".,()") for tok in source.replace("\"", " ").split()}
    assert "dependents_of" in source


# ── U3 review findings (regressions) ───────────────────────────────────────


def test_forged_buckets_in_saved_preview_refuse(corpus: Corpus, tmp_path: Path) -> None:
    """P1: an edited preview whose buckets name a cascade that never existed
    must not commit a hash of that forged cascade."""
    path = tmp_path / "p.json"
    honest = _preview(corpus, path)
    forged = dict(honest, aporetic=[], review_needed=[], auto_rederive=["urn:fabricated:x"])
    forged_path = tmp_path / "forged.json"
    forged_path.write_text(json.dumps(forged), encoding="utf-8")
    _assert_stale(corpus, forged_path)


def test_edited_state_position_does_not_bypass_guard(corpus: Corpus, tmp_path: Path) -> None:
    """P2: state_position is bound into the state hash, so bumping it in the
    file after a corpus change refuses instead of committing."""
    path = tmp_path / "p.json"
    preview = _preview(corpus, path)

    async def _edit(ctx: CorpusStorageContext) -> None:
        other = await ctx.shards.get(corpus.unrelated)
        assert other is not None
        await ctx.shards.put(
            other.shard_iri, other.model_copy(update={"sense": "unrelated edit"}), op_id="edit-u"
        )

    _in_ctx(corpus.root, _edit)
    preview["state_position"] = _in_ctx(corpus.root, _snapshot)["head"]
    bumped = tmp_path / "bumped.json"
    bumped.write_text(json.dumps(preview), encoding="utf-8")
    _assert_stale(corpus, bumped)


def test_revocation_after_cli_authorize_refuses_in_transaction(
    corpus: Corpus, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P2: a revocation committed between the CLI's authorize() and the
    append still refuses: storage re-authorizes against committed history."""
    from click.testing import CliRunner

    import folio_insights.governance.cli.retract as retract_cli
    from folio_insights.cli import cli

    b_key = tmp_path / "b.jwk"
    b_did = generate_keypair(b_key)
    common = ("--corpus", CORPUS, "--key-path", str(corpus.admin_key))
    ok(run_cli(corpus.root, "governance", "assert-role", b_did, "--role", "corpus_admin", *common))

    real = retract_cli.authorize

    async def _racing(did: str, action: str, corp: str, **kw: Any) -> Any:
        decision = await real(did, action, corp, **kw)
        ok(run_cli(corpus.root, "governance", "revoke-role", b_did, "--revoked-role", "corpus_admin", *common))
        return decision

    monkeypatch.setattr(retract_cli, "authorize", _racing)
    monkeypatch.setenv("FOLIO_INSIGHTS_CORPUS_ROOT", str(corpus.root))
    result = CliRunner().invoke(
        cli,
        ["governance", "retract", corpus.target, "--yes", "--corpus", CORPUS, "--key-path", str(b_key)],
    )
    assert result.exit_code == 1, result.output
    assert "NotAuthorized" in result.output
    assert _in_ctx(corpus.root, _snapshot)["retractions"] == []


def test_op_id_of_shard_write_refuses_cleanly(corpus: Corpus, tmp_path: Path) -> None:
    """Nit: an op_id naming a committed shard write exits 1 without a traceback."""
    path = tmp_path / "p.json"
    preview = _preview(corpus, path)
    preview["op_id"] = f"seed:{corpus.unrelated}"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(preview), encoding="utf-8")
    before = _in_ctx(corpus.root, _snapshot)
    result = _apply(corpus, bad)
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "shard write" in result.stderr
    assert _in_ctx(corpus.root, _snapshot) == before


def test_retry_by_other_signer_names_original_committer(corpus: Corpus, tmp_path: Path) -> None:
    """Nit: re-applying a preview someone else committed returns their event
    and says who committed it."""
    path = tmp_path / "p.json"
    _preview(corpus, path)
    first = json.loads(ok(_apply(corpus, path)).stdout)
    member_key = tmp_path / "member.jwk"
    result = ok(
        run_cli(
            corpus.root, "governance", "retract", corpus.target, "--apply", str(path),
            "--corpus", CORPUS, "--key-path", str(member_key),
        )
    )
    assert json.loads(result.stdout) == first
    assert f"already committed by {corpus.admin_did}" in result.stderr
    assert len(_in_ctx(corpus.root, _snapshot)["retractions"]) == 1
