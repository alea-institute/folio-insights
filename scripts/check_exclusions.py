"""Exclusion evidence check for the proposed-class governance work (plan U4, R5, KTD1).

What this is, honestly: a **key and shape heuristic**. It finds book-derived material
that is labelled or shaped the way generated proposal artifacts label and shape it. It
cannot recognize unlabelled book prose. The real gate is ``--book PATH``: a 12-word
shingle comparison against a local copy of the source text, which reports counts only.
Run both before publishing.

Checks (everything printed is metadata: paths, rules, lengths, digest prefixes, counts):

* **Path audit** (``--history BASE``). Every path touched by a commit in
  ``BASE..HEAD`` is compared with the excluded prefixes (``data/governance/``,
  ``docs/evidence/``, ``output/``, ``staging/``). A new commit that adds, modifies or
  deletes anything there is a finding.
* **Content scan.** Allowed text artifacts (data and prose formats such as JSON, JSONL,
  notebooks, HTML, Markdown and YAML; never source code, never an excluded path) are
  scanned, at HEAD and (with ``--history``) in every blob a new commit added or modified:

  - **strong excerpt keys** (the proposal ledger's ``FORBIDDEN_PAYLOAD_KEYS`` except
    ``text``, plus ``quote``, ``snippet`` and ``passage``): any non-empty value;
  - **weak keys** (``text``, ``quote``, ``snippet``, ``passage``, ``reviewer_note``): a
    value of at least ``PROSE_WORDS`` words;
  - **derived definitions** (``draft_definition``) and **book provenance** (``books`` /
    ``chapters`` inside ``provenance``);
  - **generated proposal artifacts** (a ``schema`` of ``proposed-class-*``);
  - **Markdown and HTML shapes**: ``key: value`` / ``**Key:** value`` lines of at least
    ``PROSE_WORDS`` words, table cells under (or next to) a key-named cell, elements
    whose class names a key, and blockquotes of at least ``BLOCKQUOTE_WORDS`` words.

  Rules are **strong** (an excerpt-key value, a derived definition, book provenance, a
  generated artifact, an excluded path, shared book shingles) or **shape** (prose under a
  weak key, a key-labelled table cell, a long blockquote). Any finding in a new commit's
  blob fails the check, and so does a strong finding anywhere in the tree. Shape findings
  in content that predates BASE are advisory (reported with counts, exit 0) unless
  ``--strict``: ordinary docs quote people and tables hold prose, so those need the
  ``--book`` shingle check, not a key heuristic.

  Keys match case-, space- and hyphen-insensitively ("Excerpt ", "source-text"). Source
  code is never content-scanned: field names in code are references, not leaked values.
  Printed pointers never contain a raw key: unknown keys are shown as a digest.
* **Shingle check** (``--book PATH``). Every tracked file at REV (code included,
  excluded paths never read) and, with ``--history``, every new blob, is compared with
  the book's 12-word shingles. Output is per-path overlap COUNTS only. The book file
  must live outside the repository.

Exit status 1 when a failing finding exists (see the strong/shape rule above).

Usage:
  python scripts/check_exclusions.py [--repo DIR] [--history BASE] [--book PATH]
      [--strict] [--show-advisory] [--json]
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

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from folio_insights.storage.proposals import FORBIDDEN_PAYLOAD_KEYS  # noqa: E402

EXCLUDED_PREFIXES = ("data/governance/", "docs/evidence/", "output/", "staging/")
WEAK_KEYS = frozenset({"text", "quote", "snippet", "passage", "reviewer_note"})
EXCERPT_KEYS = (frozenset(FORBIDDEN_PAYLOAD_KEYS) | {"quote", "snippet", "passage"}) - {"text"}
DERIVED_KEYS = frozenset({"draft_definition"})
PROVENANCE_BOOK_KEYS = frozenset({"books", "chapters"})
ALL_KEYS = EXCERPT_KEYS | WEAK_KEYS | DERIVED_KEYS
SAFE_POINTER_KEYS = ALL_KEYS | PROVENANCE_BOOK_KEYS | {"provenance", "schema"}
PROSE_WORDS = 8
BLOCKQUOTE_WORDS = 12
SHINGLE_WORDS = 12
SHAPE_RULES = frozenset({"prose-value", "table-prose", "blockquote-prose"})
GENERATED_SCHEMA = re.compile(
    r"proposed-class-(registry|worklist|approval-queue|backlog|approvals)/"
)
STRUCTURED_SUFFIXES = frozenset({".json", ".jsonld", ".geojson", ".ipynb"})
LINE_JSON_SUFFIXES = frozenset({".jsonl", ".ndjson"})
TEXT_SUFFIXES = frozenset({
    ".md", ".markdown", ".txt", ".html", ".htm", ".yaml", ".yml", ".csv", ".tsv", ".ttl",
    ".nq", ".nt", ".xml", ".rst",
})
_EMPTY = {"", "null", "None", "...", "…", "[]", "{}", '""', "''"}
_WORDS = re.compile(r"[^\W\d_]{2,}")


def norm_key(key: str) -> str:
    return re.sub(r"[\s\-]+", "_", str(key).strip().casefold()).strip("_")


def _key_pattern(keys: frozenset[str]) -> str:
    # source_text also matches "source text", "Source-Text" and the like.
    return "|".join(
        k.replace("_", r"[\s_-]?") for k in sorted(keys, key=len, reverse=True)
    )


_KP = _key_pattern(ALL_KEYS)
_QUOTED = re.compile(
    rf"""["']\s*(?P<k1>{_KP})\s*["']\s*[:=]\s*(?:"(?P<v1>(?:[^"\\]|\\.)*)"|'(?P<v2>(?:[^'\\]|\\.)*)')"""
    rf"""|\b(?P<k3>{_KP})\s*=\s*(?:"(?P<v3>(?:[^"\\]|\\.)*)"|'(?P<v4>(?:[^'\\]|\\.)*)')"""
    rf"""|\bdata-(?P<k2>{_KP})\s*=\s*"(?P<v5>[^"]*)\"""",
    re.IGNORECASE,
)
_TRIPLE = re.compile(rf"""\b(?P<k>{_KP})\s*[:=]\s*(?P<q>\"\"\"|''')(?P<v>.*?)(?P=q)""",
                     re.IGNORECASE | re.DOTALL)
# "key: value", "- key: value", "**Key:** value", "__Key__: value", "1. *Key*: value"
_LABELLED = re.compile(
    rf"""^\s*(?:[-*+]\s+|\d+[.)]\s+)?[*_]{{0,2}}\s*(?P<k>{_KP})\s*(?:[*_]{{0,2}}\s*:|:\s*[*_]{{0,2}})"""
    rf"""\s*(?P<v>\S.*)$""",
    re.IGNORECASE,
)
_HTML_CLASS = re.compile(
    rf"""<(?P<tag>[a-z][a-z0-9]*)\b[^>]*\bclass\s*=\s*["'][^"']*\b(?P<k>{_KP})\b"""
    rf"""[^"']*["'][^>]*>(?P<v>[^<]+)""",
    re.IGNORECASE,
)
_SCHEMA_TEXT = re.compile(
    r"""["']?schema["']?\s*[:=]\s*["'](?P<v>proposed-class-[a-z-]+/[^"']*)["']"""
)


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


def _pointer_part(key: Any) -> str:
    k = norm_key(key)
    if k in SAFE_POINTER_KEYS:
        return k
    return "#" + hashlib.sha256(str(key).encode()).hexdigest()[:8]


def _words(value: str) -> int:
    return len(_WORDS.findall(value))


def _value_finding(key: str, value: str, path: str, where: str) -> Finding | None:
    """The finding for ``value`` under (normalized) ``key``, or ``None``."""
    value = value.strip()
    if value in _EMPTY:
        return None
    if key in DERIVED_KEYS:
        return Finding("derived-definition", path, where, f"key={key} {_fingerprint(value)}")
    if key in EXCERPT_KEYS:
        return Finding("excerpt-value", path, where, f"key={key} {_fingerprint(value)}")
    if key in WEAK_KEYS and _words(value) >= PROSE_WORDS:
        return Finding("prose-value", path, where, f"key={key} {_fingerprint(value)}")
    return None


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
            k = norm_key(key)
            here = f"{pointer}/{_pointer_part(key)}"
            if isinstance(item, str):
                found = _value_finding(k, item, path, here)
                if found is not None:
                    yield found
                elif k == "schema" and GENERATED_SCHEMA.match(item):
                    yield Finding("generated-artifact", path, here, f"schema={item}")
            elif k in EXCERPT_KEYS and isinstance(item, list) and any(
                isinstance(x, str) and x.strip() for x in item
            ):
                yield Finding("excerpt-value", path, here, f"key={k} items={len(item)}")
            if parent == "provenance" and k in PROVENANCE_BOOK_KEYS and item:
                count = len(item) if hasattr(item, "__len__") else 1
                yield Finding("book-provenance", path, here, f"items={count}")
            yield from _walk(item, here, path, parent=k)
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
            pass  # not valid JSON: fall back to the text scan
    if suffix in LINE_JSON_SUFFIXES:
        found: list[Finding] = []
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                found.extend(_walk(json.loads(line), f"line {number}:", path))
            except ValueError:
                found.extend(_scan_line(path, line, number, {}))
        return found
    found = []
    table: dict[str, Any] = {}
    for number, line in enumerate(text.splitlines(), 1):
        found.extend(_scan_line(path, line, number, table))
    for match in _TRIPLE.finditer(text):
        number = text.count("\n", 0, match.start()) + 1
        hit = _value_finding(norm_key(match.group("k")), match.group("v"), path, f"line {number}")
        if hit is not None:
            found.append(hit)
    return found


def _cells(line: str) -> list[str] | None:
    s = line.strip()
    if not (s.startswith("|") and s.endswith("|") and s.count("|") >= 3):
        return None
    return [c.strip() for c in s[1:-1].split("|")]


def _plain_key(cell: str) -> str:
    return norm_key(re.sub(r"[*_`]", "", cell))


def _scan_table(path: str, line: str, number: int, table: dict[str, Any]) -> Iterator[Finding]:
    """A Markdown table cell of prose under a key-named column, or in a row whose other
    cell names a key."""
    cells = _cells(line)
    if cells is None:
        table.clear()
        return
    if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
        table["header"] = [_plain_key(c) for c in table.get("last", [])]
        return
    table["last"] = cells
    header = table.get("header", [])
    row_key = next((k for k in map(_plain_key, cells) if k in ALL_KEYS), "")
    for index, cell in enumerate(cells):
        column = header[index] if index < len(header) else ""
        key = column if column in ALL_KEYS else row_key
        if not key or _plain_key(cell) in ALL_KEYS:
            continue
        if _words(cell) >= PROSE_WORDS:
            yield Finding("table-prose", path, f"line {number}",
                          f"key={key} {_fingerprint(cell)}")
            return


def _scan_line(path: str, line: str, number: int, table: dict[str, Any]) -> Iterator[Finding]:
    where = f"line {number}"
    hits = 0
    for match in _QUOTED.finditer(line):
        key = norm_key(match.group("k1") or match.group("k2") or match.group("k3") or "")
        value = next((v for v in match.group("v1", "v2", "v3", "v4", "v5") if v is not None), "")
        found = _value_finding(key, value, path, where)
        if found is not None:
            hits += 1
            yield found
    labelled = _LABELLED.match(line)
    if labelled and not hits:
        key = norm_key(labelled.group("k"))
        value = re.split(r"\s#\s", labelled.group("v"), maxsplit=1)[0]
        value = value.strip().strip("*_").strip()
        # A short value after the colon is a type, a reference or a style note
        # ("excerpt: str", "Source text: 14px"), not a span: only prose counts.
        if _words(value) >= PROSE_WORDS:
            found = _value_finding(key, value, path, where)
            if found is not None:
                hits += 1
                yield found
    for match in _HTML_CLASS.finditer(line):
        key = norm_key(match.group("k"))
        found = _value_finding(key, match.group("v"), path, where)
        if found is not None:
            hits += 1
            yield found
    quote = re.match(r"^\s*(?:>\s*)+(?P<v>.*)$", line)
    if quote and _words(quote.group("v")) >= BLOCKQUOTE_WORDS:
        yield Finding("blockquote-prose", path, where, _fingerprint(quote.group("v").strip()))
    yield from _scan_table(path, line, number, table)
    for match in _SCHEMA_TEXT.finditer(line):
        if GENERATED_SCHEMA.match(match.group("v")):
            yield Finding("generated-artifact", path, where, f"schema={match.group('v')}")


# ---------- shingles (counts only) ----------


def _shingles(text: str, n: int = SHINGLE_WORDS) -> set[bytes]:
    words = re.findall(r"[a-z0-9]+", text.casefold())
    return {
        hashlib.sha1(" ".join(words[i:i + n]).encode()).digest()
        for i in range(len(words) - n + 1)
    }


def load_book_shingles(book: Path, repo: Path) -> set[bytes]:
    book = Path(book).resolve()
    top = Path(_git(repo, "rev-parse", "--show-toplevel").strip()).resolve()
    if book == top or top in book.parents:
        raise SystemExit("refusing a --book path inside the repository; keep the book outside")
    return _shingles(book.read_text(encoding="utf-8", errors="replace"))


def shingle_overlap(repo: Path, book: set[bytes], rev: str = "HEAD",
                    base: str | None = None) -> list[Finding]:
    """Per-path counts of shared shingles, for every tracked non-excluded file at ``rev``
    and every blob a commit in ``base..rev`` added or modified. Never prints text."""
    findings: list[Finding] = []
    for path in _git(repo, "ls-tree", "-r", "--name-only", rev).splitlines():
        if is_excluded(path):
            continue
        text = _blob(repo, rev, path)
        if text is not None:
            hits = len(_shingles(text) & book)
            if hits:
                findings.append(Finding("book-shingles", path, "tree", f"shared={hits}"))
    if base:
        for commit, status, path in _changes(repo, base, rev):
            if status in {"A", "M", "R", "C"} and not is_excluded(path):
                text = _blob(repo, commit, path)
                if text is not None:
                    hits = len(_shingles(text) & book)
                    if hits:
                        findings.append(
                            Finding("book-shingles", path, "history", f"shared={hits}", commit)
                        )
    return findings


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


def _changes(repo: Path, base: str, head: str) -> Iterator[tuple[str, str, str]]:
    """``(commit, status letter, path)`` for every path each commit in base..head touched.
    For a rename or copy the source side is reported as ``D``; only the destination is new
    content."""
    for commit in _git(repo, "rev-list", "--reverse", f"{base}..{head}").split():
        changes = _git(repo, "diff-tree", "--no-commit-id", "-r", "--name-status", "-M",
                       "--root", commit)
        for line in changes.splitlines():
            parts = line.split("\t")
            status, paths = parts[0][:1], parts[1:]
            for index, path in enumerate(paths):
                yield commit, (status if index == len(paths) - 1 else "D"), path


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
    for commit, status, path in _changes(repo, base, head):
        if is_excluded(path):
            findings.append(Finding("excluded-path", path, f"status={status}", commit=commit))
        elif status in {"A", "M", "R", "C"} and is_scanned(path):
            text = _blob(repo, commit, path)
            if text is not None:
                findings.extend(
                    Finding(f.rule, f.path, f.where, f.detail, commit)
                    for f in scan_text(path, text)
                )
    return findings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=".", help="repository to check (default: cwd)")
    ap.add_argument("--rev", default="HEAD", help="tree to scan (default: HEAD)")
    ap.add_argument("--history", default=None, metavar="BASE",
                    help="also audit every commit in BASE..REV (paths and blobs)")
    ap.add_argument("--book", default=None, metavar="PATH",
                    help="also compare 12-word shingles with this local book copy "
                         "(outside the repository); prints counts only")
    ap.add_argument("--strict", action="store_true",
                    help="treat shape findings in pre-existing tree content as failures")
    ap.add_argument("--show-advisory", action="store_true",
                    help="print advisory shape findings (metadata only)")
    ap.add_argument("--json", action="store_true", help="print findings as JSON")
    args = ap.parse_args(argv)
    repo = Path(args.repo)
    tree = scan_tree(repo, args.rev)
    history = audit_history(repo, args.history, args.rev) if args.history else []
    shingles: list[Finding] = []
    if args.book:
        shingles = shingle_overlap(repo, load_book_shingles(Path(args.book), repo),
                                   args.rev, args.history)
    failing = [f for f in tree if args.strict or f.rule not in SHAPE_RULES] + history + shingles
    advisory = [f for f in tree if not args.strict and f.rule in SHAPE_RULES]
    summary = {
        "tree_rev": args.rev,
        "tree_findings": len(tree) - len(advisory),
        "tree_shape_advisory": len(advisory),
        "history_base": args.history,
        "history_commits": (
            len(_git(repo, "rev-list", f"{args.history}..{args.rev}").split())
            if args.history else 0
        ),
        "history_findings": len(history),
        "book_checked": bool(args.book),
        "book_shingle_findings": len(shingles),
    }
    if args.json:
        print(json.dumps({**summary, "findings": [asdict(f) for f in failing],
                          "advisory": [asdict(f) for f in advisory]}, indent=2, sort_keys=True))
    else:
        for f in failing:
            print(f.render())
        if advisory and args.show_advisory:
            for f in advisory:
                print("advisory " + f.render())
        print(json.dumps(summary, sort_keys=True))
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main())
