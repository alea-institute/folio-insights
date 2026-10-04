"""U4 exclusion evidence check (``scripts/check_exclusions.py``), on synthetic repositories.

* A synthetic non-empty excerpt is detected in JSON, JSONL, Markdown and HTML.
* Field-name references are not false positives: source code is never scanned, and in
  text only a key/value assignment with a non-empty value counts.
* Derived definitions, book provenance and generated proposal artifacts are detected.
* The path audit flags a new commit that touches an excluded path, and the content scan
  never reads files under excluded paths.
* A finding never prints the value it found.
* The real repository's tree is clean.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SENTINEL = "SYNTHETIC-EXCERPT-SENTINEL a passage that must never print"


def _scanner():
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        import check_exclusions
    finally:
        sys.path.remove(str(REPO_ROOT / "scripts"))
    return check_exclusions


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=Synthetic", "-c", "user.email=s@example.invalid",
         "-c", "commit.gpgsign=false", *args],
        check=True, capture_output=True, text=True,
    ).stdout


def _commit(repo: Path, files: dict[str, str], message: str) -> None:
    for rel, text in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--no-verify", "-m", message)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _commit(repo, {"README.md": "Synthetic base.\n"}, "base")
    _git(repo, "tag", "base")
    return repo


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("w.json", json.dumps({"items": [{"supporting_excerpt": SENTINEL}]})),
        ("w.jsonl", json.dumps({"source_text": SENTINEL}) + "\n"),
        ("notes.md", f'Example row: {{"source_snippet": "{SENTINEL}"}}\n'),
        ("page.html", f'<div data-excerpt="{SENTINEL}"></div>\n'),
        ("cfg.yaml", f"excerpt: {SENTINEL}\n"),  # 8 words: prose
    ],
)
def test_nonempty_excerpt_is_detected_without_printing_it(name, text):
    scanner = _scanner()
    findings = scanner.scan_text(name, text)
    assert [f.rule for f in findings] == ["excerpt-value"]
    rendered = "\n".join(f.render() for f in findings)
    assert SENTINEL not in rendered and "SYNTHETIC" not in rendered
    assert "len=" in rendered and "sha256=" in rendered


@pytest.mark.parametrize(
    ("name", "text"),
    [
        # Empty strong keys, and a short value under a weak key (a label, not prose).
        ("w.json", json.dumps({"supporting_excerpt": "", "source_text": None,
                               "text": "Synthetic short label"})),
        ("doc.md", "Worklist items carry no `supporting_excerpt`; `source_text` is dropped.\n"),
        ("doc.md", "**Rule excerpt:**\n"),
        ("doc.md", "    draft_definition: str   # a typed field in a code sample\n"),
        ("doc.md", 'An empty example: {"source_text": ""}\n'),
    ],
)
def test_field_name_references_and_empty_values_are_not_findings(name, text):
    assert _scanner().scan_text(name, text) == []


def test_derived_definitions_book_provenance_and_generated_artifacts_are_detected():
    scanner = _scanner()
    registry = {
        "schema": "proposed-class-registry/v1",
        "proposals": [{"draft_definition": "An invented derived definition.",
                       "provenance": {"books": ["SYN"], "chapters": ["1"], "runs": ["r1"]}}],
    }
    rules = sorted(f.rule for f in scanner.scan_text("r.json", json.dumps(registry)))
    assert rules == ["book-provenance", "book-provenance", "derived-definition",
                     "generated-artifact"]
    # The current registry keeps run names only: no finding.
    clean = {"proposals": [{"provenance": {"runs": ["r1"]}, "draft_definition": ""}]}
    assert scanner.scan_text("r.json", json.dumps(clean)) == []


def test_source_code_is_never_scanned(repo):
    scanner = _scanner()
    code = (
        'FORBIDDEN = {"excerpt", "source_text", "supporting_excerpt"}\n'
        f'row = {{"supporting_excerpt": "{SENTINEL}"}}\n'
        'value = payload["source_text"]\n'
    )
    _commit(repo, {"src/mod.py": code, "web/app.ts": code, "web/view.svelte": code}, "code")
    assert not scanner.is_scanned("src/mod.py")
    assert scanner.scan_tree(repo) == []
    assert scanner.audit_history(repo, "base") == []


def test_path_audit_flags_excluded_paths_and_never_reads_them(repo):
    scanner = _scanner()
    _commit(repo, {
        "staging/run.json": json.dumps({"supporting_excerpt": SENTINEL}),
        "docs/evidence/pack.json": json.dumps({"source_text": SENTINEL}),
        "docs/ok.md": "Plain synthetic note.\n",
    }, "adds excluded paths")
    findings = scanner.audit_history(repo, "base")
    assert sorted((f.rule, f.path) for f in findings) == [
        ("excluded-path", "docs/evidence/pack.json"),
        ("excluded-path", "staging/run.json"),
    ]
    # The tree scan skips excluded paths entirely: no content finding for them.
    assert scanner.scan_tree(repo) == []


def test_history_scan_catches_material_added_then_removed(repo):
    scanner = _scanner()
    _commit(repo, {"fixtures/w.json": json.dumps({"supporting_excerpt": SENTINEL})}, "add")
    _commit(repo, {"fixtures/w.json": json.dumps({"supporting_excerpt": ""})}, "scrub")
    assert scanner.scan_tree(repo) == []
    history = scanner.audit_history(repo, "base")
    assert [(f.rule, f.path) for f in history] == [("excerpt-value", "fixtures/w.json")]
    assert history[0].commit


def test_cli_exit_status_and_summary(repo):
    _commit(repo, {"fixtures/w.json": json.dumps({"excerpt": SENTINEL})}, "add")
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "check_exclusions.py"),
         "--repo", str(repo), "--history", "base"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert SENTINEL not in result.stdout + result.stderr
    summary = json.loads(result.stdout.strip().splitlines()[-1])
    assert summary["tree_findings"] == 1 and summary["history_findings"] == 1


def test_this_repository_tree_is_clean():
    """The tracked tree at HEAD carries no strong finding (excerpt-key value, derived
    definition, book provenance or generated proposal artifact) in any allowed text file.
    Shape findings in pre-existing docs are advisory; see the scanner docstring."""
    probe = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
                           capture_output=True, check=False)
    if probe.returncode != 0:
        pytest.skip("not a git checkout (e.g. a built image)")
    scanner = _scanner()
    findings = [f for f in scanner.scan_tree(REPO_ROOT) if f.rule not in scanner.SHAPE_RULES]
    assert findings == [], [f.render() for f in findings]


# ---------- review P2-4: false negatives, key leaks, shingles ----------

PROSE = "The synthetic court held that the zephyr quorum widget governs every lantern filing."


@pytest.mark.parametrize(
    ("name", "text", "rule"),
    [
        ("b.json", json.dumps({"text": PROSE}), "prose-value"),
        ("c.json", json.dumps({"quote": PROSE}), "excerpt-value"),
        ("d.json", json.dumps({"supporting_units": [{"snippet": PROSE}]}), "excerpt-value"),
        ("e.json", json.dumps({"decision": {"reviewer_note": PROSE}}), "prose-value"),
        ("f.md", f"> {PROSE}\n", "blockquote-prose"),
        ("g.md", f"| excerpt | {PROSE} |\n", "table-prose"),
        ("g2.md", f"| id | quote |\n|---|---|\n| u1 | {PROSE} |\n", "table-prose"),
        ("h.md", f"- **Excerpt:** {PROSE}\n", "excerpt-value"),
        ("i.html", f"<td class='excerpt'>{PROSE}</td>", "excerpt-value"),
        ("l.ipynb", json.dumps({"cells": [{"outputs": [{"excerpt": PROSE}]}]}), "excerpt-value"),
        ("m.json", json.dumps({"Excerpt ": PROSE}), "excerpt-value"),
        ("m2.json", json.dumps({"Source-Text": PROSE}), "excerpt-value"),
        ("o.txt", f'source_text = """{PROSE}"""', "excerpt-value"),
        ("s.json", json.dumps({"source_text_excerpt": PROSE}), "excerpt-value"),
    ],
)
def test_reviewed_false_negatives_are_detected(name, text, rule):
    assert _scanner().is_scanned(name)  # notebooks included
    findings = _scanner().scan_text(name, text)
    assert [f.rule for f in findings] == [rule]
    assert "zephyr" not in findings[0].render()


def test_every_ledger_forbidden_key_is_a_scanner_key():
    from folio_insights.storage.proposals import FORBIDDEN_PAYLOAD_KEYS

    scanner = _scanner()
    assert FORBIDDEN_PAYLOAD_KEYS <= scanner.ALL_KEYS
    for key in FORBIDDEN_PAYLOAD_KEYS:
        assert scanner.scan_text("x.json", json.dumps({key: PROSE})), key


def test_pointers_never_print_a_raw_key():
    leaky = "Leaky Synthetic Book Label Here"
    findings = _scanner().scan_text("n.json", json.dumps({leaky: {"excerpt": PROSE}}))
    rendered = findings[0].render()
    assert leaky not in rendered and "Leaky" not in rendered
    assert "/#" in findings[0].where and findings[0].where.endswith("/excerpt")


@pytest.mark.parametrize(
    "text",
    [
        "Note: the excerpt field is dropped at collection.\n",
        "- Source text: 14px/400, `--surface` bg, 16px padding\n",
        "> Short quote.\n",
        "| Status | Path | Notes |\n|---|---|---|\n| A | `x.py` | " + PROSE + " |\n",
    ],
)
def test_ordinary_docs_are_not_findings(text):
    assert _scanner().scan_text("doc.md", text) == []


def test_shape_findings_in_old_content_are_advisory_but_new_ones_fail(repo):
    _commit(repo, {"docs/old.md": f"> {PROSE}\n"}, "old quote")
    _git(repo, "tag", "base2")
    scanner = _scanner()
    run = [sys.executable, str(REPO_ROOT / "scripts" / "check_exclusions.py"),
           "--repo", str(repo), "--history", "base2"]
    ok = subprocess.run(run, capture_output=True, text=True, check=False)
    assert ok.returncode == 0, ok.stdout
    assert json.loads(ok.stdout.splitlines()[-1])["tree_shape_advisory"] == 1
    strict = subprocess.run([*run, "--strict"], capture_output=True, text=True, check=False)
    assert strict.returncode == 1
    _commit(repo, {"docs/new.md": f"> {PROSE}\n"}, "new quote")
    new = subprocess.run(run, capture_output=True, text=True, check=False)
    assert new.returncode == 1
    assert [f.rule for f in scanner.audit_history(repo, "base2")] == ["blockquote-prose"]


def test_book_shingle_mode_reports_counts_only(repo, tmp_path):
    book_text = " ".join(f"synthetic{i} lantern" for i in range(60))
    book = tmp_path / "book.txt"
    book.write_text(book_text)
    words = book_text.split()
    _commit(repo, {"src/fixture.py": f'X = "{" ".join(words[10:40])}"\n'}, "copies a span")
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "check_exclusions.py"),
         "--repo", str(repo), "--history", "base", "--book", str(book)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert "synthetic1" not in result.stdout and "lantern" not in result.stdout
    lines = result.stdout.strip().splitlines()
    assert any(line.startswith("book-shingles: src/fixture.py tree shared=") for line in lines)
    assert json.loads(lines[-1])["book_shingle_findings"] == 2  # tree + history
    inside = repo / "book.txt"
    inside.write_text(book_text)
    refused = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "check_exclusions.py"),
         "--repo", str(repo), "--book", str(inside)],
        capture_output=True, text=True, check=False,
    )
    assert refused.returncode != 0 and "outside" in (refused.stdout + refused.stderr)
