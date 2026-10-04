"""Where generated proposal material may be written (governance plan R5).

Worklists, approval queues and approved-only backlogs are generated from the
proposal ledger. Their labels come from pipeline output, so they must never
be committed to a repository. Every writer checks its destination with
``check_generated_destination`` first. It refuses a path that is:

* inside this repository (the checkout the code was loaded from);
* inside any other git work tree or git directory (another worktree or clone
  of this repository, or any other repository), including a path that does
  not exist yet, by checking its nearest existing ancestor;
* inside the corpus storage root.

``write_json_atomic`` then writes the file through a temporary sibling and an
atomic rename, so a reader never sees a partial file.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

# src/folio_insights/proposals/destinations.py -> the repository root.
REPO_ROOT = Path(__file__).resolve().parents[3]


class DestinationRefused(SystemExit):
    """The destination would place generated proposal material where it could
    be committed, or inside the storage root. Raised as ``SystemExit`` so a
    CLI exits with the message and a non-zero status."""


def _inside(path: Path, other: Path) -> bool:
    path, other = path.resolve(), other.resolve()
    return path == other or other in path.parents


def nearest_existing_dir(path: Path) -> Path:
    probe = path
    while not probe.exists():
        if probe.parent == probe:
            break
        probe = probe.parent
    return probe if probe.is_dir() else probe.parent


def git_claims(directory: Path) -> bool:
    """True if ``directory`` is inside any git work tree or git directory.

    Runs git with inherited ``GIT_*`` variables dropped and system/global
    config ignored. A git that cannot run fails closed (treated as a claim).
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    try:
        result = subprocess.run(
            ["git", "-C", str(directory), "rev-parse", "--is-inside-work-tree",
             "--is-inside-git-dir"],
            env=env, capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return True
    if result.returncode != 0:
        # "not a git repository" is the only acceptable failure.
        return "not a git repository" not in result.stderr
    return "true" in result.stdout.split()


def check_generated_destination(
    out: Path, corpus_root: Path, *, what: str, repo_root: Path = REPO_ROOT
) -> Path:
    """Refuse an unsafe destination for generated proposal material (see the
    module docstring). Returns the resolved path, which is what gets written."""
    resolved = Path(out).expanduser().resolve()
    if _inside(resolved, repo_root):
        raise DestinationRefused(
            f"refusing to write a {what} inside the repository ({repo_root}); "
            "generated review material must never be committed"
        )
    if _inside(resolved, Path(corpus_root).expanduser()):
        raise DestinationRefused(f"refusing to write a {what} inside the corpus storage root")
    if git_claims(nearest_existing_dir(resolved)):
        raise DestinationRefused(
            f"refusing to write a {what} inside a git work tree or git directory; "
            "generated review material must never be committed"
        )
    return resolved


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def canonical_json(data: Any) -> str:
    """Sorted keys, two-space indent, trailing newline: identical input gives
    identical bytes."""
    return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def write_json_atomic(path: Path, data: Any) -> None:
    write_text_atomic(path, canonical_json(data))


__all__ = [
    "REPO_ROOT",
    "DestinationRefused",
    "canonical_json",
    "check_generated_destination",
    "git_claims",
    "nearest_existing_dir",
    "write_json_atomic",
    "write_text_atomic",
]
