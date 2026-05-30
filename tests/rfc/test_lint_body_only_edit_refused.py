"""RFC linter — body-only-edit-refusal heuristic across git history (D-22).

D-22 cheap heuristic: a commit that changes ``status:`` MUST also carry
EITHER (a) a ``Reason:`` trailer in the commit body OR (b) a
``status_change_reason:`` line in the frontmatter at that commit.
Otherwise the linter refuses the commit.

These tests spin up a real ``git init`` repo and exercise both
acceptance paths plus the negative case.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from folio_insights.rfc.lint import main

pytestmark = pytest.mark.rfc

if shutil.which("git") is None:  # pragma: no cover - env-dependent
    pytest.skip("git CLI not available", allow_module_level=True)


# Helpers duplicated rather than imported from the sibling test module to
# keep each test file independently runnable (matches the rest of the
# tests/rfc/ suite). Identical contracts; not collected as tests.
def _make_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "RFC Lint Test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "rfc-lint@test.local"], cwd=repo, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=repo, check=True)
    (repo / ".planning" / "rfcs").mkdir(parents=True)
    return repo


def _commit(repo: Path, rel: str, content: str, message: str) -> None:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", rel], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", message, "--no-gpg-sign"],
        cwd=repo, check=True,
    )


def _rfc(
    rfc: int,
    status: str,
    *,
    extra_keys: tuple[tuple[str, str], ...] = (),
    body: str = "Body.",
) -> str:
    lines = [
        "---",
        f"rfc: {rfc}",
        "title: Sample RFC",
        f"status: {status}",
        "authors:",
        "  - did:key:z6MkAlice",
        "created: 2026-05-30",
        *(f"{k}: {v}" for k, v in extra_keys),
        "---",
        body,
    ]
    return "\n".join(lines) + "\n"


# ─────────────────────── negative: no rationale → fail ───────────────────────
def test_status_change_with_no_rationale_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """draft → discussion, no `Reason:` trailer, no `status_change_reason:` → fail."""
    repo = _make_git_repo(tmp_path)
    rel = ".planning/rfcs/0001-no-rationale.md"
    _commit(repo, rel, _rfc(1, "draft"), "feat(rfc): create 0001")
    # status edited but message has no `Reason:` and frontmatter has no `status_change_reason:`
    _commit(repo, rel, _rfc(1, "discussion"), "chore(rfc): bump status")

    rc = main(repo / ".planning" / "rfcs")
    captured = capsys.readouterr()
    assert rc == 1
    # Error mentions both acceptance paths so operators know how to fix.
    assert "Reason:" in captured.err
    assert "status_change_reason" in captured.err


# ─────────────────────── positive: Reason: trailer → pass ───────────────────────
def test_status_change_with_reason_trailer_is_accepted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """draft → discussion + `Reason:` trailer → exit 0."""
    repo = _make_git_repo(tmp_path)
    rel = ".planning/rfcs/0002-reason-trailer.md"
    _commit(repo, rel, _rfc(2, "draft"), "feat(rfc): create 0002")
    _commit(
        repo, rel, _rfc(2, "discussion"),
        "chore(rfc): open 0002 for discussion\n\nReason: discussion period opened",
    )

    rc = main(repo / ".planning" / "rfcs")
    captured = capsys.readouterr()
    assert rc == 0, f"expected 0; stderr was: {captured.err}"


# ───────────── positive: status_change_reason frontmatter line → pass ─────────────
def test_status_change_with_frontmatter_reason_is_accepted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """draft → discussion + `status_change_reason:` frontmatter line → exit 0.

    The Pydantic `RFCFrontmatter` model uses `extra="forbid"`, so
    `status_change_reason:` is NOT on the validated schema; the linter's
    body-only-edit check reads the raw dict via `_parse_frontmatter_raw`
    BEFORE validation, so unknown keys remain visible.
    """
    repo = _make_git_repo(tmp_path)
    rel = ".planning/rfcs/0003-frontmatter-reason.md"
    _commit(repo, rel, _rfc(3, "draft"), "feat(rfc): create 0003")
    _commit(
        repo, rel,
        _rfc(3, "discussion", extra_keys=(("status_change_reason", "discussion period opened"),)),
        "chore(rfc): bump status",  # NB: no `Reason:` trailer here
    )

    # Tricky: the linter's *Pydantic* validation of the CURRENT file (HEAD)
    # would reject `status_change_reason:` due to extra="forbid", so the
    # final commit needs to either (a) keep the key off HEAD or (b) the
    # linter must treat history reads via the raw dict only.
    # Per the plan, the historical commit dict is consulted via the raw
    # parser (extra-key tolerant). The HEAD validation runs the Pydantic
    # model. To make this scenario realistic, the HEAD commit drops the
    # key — leaving the rationale in history where the heuristic checks.
    _commit(
        repo, rel, _rfc(3, "discussion"),
        "chore(rfc): drop status_change_reason (rationale was preserved in prior commit)",
    )

    rc = main(repo / ".planning" / "rfcs")
    captured = capsys.readouterr()
    assert rc == 0, f"expected 0; stderr was: {captured.err}"


# ─────────────────────── two changes — only first lacks rationale ───────────────────────
def test_only_unauthorized_change_is_flagged_not_compliant_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """If commit N changes status without rationale but N+1 has Reason:,
    only N is reported — and the linter still exits non-zero."""
    repo = _make_git_repo(tmp_path)
    rel = ".planning/rfcs/0004-mixed.md"
    _commit(repo, rel, _rfc(4, "draft"), "feat(rfc): 0004 draft")
    # First transition has NO rationale — should be flagged.
    _commit(repo, rel, _rfc(4, "discussion"), "chore(rfc): bump status")
    # Second transition has Reason: trailer — should NOT be flagged.
    _commit(
        repo, rel, _rfc(4, "accepted"),
        "chore(rfc): accept 0004\n\nReason: consensus 2026-07",
    )

    rc = main(repo / ".planning" / "rfcs")
    captured = capsys.readouterr()
    assert rc == 1
    # The flagged commit is the draft→discussion one (no rationale).
    assert "draft → discussion" in captured.err
    # The accepted transition was authorized — it shouldn't be flagged for missing rationale.
    err = captured.err
    assert err.count("status changed") == 1, (
        f"expected exactly 1 rationale violation, got: {err}"
    )
