"""RFC linter — status-DAG enforcement across git history (D-22, GOV-07).

These tests spin up a real ``git init`` repo in ``tmp_path`` and walk the
linter against synthetic commit chains. The walker uses subprocess + git
(stdlib + system git only — no GitPython per the dep-rejection rationale).

Skipped if ``git`` is not on ``$PATH``.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from folio_insights.rfc.lint import main

pytestmark = pytest.mark.rfc

# Skip the whole module if git isn't available on the box (CI sandboxes etc).
if shutil.which("git") is None:  # pragma: no cover - env-dependent
    pytest.skip("git CLI not available", allow_module_level=True)


# ─────────────────────── git fixture helpers ───────────────────────
def _make_git_repo(tmp_path: Path) -> Path:
    """Initialise a fresh git repo under tmp_path and return its root.

    Sets user.name/user.email + commit.gpgsign=false locally so the
    container/CI box's global config can't perturb the test (no signing,
    no funky default branch names).
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "RFC Lint Test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "rfc-lint@test.local"], cwd=repo, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=repo, check=True)
    (repo / ".planning" / "rfcs").mkdir(parents=True)
    return repo


def _commit_file(repo: Path, rel_path: str, content: str, message: str) -> str:
    """Write `content` to `repo/rel_path`, stage + commit it; return short sha."""
    target = repo / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", rel_path], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", message, "--no-gpg-sign"],
        cwd=repo, check=True,
    )
    return subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=repo, check=True, capture_output=True, text=True,
    ).stdout.strip()


def _rfc_body(
    rfc: int,
    status: str,
    *,
    title: str = "Sample RFC",
    authors: tuple[str, ...] = ("did:key:z6MkAlice",),
    created: str = "2026-05-30",
    extra_keys: tuple[tuple[str, str], ...] = (),
    body: str = "Body.",
) -> str:
    lines = [
        "---",
        f"rfc: {rfc}",
        f"title: {title}",
        f"status: {status}",
        "authors:",
        *(f"  - {did}" for did in authors),
        f"created: {created}",
        *(f"{k}: {v}" for k, v in extra_keys),
        "---",
        body,
    ]
    return "\n".join(lines) + "\n"


# ─────────────────────── happy-path DAG ───────────────────────
def test_dag_happy_path_draft_to_discussion_to_accepted_exits_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """draft → discussion → accepted, each with `Reason:` trailer — lint clean."""
    repo = _make_git_repo(tmp_path)
    rel = ".planning/rfcs/0001-add-shacl-shape.md"

    _commit_file(repo, rel, _rfc_body(1, "draft"), "feat(rfc): introduce 0001")
    _commit_file(
        repo, rel, _rfc_body(1, "discussion"),
        "chore(rfc): open 0001 for discussion\n\nReason: discussion gate passed",
    )
    _commit_file(
        repo, rel, _rfc_body(1, "accepted"),
        "chore(rfc): accept 0001\n\nReason: consensus reached on 2026-06-01",
    )

    rc = main(repo / ".planning" / "rfcs")
    captured = capsys.readouterr()
    assert rc == 0, f"expected 0; stderr was: {captured.err}"


# ─────────────────────── forbidden DAG edges ───────────────────────
def test_dag_negative_downgrade_accepted_to_draft_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`accepted → draft` is not in ALLOWED_TRANSITIONS[accepted] → lint fails."""
    repo = _make_git_repo(tmp_path)
    rel = ".planning/rfcs/0001-revert-test.md"

    _commit_file(repo, rel, _rfc_body(1, "accepted"), "feat(rfc): 0001 accepted")
    _commit_file(
        repo, rel, _rfc_body(1, "draft"),
        "fix(rfc): downgrade 0001 to draft\n\nReason: needs more work",
    )

    rc = main(repo / ".planning" / "rfcs")
    captured = capsys.readouterr()
    assert rc == 1
    assert "forbidden status transition" in captured.err
    assert "accepted → draft" in captured.err


def test_dag_negative_terminal_rejected_cannot_resurrect(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`rejected` is terminal — even `rejected → accepted` is refused."""
    repo = _make_git_repo(tmp_path)
    rel = ".planning/rfcs/0002-doomed.md"

    _commit_file(repo, rel, _rfc_body(2, "rejected"), "feat(rfc): 0002 rejected at draft")
    _commit_file(
        repo, rel, _rfc_body(2, "accepted"),
        "fix(rfc): change of heart\n\nReason: new evidence found",
    )

    rc = main(repo / ".planning" / "rfcs")
    captured = capsys.readouterr()
    assert rc == 1
    assert "forbidden status transition" in captured.err
    assert "rejected → accepted" in captured.err


def test_dag_negative_skip_stage_draft_to_accepted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`draft → accepted` (skipping `discussion`) — refused per D-22 DAG."""
    repo = _make_git_repo(tmp_path)
    rel = ".planning/rfcs/0003-fast-track.md"

    _commit_file(repo, rel, _rfc_body(3, "draft"), "feat(rfc): 0003 draft")
    _commit_file(
        repo, rel, _rfc_body(3, "accepted"),
        "chore(rfc): fast-track 0003\n\nReason: emergency patch",
    )

    rc = main(repo / ".planning" / "rfcs")
    captured = capsys.readouterr()
    assert rc == 1
    assert "draft → accepted" in captured.err
