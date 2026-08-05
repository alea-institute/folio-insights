#!/usr/bin/env python3
"""Insert-or-update a single hash-pinned package in the pip-compile lockfiles.

WHY THIS EXISTS
---------------
``requirements.lock`` and ``requirements.dev.lock`` were compiled from
``pyproject.toml`` before ``folio-resolve`` was a dependency, so they carry no
``folio-resolve`` line at all — while ``ci/build.py`` installs the dev lock with
``--require-hashes`` and then runs pytest. A full ``uv pip compile`` would re-resolve
all ~159 packages and turn a one-package pin into an unreviewable dependency sweep.
This script does the narrow thing instead: it rewrites exactly one package's block and
leaves every other byte of the file alone.

It is re-runnable and idempotent — running it twice with the same version is a no-op,
and running it with a new version replaces the block in place.

USAGE
-----
    # pin folio-resolve 0.3.1 into requirements.lock + requirements.dev.lock
    .venv/bin/python scripts/pin_folio_resolve_lock.py 0.3.1

    # would it change anything? (exit 1 = yes; good as a CI guard)
    .venv/bin/python scripts/pin_folio_resolve_lock.py 0.3.1 --check

    # some other package, or some other lockfile
    .venv/bin/python scripts/pin_folio_resolve_lock.py 1.2.3 --package some-lib \
        --lock requirements.dev.lock

Hashes come from the PyPI JSON API (``/pypi/<name>/<version>/json``) — every
distribution file published for that version, sdist and wheels, sorted ascending to
match uv's own ordering. Needs network access; nothing else.

WHY ``requirements.worker.lock`` IS NOT A DEFAULT TARGET
--------------------------------------------------------
It is compiled from ``requirements.worker.in``, which excludes the folio stack on
purpose ("Intentionally excludes ... folio-python ...", worker.in L2-3), and it
contains no ``pydantic``. ``folio-resolve`` requires ``pydantic``; under
``--require-hashes`` pip refuses an install whose transitive requirements are not
themselves hash-pinned, so writing this pin there would BREAK the worker image build
(``Dockerfile.worker`` L65-66) rather than protect it. The dependency check below
enforces that generically: a lockfile missing any of the package's own requirements is
refused by name, with the reason. Pass ``--allow-missing-deps`` only if you have also
added those requirements.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOCKS = ("requirements.lock", "requirements.dev.lock")
DEFAULT_PACKAGE = "folio-resolve"
DEFAULT_VIA = "folio-insights (pyproject.toml)"
PYPI_JSON = "https://pypi.org/pypi/{name}/{version}/json"

# A lock entry starts flush-left as ``name==version \``; continuation lines
# (``    --hash=...``) and annotations (``    # via ...``) are indented.
ENTRY_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==")


def normalize(name: str) -> str:
    """PEP 503 name normalization — lockfiles are written in normalized form."""
    return re.sub(r"[-_.]+", "-", name).lower()


def fetch_hashes(package: str, version: str) -> list[str]:
    """Return every sha256 published for this version (sdist + wheels), sorted."""
    url = PYPI_JSON.format(name=package, version=version)
    with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310 - fixed PyPI host
        payload = json.load(resp)
    digests = {f["digests"]["sha256"] for f in payload.get("urls", [])}
    if not digests:
        raise SystemExit(f"error: PyPI lists no distribution files for {package}=={version}")
    return sorted(digests)


def fetch_requirements(package: str, version: str) -> list[str]:
    """Return the package's own runtime requirement names (extras/markers stripped)."""
    url = PYPI_JSON.format(name=package, version=version)
    with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310 - fixed PyPI host
        payload = json.load(resp)
    names: list[str] = []
    for raw in payload.get("info", {}).get("requires_dist") or []:
        # Skip anything gated behind an extra — those are not installed by default.
        if ";" in raw and "extra ==" in raw.split(";", 1)[1]:
            continue
        name = re.split(r"[\s;\[(<>=!~]", raw.strip(), maxsplit=1)[0]
        if name:
            names.append(normalize(name))
    return names


def render_block(package: str, version: str, hashes: list[str], via: str) -> list[str]:
    """Render the pip-compile ``--require-hashes`` block for one package."""
    lines = [f"{package}=={version} \\\n"]
    for i, digest in enumerate(hashes):
        last = i == len(hashes) - 1
        lines.append(f"    --hash=sha256:{digest}{'' if last else ' \\'}\n")
    lines.append(f"    # via {via}\n")
    return lines


def find_entries(lines: list[str]) -> list[tuple[str, int, int]]:
    """Return (normalized_name, start_index, end_index_exclusive) for every entry."""
    starts: list[tuple[str, int]] = []
    for i, line in enumerate(lines):
        match = ENTRY_RE.match(line)
        if match:
            starts.append((normalize(match.group(1)), i))
    entries: list[tuple[str, int, int]] = []
    for pos, (name, start) in enumerate(starts):
        end = starts[pos + 1][1] if pos + 1 < len(starts) else len(lines)
        entries.append((name, start, end))
    return entries


def apply_pin(
    path: Path,
    package: str,
    version: str,
    hashes: list[str],
    via: str,
    requirements: list[str],
    allow_missing_deps: bool,
) -> tuple[bool, str]:
    """Insert-or-update ``package`` in ``path``. Returns (changed, message)."""
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    entries = find_entries(lines)
    present = {name for name, _, _ in entries}
    target = normalize(package)

    missing = [dep for dep in requirements if dep not in present and dep != target]
    if missing and not allow_missing_deps:
        return False, (
            f"REFUSED {path.name}: it does not pin {', '.join(missing)}, which "
            f"{package} requires. A --require-hashes install would fail on the "
            f"unhashed transitive dep. Add them first, or pass --allow-missing-deps."
        )

    block = render_block(package, version, hashes, via)

    for name, start, end in entries:
        if name == target:
            if lines[start:end] == block:
                return False, f"unchanged {path.name} (already {package}=={version})"
            new_lines = lines[:start] + block + lines[end:]
            path.write_text("".join(new_lines), encoding="utf-8")
            old = lines[start].split("==", 1)[1].split()[0]
            return True, f"updated   {path.name}: {package} {old} -> {version}"

    # Not present: insert in normalized-name order, matching uv's sort.
    insert_at = len(lines)
    for name, start, _ in entries:
        if name > target:
            insert_at = start
            break
    new_lines = lines[:insert_at] + block + lines[insert_at:]
    path.write_text("".join(new_lines), encoding="utf-8")
    return True, f"inserted  {path.name}: {package}=={version} at line {insert_at + 1}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Insert-or-update one hash-pinned package in the requirements locks.",
    )
    parser.add_argument("version", help="version to pin, e.g. 0.3.1")
    parser.add_argument("--package", default=DEFAULT_PACKAGE, help="package name")
    parser.add_argument(
        "--lock",
        action="append",
        dest="locks",
        metavar="PATH",
        help=f"lockfile to edit (repeatable; default: {', '.join(DEFAULT_LOCKS)})",
    )
    parser.add_argument("--via", default=DEFAULT_VIA, help="text for the '# via' annotation")
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; exit 1 if any lockfile would change",
    )
    parser.add_argument(
        "--allow-missing-deps",
        action="store_true",
        help="write even if the lockfile does not pin the package's own requirements",
    )
    args = parser.parse_args(argv)

    locks = [Path(p) for p in (args.locks or DEFAULT_LOCKS)]
    locks = [p if p.is_absolute() else REPO_ROOT / p for p in locks]
    for path in locks:
        if not path.is_file():
            print(f"error: no such lockfile: {path}", file=sys.stderr)
            return 2

    hashes = fetch_hashes(args.package, args.version)
    requirements = fetch_requirements(args.package, args.version)
    print(f"{args.package}=={args.version}: {len(hashes)} sha256 digests from PyPI")

    changed = False
    refused = False
    for path in locks:
        if args.check:
            before = path.read_text(encoding="utf-8")
            did, message = apply_pin(
                path, args.package, args.version, hashes, args.via,
                requirements, args.allow_missing_deps,
            )
            if did:
                path.write_text(before, encoding="utf-8")  # --check never persists
                message = f"WOULD CHANGE {path.name}"
        else:
            did, message = apply_pin(
                path, args.package, args.version, hashes, args.via,
                requirements, args.allow_missing_deps,
            )
        changed = changed or did
        refused = refused or message.startswith("REFUSED")
        print(f"  {message}")

    if refused:
        return 2
    if args.check and changed:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
