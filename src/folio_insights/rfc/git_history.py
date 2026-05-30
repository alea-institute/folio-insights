"""Git history walker for the RFC linter (D-22, stdlib subprocess only).

We deliberately do NOT use GitPython:
  * adds a heavy dep for a single ``git log`` invocation;
  * the `--follow --reverse` semantics we need are 100% the same as the
    CLI, so the subprocess interface is the simplest and most-stable.

The walker is tolerant: commits where the file did not yet exist, or where
frontmatter cannot be parsed, are silently skipped — only commits that
produce a *valid* (sha, status, frontmatter_dict) tuple are returned.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from folio_insights.rfc.frontmatter import _parse_frontmatter_raw, parse_frontmatter


def walk_history(
    rfc_path: Path,
    *,
    repo_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Return commits touching `rfc_path` oldest-first, with parsed status.

    Each entry is::

        {
            "sha": "<full-sha>",
            "subject": "<commit subject line>",
            "body": "<commit body, may be multi-line>",
            "status": "<draft|discussion|accepted|rejected|implemented>",
            "frontmatter_dict": <raw dict including unknown keys like
                                 status_change_reason — used by the
                                 body-only-edit-refusal heuristic>,
        }

    Commits where the file did not exist, or where the frontmatter could
    not be parsed, are skipped.

    ``repo_root`` (optional) sets the subprocess CWD; pass it when calling
    against a tmp_path test repo (otherwise the call inherits the
    interpreter CWD).
    """
    # Compute a path that's relative to the repo root if possible — git
    # log --follow is happiest with repo-relative paths.
    try:
        if repo_root is not None:
            rel = rfc_path.relative_to(repo_root)
            path_arg = str(rel)
        else:
            path_arg = str(rfc_path)
    except ValueError:
        path_arg = str(rfc_path)

    cwd = str(repo_root) if repo_root is not None else None

    try:
        result = subprocess.run(
            [
                "git", "log", "--follow", "--reverse",
                "--format=%H%n%s%n--BODY--%n%b%n--END--",
                "--", path_arg,
            ],
            check=True,
            capture_output=True,
            text=True,
            cwd=cwd,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        # No git in $PATH, or the file lives outside any git repo.
        return []

    commits: list[dict[str, Any]] = []
    for entry in result.stdout.split("--END--\n"):
        if not entry.strip():
            continue
        try:
            sha_line, rest = entry.split("\n", 1)
        except ValueError:
            continue
        subject, _, body = rest.partition("--BODY--\n")
        sha = sha_line.strip()
        if not sha:
            continue

        # Re-read the file AT this commit.
        try:
            content = subprocess.run(
                ["git", "show", f"{sha}:{path_arg}"],
                check=True,
                capture_output=True,
                text=True,
                cwd=cwd,
            ).stdout
        except subprocess.CalledProcessError:
            continue  # file didn't exist at this commit

        try:
            raw = _parse_frontmatter_raw(content)
            fm = parse_frontmatter(content)
        except (ValueError, ValidationError):
            continue  # malformed frontmatter at this commit — skip

        commits.append({
            "sha": sha,
            "subject": subject.strip(),
            "body": body.rstrip("\n"),
            "status": fm.status,
            "frontmatter_dict": raw,
        })
    return commits
