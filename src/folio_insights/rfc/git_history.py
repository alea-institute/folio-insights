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

from folio_insights.rfc.frontmatter import _parse_frontmatter_raw


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

        # History walk is intentionally tolerant of `extra="forbid"`
        # schema violations: a historical commit may carry the optional
        # `status_change_reason:` key (which Pydantic refuses on the
        # current schema). The body-only-edit refusal heuristic NEEDS
        # to see that key. So we parse the raw dict (tolerates unknown
        # keys) and pull `status` directly from it; we only skip
        # commits where the frontmatter block is malformed.
        try:
            raw = _parse_frontmatter_raw(content)
        except ValueError:
            continue  # malformed / missing frontmatter at this commit — skip
        status_value = raw.get("status")
        if not isinstance(status_value, str) or not status_value:
            continue  # no status field at this commit — skip

        commits.append({
            "sha": sha,
            "subject": subject.strip(),
            "body": body.rstrip("\n"),
            "status": status_value,
            "frontmatter_dict": raw,
        })
    return commits
