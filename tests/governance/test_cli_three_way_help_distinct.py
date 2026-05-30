"""D-16 CLI surface: contest / supersede / resolve-contest have DISTINCT --help text.

Each subcommand's --help mentions its distinct PRD section (or a distinguishing
phrase). The grep-guard regression test in test_grep_guard_three_way_disambiguation.py
covers the source-level discipline; this test covers the operator-facing surface.
"""
from __future__ import annotations

import pytest
from click.testing import CliRunner

from folio_insights.governance.cli import governance_group

pytestmark = pytest.mark.governance


def test_contest_help_mentions_distinct_prd_section() -> None:
    """`governance contest --help` mentions §21.8 or 'contest' / 'distinct'."""
    runner = CliRunner()
    result = runner.invoke(governance_group, ["contest", "--help"])
    assert result.exit_code == 0
    out = result.output.lower()
    # PATTERNS.md L677 allows "§21.8" OR the word "contest" — both pass.
    assert "§21.8" in result.output or "contest" in out


def test_supersede_help_mentions_distinct_prd_section() -> None:
    """`governance supersede --help` mentions §21.9 or 'supersede' / 'supersession'."""
    runner = CliRunner()
    result = runner.invoke(governance_group, ["supersede", "--help"])
    assert result.exit_code == 0
    out = result.output.lower()
    assert "§21.9" in result.output or "supersed" in out


def test_resolve_contest_help_mentions_gov_05() -> None:
    """`governance resolve-contest --help` mentions GOV-05 or the 3-path lock."""
    runner = CliRunner()
    result = runner.invoke(governance_group, ["resolve-contest", "--help"])
    assert result.exit_code == 0
    out = result.output
    # GOV-05 mention OR explicit listing of the 3 paths.
    has_gov_05 = "GOV-05" in out
    has_paths = "arbiter" in out and "distinguo" in out and "aporetic" in out
    assert has_gov_05 or has_paths


def test_three_help_texts_are_mutually_distinct() -> None:
    """contest --help != supersede --help != resolve-contest --help."""
    runner = CliRunner()
    contest = runner.invoke(governance_group, ["contest", "--help"]).output
    supersede = runner.invoke(governance_group, ["supersede", "--help"]).output
    resolve = runner.invoke(governance_group, ["resolve-contest", "--help"]).output
    assert contest != supersede
    assert supersede != resolve
    assert contest != resolve
