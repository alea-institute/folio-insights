"""RFC lifecycle linter — CI-runnable gate per D-22 (GOV-07).

Usage::

    python -m folio_insights.rfc.lint .planning/rfcs/

Exit code 0 = clean; exit code 1 = at least one RFC lifecycle violation.
Errors are printed to stderr in GitHub-Actions-friendly ``::error::`` form
so the same invocation works both locally and in CI without extra wiring.

Checks per RFC file:
  1. Filename matches ``NNNN-kebab-title.md`` (4-digit pad + kebab slug).
  2. Current frontmatter parses + validates against :class:`RFCFrontmatter`.
  3. ``frontmatter.rfc`` matches the filename number.
  4. Git-history walk: every status transition lies on the
     :data:`ALLOWED_TRANSITIONS` DAG.
  5. Body-only-edit refusal heuristic (D-22): a commit that changed
     ``status:`` MUST also carry EITHER a ``Reason:`` commit-message
     trailer OR a ``status_change_reason:`` frontmatter line — otherwise
     the lifecycle is unaudited and the linter refuses the commit.

Directory-level checks:
  * Duplicate RFC numbers across files → fail.
  * ``RFC-TEMPLATE.md`` is the linter's golden fixture and is skipped.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from pydantic import ValidationError

from folio_insights.rfc.frontmatter import parse_frontmatter
from folio_insights.rfc.git_history import walk_history

RFC_FILENAME_RE = re.compile(r"^(\d{4})-[a-z0-9][a-z0-9-]*\.md$")

# D-22 status DAG. `rejected` and `implemented` are terminal — no exit edges.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"discussion"},
    "discussion": {"accepted", "rejected"},
    "accepted": {"implemented"},
    "rejected": set(),
    "implemented": set(),
}

# Matches `Reason: <text>` as a trailer line in a commit body. Multiline mode
# anchors `^` at line start; trailing text is unconstrained.
_REASON_TRAILER_RE = re.compile(r"(?m)^Reason:\s+\S")

# Key on the frontmatter dict that authorizes a status change without a
# commit-message trailer. Kept as a constant so the lint message can
# reference the exact string operators must spell.
_STATUS_CHANGE_REASON_KEY = "status_change_reason"


def _has_rationale(entry: dict) -> bool:
    """Return True if this commit carries a `Reason:` trailer or a
    `status_change_reason:` frontmatter line.

    `entry` is a `walk_history` dict containing `body` and
    `frontmatter_dict` keys.
    """
    if _REASON_TRAILER_RE.search(entry.get("body") or ""):
        return True
    fm_dict = entry.get("frontmatter_dict") or {}
    value = fm_dict.get(_STATUS_CHANGE_REASON_KEY)
    if isinstance(value, str) and value.strip():
        return True
    return False


def validate_rfc_file(path: Path, *, repo_root: Path | None = None) -> list[str]:
    """Return the list of lint errors for `path` (empty list = pass)."""
    errors: list[str] = []

    # 1. Filename
    m = RFC_FILENAME_RE.match(path.name)
    if not m:
        return [f"{path}: filename must match NNNN-kebab-title.md"]
    file_number = int(m.group(1))

    # 2. Current frontmatter
    try:
        fm = parse_frontmatter(path.read_text(encoding="utf-8"))
    except (ValueError, ValidationError) as e:
        return [f"{path}: frontmatter invalid — {e}"]
    if fm.rfc != file_number:
        errors.append(
            f"{path}: rfc:{fm.rfc} does not match filename {file_number:04d}"
        )

    # 3. History walk + monotonic transition DAG + body-only-edit refusal
    history = walk_history(path, repo_root=repo_root)
    prev_status: str | None = None
    for entry in history:
        cur = entry["status"]
        if prev_status is not None and cur != prev_status:
            allowed = ALLOWED_TRANSITIONS.get(prev_status, set())
            short_sha = entry["sha"][:8]
            if cur not in allowed:
                # Build a readable allowed-set for the error (sorted for
                # deterministic snapshot diffs).
                allowed_display = (
                    "{" + ", ".join(sorted(allowed)) + "}" if allowed else "{} (terminal)"
                )
                errors.append(
                    f"{path} commit {short_sha}: forbidden status transition "
                    f"{prev_status} → {cur} (allowed: {allowed_display})"
                )
            # D-22 body-only-edit-refusal heuristic
            if not _has_rationale(entry):
                errors.append(
                    f"{path} commit {short_sha}: status changed "
                    f"{prev_status} → {cur} but commit has "
                    f"no 'Reason:' trailer and no "
                    f"'{_STATUS_CHANGE_REASON_KEY}:' frontmatter line"
                )
        prev_status = cur

    return errors


def main(directory: Path) -> int:
    """Lint every `*.md` under `directory`; return process exit code.

    `RFC-TEMPLATE.md` is the linter's golden fixture and is skipped.
    `directory` itself is also walked as the git-history `repo_root` so
    tests can drop a tmp_path repo in and the relative-path arithmetic
    in `git_history.walk_history` Just Works.
    """
    all_errors: list[str] = []
    seen_numbers: set[int] = set()
    # Resolve repo_root upward: directory may live inside a working tree.
    repo_root = _resolve_repo_root(directory)

    for path in sorted(directory.glob("*.md")):
        if path.name == "RFC-TEMPLATE.md":
            continue
        m = RFC_FILENAME_RE.match(path.name)
        if m:
            n = int(m.group(1))
            if n in seen_numbers:
                all_errors.append(
                    f"{path}: duplicate RFC number {n:04d}"
                )
            seen_numbers.add(n)
        all_errors.extend(validate_rfc_file(path, repo_root=repo_root))

    for e in all_errors:
        print(f"::error::{e}", file=sys.stderr)
    return 1 if all_errors else 0


def _resolve_repo_root(start: Path) -> Path | None:
    """Walk parents from `start` looking for a `.git` dir/file."""
    cur = start.resolve()
    for candidate in (cur, *cur.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


if __name__ == "__main__":  # pragma: no cover - module CLI entry
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".planning/rfcs/")
    sys.exit(main(target))
