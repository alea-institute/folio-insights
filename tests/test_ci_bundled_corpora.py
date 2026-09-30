"""The Dagger build refuses to publish when a bundled corpus holds untracked files.

Images go to the public ttl.sh registry, and the build context is the host
directory, so anything dropped into output/default or output/demo would ship.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ci.build import assert_bundled_corpora_tracked


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    demo = tmp_path / "output" / "demo"
    demo.mkdir(parents=True)
    (demo / "extraction.json").write_text("{}")
    _git(tmp_path, "add", "output/demo/extraction.json")
    _git(tmp_path, "commit", "-q", "-m", "seed")
    return tmp_path


def test_tracked_only_corpora_pass(repo: Path) -> None:
    assert_bundled_corpora_tracked(repo)


def test_untracked_file_in_bundled_corpus_blocks_publish(repo: Path) -> None:
    (repo / "output" / "demo" / "sources").mkdir()
    (repo / "output" / "demo" / "sources" / "book.md").write_text("chapter text")
    with pytest.raises(SystemExit, match="output/demo/sources/book.md"):
        assert_bundled_corpora_tracked(repo)


def test_ignored_file_in_bundled_corpus_blocks_publish(repo: Path) -> None:
    (repo / ".gitignore").write_text("*.md\n")
    (repo / "output" / "demo" / "notes.md").write_text("ignored but still on disk")
    with pytest.raises(SystemExit, match="output/demo/notes.md"):
        assert_bundled_corpora_tracked(repo)


def test_sqlite_sidecars_are_allowed(repo: Path) -> None:
    """Sidecars are excluded from the build context, so they cannot ship."""
    (repo / "output" / "demo" / "review.db-wal").write_text("")
    (repo / "output" / "demo" / "review.db-shm").write_text("")
    assert_bundled_corpora_tracked(repo)
