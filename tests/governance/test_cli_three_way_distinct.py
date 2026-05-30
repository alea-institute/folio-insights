"""``governance --help`` lists contest, supersede, resolve-contest as separate subcommands.

This is the D-16 CLI surface check at the GROUP level — the three
disambiguation subcommands appear distinctly in the help, alongside the
existing promote / assert-role / revoke-role from 07-04b.
"""
from __future__ import annotations

import pytest
from click.testing import CliRunner

from folio_insights.governance.cli import governance_group

pytestmark = pytest.mark.governance


def test_governance_group_lists_three_way_subcommands() -> None:
    """`governance --help` lists contest, supersede, resolve-contest."""
    runner = CliRunner()
    result = runner.invoke(governance_group, ["--help"])
    assert result.exit_code == 0
    out = result.output
    assert "contest" in out
    assert "supersede" in out
    assert "resolve-contest" in out


def test_governance_group_preserves_07_04b_subcommands() -> None:
    """Adding the three new subcommands does NOT remove promote/assert-role/revoke-role."""
    runner = CliRunner()
    result = runner.invoke(governance_group, ["--help"])
    assert result.exit_code == 0
    out = result.output
    assert "promote" in out
    assert "assert-role" in out
    assert "revoke-role" in out
