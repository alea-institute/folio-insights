"""ci.build builds from a normalized export of HEAD, not the working tree.

COPY carries file mtimes and modes into the image, and BuildKit's
rewrite-timestamp only clamps times newer than SOURCE_DATE_EPOCH. The exported
context stamps every entry with the commit time and fixed modes, so two
checkouts of one commit build the same digest.
"""
from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from ci.build import context_paths, export_build_context, export_image_contexts

COMMIT_EPOCH = 1_700_000_000
DOCKERFILE = """FROM base AS builder
COPY --from=other /bin/tool /bin/
COPY req.lock \\
     extra.lock ./
COPY src/ ./src/
FROM base
COPY --chown=1001:1001 app/ ./app/
"""


def _git(repo: Path, *args: str, **env: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True,
        env={**os.environ, **env},
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "Dockerfile.x").write_text(DOCKERFILE)
    (repo / ".dockerignore").write_text("**/__pycache__\n")
    for rel in ("req.lock", "extra.lock", "src/pkg/mod.py", "app/main.py", "unrelated/secret.txt"):
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rel)
    (repo / "src/pkg/run.sh").write_text("#!/bin/sh\n")
    (repo / "src/pkg/run.sh").chmod(0o775)
    (repo / "src/pkg/mod.py").chmod(0o666)
    _git(repo, "add", "-A")
    date = f"@{COMMIT_EPOCH} +0000"
    _git(repo, "commit", "-q", "-m", "seed", GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    # A stale mtime older than the commit, as on a long-lived checkout.
    os.utime(repo / "src/pkg/mod.py", (1_000_000_000, 1_000_000_000))
    return repo


def test_context_paths_lists_copy_sources_only(repo: Path) -> None:
    assert context_paths(repo, ("Dockerfile.x",)) == [
        ".dockerignore", "Dockerfile.x", "app", "extra.lock", "req.lock", "src",
    ]


def test_export_stamps_commit_time_and_fixed_modes(repo: Path, tmp_path: Path) -> None:
    dest = tmp_path / "ctx"
    dest.mkdir()
    export_build_context(dest, repo, ("Dockerfile.x",))
    files = sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*"))
    assert "unrelated" not in {f.split("/")[0] for f in files}
    assert "src/pkg/mod.py" in files and "app/main.py" in files
    for path in dest.rglob("*"):
        assert int(path.stat().st_mtime) == COMMIT_EPOCH, path
        mode = stat.S_IMODE(path.stat().st_mode)
        if path.is_dir() or path.name == "run.sh":
            assert mode == 0o755, (path, oct(mode))
        else:
            assert mode == 0o644, (path, oct(mode))


def test_export_builds_head_and_warns_on_uncommitted(
    repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    (repo / "src/pkg/mod.py").write_text("uncommitted edit")
    dest = tmp_path / "ctx"
    dest.mkdir()
    export_build_context(dest, repo, ("Dockerfile.x",))
    assert (dest / "src/pkg/mod.py").read_text() == "src/pkg/mod.py"
    assert "src/pkg/mod.py" in capsys.readouterr().err



def test_each_image_gets_a_fresh_uniquely_named_context(repo: Path, tmp_path: Path) -> None:
    """BuildKit reuses a cached context transfer for any later context with the same
    basename, and that incremental transfer keeps stale directory mtimes. Every
    image, on every run, must therefore build from a basename never used before."""
    (repo / "Dockerfile.y").write_text("FROM base\nCOPY src/ ./src/\n")
    _git(repo, "add", "-A")
    date = f"@{COMMIT_EPOCH} +0000"
    _git(repo, "commit", "-q", "-m", "y", GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    dockerfiles = ("Dockerfile.x", "Dockerfile.y")
    runs = []
    for run in ("run1", "run2"):
        (tmp_path / run).mkdir()
        runs.append(export_image_contexts(tmp_path / run, repo, dockerfiles))
    contexts = [ctx for run in runs for ctx in run.values()]
    assert all(set(run) == set(dockerfiles) for run in runs)
    assert len({ctx.name for ctx in contexts}) == len(contexts), contexts
    for ctx in contexts:
        assert (ctx / "src/pkg/mod.py").read_text() == "src/pkg/mod.py"
        assert int((ctx / "src").stat().st_mtime) == COMMIT_EPOCH


def test_failed_extraction_kills_and_reaps_git(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review nit: if extraction raises, the git child is killed and reaped,
    never left blocked on a full pipe."""
    import ci.build as build

    spawned: list[subprocess.Popen] = []
    real_popen = subprocess.Popen

    def recording_popen(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        proc = real_popen(*args, **kwargs)
        spawned.append(proc)
        return proc

    def broken_open(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("synthetic extraction failure")

    monkeypatch.setattr(build.subprocess, "Popen", recording_popen)
    monkeypatch.setattr(build.tarfile, "open", broken_open)
    dest = tmp_path / "ctx"
    dest.mkdir()
    with pytest.raises(RuntimeError, match="synthetic"):
        export_build_context(dest, repo, ("Dockerfile.x",))
    assert spawned and all(p.returncode is not None for p in spawned)
    assert all(p.stdout is None or p.stdout.closed for p in spawned)
