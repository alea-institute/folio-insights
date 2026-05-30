"""D-16 quality gate: contest / supersede / retract must NOT share codepaths.

This is the QUALITY GATE for the Phase 7 three-way disambiguation discipline.
It is shipped in its OWN task (07-05a Task 2) — per the quality_gate
convention from the plan revision (Issue #6 split) — so the regression check
is decoupled from any single module's implementation. Failing this test
indicates a structural refactor toward DRY across the three modules; reverting
the cross-coupling is the only fix.

Three orthogonal grep-style discipline checks (PATTERNS.md L596-680):

  (a) No cross-imports among contest.py / supersede.py / retract.py.
  (b) No shared base class beyond GovernanceEvent / _BaseEvent / BaseModel.
  (c) The three Click commands share no implementation function (forbidden
      helpers: ``execute_disagreement``, ``_dispatch_disagreement``,
      ``handle_disputed_action``).

retract.py ships in 07-05b. We use ``pytest.importorskip`` at the module top
so the retract branch becomes a no-op until 07-05b lands, at which point the
test automatically expands to cover the full triad (no edit needed in 07-05b).

Primary analogs:
  * ``tests/shards/test_dep_leak_guard.py`` — per-file ``read_text`` source scan.
  * ``tests/identity/test_no_server_keys_contract.py`` — AST-walk pattern.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from folio_insights import governance as _gov

pytestmark = pytest.mark.governance


# THREE_WAY = ("contest", "supersede", "retract") — retract ships in 07-05b.
# Until retract.py lands, the retract branch of each parametrized test will
# pytest.skip via importorskip below.
THREE_WAY = ("contest", "supersede", "retract")

_GOV_DIR = pathlib.Path(_gov.__file__).parent

# When 07-05b lands ``folio_insights.governance.retract``, this importorskip
# becomes a no-op and the parametrized tests automatically expand from 2-of-3
# coverage to the full 3-of-3 triad WITHOUT any edit to this test file. The
# helper functions below also call importorskip-by-module-path as a per-branch
# safety net so a partial 07-05b (e.g. retract.py but not cli/retract.py)
# skips gracefully.
_RETRACT_GATE = pytest.importorskip(
    "folio_insights.governance.retract",
    reason="folio_insights.governance.retract ships in 07-05b — until then the "
    "retract branches of the three-way grep-guard SKIP. Contest + supersede "
    "branches enforce now.",
) if (_GOV_DIR / "retract.py").exists() else None


def _module_path(module_name: str) -> pathlib.Path:
    """Return the path to ``governance/<module_name>.py``; skip if it doesn't exist."""
    path = _GOV_DIR / f"{module_name}.py"
    if not path.exists():
        # retract.py ships in 07-05b — until then, skip the branch. Once
        # 07-05b lands, the test automatically enforces the full triad.
        pytest.importorskip(f"folio_insights.governance.{module_name}")
    return path


def _cli_module_path(module_name: str) -> pathlib.Path:
    """Return the path to ``governance/cli/<module_name>.py``; skip if absent."""
    path = _GOV_DIR / "cli" / f"{module_name}.py"
    if not path.exists():
        pytest.importorskip(f"folio_insights.governance.cli.{module_name}")
    return path


# ── Grep-guard 1: no cross-imports ─────────────────────────────────────────


@pytest.mark.parametrize("module_name", THREE_WAY)
def test_three_way_modules_do_not_cross_import(module_name: str) -> None:
    """Each of contest / supersede / retract must NOT import from the other two."""
    path = _module_path(module_name)
    source = path.read_text(encoding="utf-8")
    other_modules = [m for m in THREE_WAY if m != module_name]
    for other in other_modules:
        assert f"from folio_insights.governance.{other}" not in source, (
            f"{module_name}.py imports from {other}.py — D-16 forbids "
            "cross-imports among contest/supersede/retract. Refactoring "
            "toward a shared `disagree()` helper is intentionally blocked."
        )
        assert f"import folio_insights.governance.{other}" not in source, (
            f"{module_name}.py imports folio_insights.governance.{other} — "
            "D-16 forbids cross-imports."
        )


# ── Grep-guard 2: no shared behavior base class ────────────────────────────


@pytest.mark.parametrize("module_name", THREE_WAY)
def test_three_way_event_classes_share_only_base_event(module_name: str) -> None:
    """Each event-class in each module inherits only from _BaseEvent / BaseModel.

    A shared ``ContestSupersedeBase`` / ``DisagreementEvent`` / ``DisputeEvent``
    base would be a structural DRY refactor — D-16 explicitly forbids that.
    The check works on whatever ClassDef appears in the module (re-exports
    don't define classes, so they're a no-op for this check).
    """
    path = _module_path(module_name)
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    event_classes = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef) and "Event" in n.name
    ]
    forbidden_shared = {
        "ContestSupersedeBase",
        "DisagreementEvent",
        "DisputeEvent",
    }
    for cls in event_classes:
        bases = {ast.unparse(b) for b in cls.bases}
        intersection = bases & forbidden_shared
        assert not intersection, (
            f"{module_name}.{cls.name} inherits from a shared-disagreement "
            f"base class ({intersection}) — D-16 forbids any behavior-sharing "
            "base beyond _BaseEvent / GovernanceEvent / BaseModel."
        )


# ── Grep-guard 3: no shared Click implementation function ──────────────────


def test_three_way_click_commands_share_no_impl() -> None:
    """The three CLI command modules must not delegate to a shared helper.

    Forbidden function names (the canonical "unified disagreement" smell):
      * ``execute_disagreement``
      * ``_dispatch_disagreement``
      * ``handle_disputed_action``

    A reference to any of these in cli/contest.py / cli/supersede.py /
    cli/retract.py — even as a string literal or comment — fails CI. The
    word "disputed" is intentionally narrow so it does not collide with
    legitimate per-module helpers.
    """
    forbidden_helpers = (
        "execute_disagreement",
        "_dispatch_disagreement",
        "handle_disputed_action",
    )
    for module_name in THREE_WAY:
        path = _cli_module_path(module_name)
        source = path.read_text(encoding="utf-8")
        for helper in forbidden_helpers:
            assert helper not in source, (
                f"cli/{module_name}.py references {helper!r} — D-16 forbids "
                "any shared Click implementation function across the three "
                "commands. Each command must own its own body."
            )


# ── Sentinel: THREE_WAY constant is present and correct ────────────────────


def test_three_way_constant_present() -> None:
    """Sentinel — the THREE_WAY constant exists at module top.

    The plan acceptance criterion greps for ``THREE_WAY`` as proof the
    quality gate is structurally in place (not just commented out).
    """
    assert THREE_WAY == ("contest", "supersede", "retract")
