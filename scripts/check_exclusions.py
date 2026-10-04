"""Exclusion evidence check for the proposed-class governance work (plan U4, R5, KTD1).

Two checks, both metadata-only in what they print:

* **Path audit** (``--history BASE``). Every path touched by a commit in
  ``BASE..HEAD`` is compared with the excluded prefixes (``data/governance/``,
  ``docs/evidence/``, ``output/``, ``staging/``). A new commit that adds,
  modifies or deletes anything there is a finding.
* **Content scan.** Allowed text artifacts (data and prose formats such as
  JSON, JSONL, HTML, Markdown and YAML; never source code, never an excluded
  path) are scanned for values that only generated, book-derived material
  carries:

  - a non-empty string under an excerpt key (``excerpt``, ``source_text``,
    ``source_text_excerpt``, ``supporting_excerpt``, ``source_snippet``);
  - a non-empty derived definition (``draft_definition``) or book provenance
    (``books`` / ``chapters`` inside a ``provenance`` object);
  - a generated proposal artifact (a ``schema`` of ``proposed-class-*``).

  JSON and JSONL files are walked structurally. Other text is matched only on
  key/value assignments (``"key": "value"``, ``key: value``, ``data-key="value"``),
  so a field NAME in prose is not a finding. Source code is never scanned: field
  names in code (``payload["source_text"]``, a forbidden-key set) are references,
  not leaked values.

  By default the tree at HEAD is scanned (tracked files). With ``--history``,
  every blob that a commit in ``BASE..HEAD`` added or modified is scanned too, so
  material committed and later removed is still caught.

Findings never print a value: only the path, the location, the rule, the value's
length and a short sha256 prefix. Exit status 1 when anything is found.

Usage:
  python scripts/check_exclusions.py [--repo DIR] [--history BASE] [--json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

EXCLUDED_PREFIXES = ("data/governance/", "docs/evidence/", "output/", "staging/")
EXCERPT_KEYS = frozenset({
    "excerpt", "source_text", "source_text_excerpt", "supporting_excerpt", "source_snippet",
})
DERIVED_KEYS = frozenset({"draft_definition"})
PROVENANCE_BOOK_KEYS = frozenset({"books", "chapters"})
GENERATED_SCHEMA = re.compile(r"proposed-class-(registry|worklist|approval-queue|backlog|approvals)/")
STRUCTURED_SUFFIXES = frozenset({".json", ".jsonld", ".geojson"})
LINE_JSON_SUFFIXES = frozenset({".jsonl", ".ndjson"})
TEXT_SUFFIXES = frozenset({
    ".md", ".markdown", ".txt", ".html", ".htm", ".yaml", ".yml", ".csv", ".tsv", ".ttl",
    ".nq", ".nt", ".xml", ".rst",
})
_KEYS = "|".join(sorted(EXCERPT_KEYS | DERIVED_KEYS))
# Quoted assignments anywhere on a line: "key": "value", 'key': 'value', key="value", and
# HTML data attributes (data-key="value").
_QUOTED = re.compile(
    rf"""["']?\b(?P<k1>{_KEYS})\b["']?\s*[:=]\s*(?:"(?P<v1>(?:[^"\\]|\\.)*)"|'(?P<v2>[^']*)')"""
    rf"""|\bdata-(?P<k2>{_KEYS.replace('_', '-')})\s*=\s*"(?P<v3>[^"]*)\"""",
    re.IGNORECASE,
)
# Unquoted YAML-style mapping lines ("  key: some words"). Only a multi-word value counts: a
# single token after the colon is a type or a reference ("excerpt: str"), not a leaked span.
_YAML = re.compile(
    rf"""^\s*(?:-\s*)?(?P<k>{_KEYS})\s*:\s+(?P<v>[^\s#'"].*)$""", re.IGNORECASE
)
_SCHEMA_TEXT = re.compile(r"""["']?schema["']?\s*[:=]\s*["'](?P<v>proposed-class-[a-z-]+/[^"']*)["']""")


@dataclass(frozen=True)
class Finding:
    rule: str
    path: str
    where: str
    detail: str = ""
    commit: str = ""

    def render(self) -> str:
        at = f"{self.commit[:12]}:" if self.commit else ""
        return f"{self.rule}: {at}{self.path} {self.where} {self.detail}".rstrip()


def _fingerprint(value: str) -> str:
    return f"len={len(value)} sha256={hashlib.sha256(value.encode()).hexdigest()[:12]}"


def is_excluded(path: str) -> bool:
    return any(path.startswith(p) for p in EXCLUDED_PREFIXES)


def is_scanned(path: str) -> bool:
    suffix = PurePosixPath(path).suffix.lower()
    return not is_excluded(path) and (
        suffix in STRUCTURED_SUFFIXES or suffix in LINE_JSON_SUFFIXES or suffix in TEXT_SUFFIXES
    )


def _walk(value: Any, pointer: str, path: str, *, parent: str = "") -> Iterator[Finding]:
    if isinstance(value, dict):
        for key, item in value.items():
            k = str(key)
            here = f"{pointer}/{k.replace('~', '~0').replace('/', '~1')}"
            low = k.lower()
            if isinstance(item, str) and item.strip():
                if low in EXCERPT_KEYS:
                    yield Finding("excerpt-value", path, here, _fingerprint(item))
                elif low in DERIVED_KEYS:
                    yield Finding("derived-definition", path, here, _fingerprint(item))
                elif low == "schema" and GENERATED_SCHEMA.match(item):
                    yield Finding("generated-artifact", path, here, f"schema={item}")
            if parent == "provenance" and low in PROVENANCE_BOOK_KEYS and item:
                yield Finding("book-provenance", path, here, f"items={len(item) if hasattr(item, '__len__') else 1}")
            yield from _walk(item, here, path, parent=low)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk(item, f"{pointer}/{index}", path, parent=parent)


def scan_text(path: str, text: str) -> list[Finding]:
    """Scan one allowed artifact's text. ``path`` decides the parser."""
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in STRUCTURED_SUFFIXES:
        try:
            return list(_walk(json.loads(text), "", path))
        except ValueError:
            pass  # not valid JSON: fall back to the assignment scan
    if suffix in LINE_JSON_SUFFIXES:
        found: list[Finding] = []
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                found.extend(_walk(json.loads(line), f"line {number}:", path))
            except ValueError:
                found.extend(_scan_assignments(path, line, number))
        return found
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        found.extend(_scan_assignments(path, line, number))
    return found


def _scan_assignments(path: str, line: str, number: int) -> Iterator[Finding]:
    hits: list[tuple[str, str]] = []
    for match in _QUOTED.finditer(line):
        key = (match.group("k1") or match.group("k2") or "").lower().replace("-", "_")
        value = next((v for v in match.group("v1", "v2", "v3") if v is not None), "")
        hits.append((key, value.strip()))
    yaml = _YAML.match(line)
    if yaml and not hits:
        value = re.split(r"\s#", yaml.group("v"), maxsplit=1)[0].strip()
        if len(re.findall(r"[A-Za-z]{2,}", value)) >= 2:
            hits.append((yaml.group("k").lower(), value))
    for key, value in hits:
        if not value or value in {"null", "None", "...", "[]", "{}"}:
            continue
        rule = "derived-definition" if key in DERIVED_KEYS else "excerpt-value"
        yield Finding(rule, path, f"line {number}", f"key={key} {_fingerprint(value)}")
    for match in _SCHEMA_TEXT.finditer(line):
        if GENERATED_SCHEMA.match(match.group("v")):
            yield Finding("generated-artifact", path, f"line {number}", f"schema={match.group('v')}")


# ---------- git plumbing ----------


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def _blob(repo: Path, rev: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(repo), "show", f"{rev}:{path}"], capture_output=True, check=False
    )
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", errors="replace")


def scan_tree(repo: Path, rev: str = "HEAD") -> list[Finding]:
    findings: list[Finding] = []
    for path in _git(repo, "ls-tree", "-r", "--name-only", rev).splitlines():
        if is_scanned(path):
            text = _blob(repo, rev, path)
            if text is not None:
                findings.extend(scan_text(path, text))
    return findings


def audit_history(repo: Path, base: str, head: str = "HEAD") -> list[Finding]:
    """Path audit plus a content scan of every blob each new commit added or modified."""
    findings: list[Finding] = []
    commits = _git(repo, "rev-list", "--reverse", f"{base}..{head}").split()
    for commit in commits:
        changes = _git(repo, "diff-tree", "--no-commit-id", "-r", "--name-status", "-M",
                       "--root", commit)
        for line in changes.splitlines():
            parts = line.split("\t")
            status, paths = parts[0], parts[1:]
            for path in paths:
                if is_excluded(path):
                    findings.append(Finding("excluded-path", path, f"status={status[:1]}",
                                            commit=commit))
            target = paths[-1] if paths else ""
            if status[:1] in {"A", "M", "R", "C"} and is_scanned(target):
                text = _blob(repo, commit, target)
                if text is not None:
                    findings.extend(
                        Finding(f.rule, f.path, f.where, f.detail, commit)
                        for f in scan_text(target, text)
                    )
    return findings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=".", help="repository to check (default: cwd)")
    ap.add_argument("--rev", default="HEAD", help="tree to scan (default: HEAD)")
    ap.add_argument("--history", default=None, metavar="BASE",
                    help="also audit every commit in BASE..REV (paths and blobs)")
    ap.add_argument("--json", action="store_true", help="print findings as JSON")
    args = ap.parse_args(argv)
    repo = Path(args.repo)
    tree = scan_tree(repo, args.rev)
    history = audit_history(repo, args.history, args.rev) if args.history else []
    findings = tree + history
    summary = {
        "tree_rev": args.rev,
        "tree_findings": len(tree),
        "history_base": args.history,
        "history_commits": (
            len(_git(repo, "rev-list", f"{args.history}..{args.rev}").split())
            if args.history else 0
        ),
        "history_findings": len(history),
    }
    if args.json:
        print(json.dumps({**summary, "findings": [asdict(f) for f in findings]},
                         indent=2, sort_keys=True))
    else:
        for f in findings:
            print(f.render())
        print(json.dumps(summary, sort_keys=True))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
