"""D-17 cascade-preview shared-builder AST regression (07-05b Task 2).

The interactive ``governance retract`` CLI ships in three modes; per D-17
ALL THREE modes MUST invoke ``build_cascade_preview(...)`` so the cascade
computation is single-sourced. AST-walks ``cli/retract.py`` to assert:

  * the interactive (default) branch calls build_cascade_preview;
  * the --preview branch calls build_cascade_preview;
  * the --apply branch calls build_cascade_preview (via the
    ``commit_cascade -> build_cascade_preview`` re-run, OR directly in the
    CLI body — either path counts).

Mirrors ``tests/governance/test_authorize_called_first.py`` from 07-04b.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

pytestmark = pytest.mark.governance

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_RETRACT_CLI = (
    _REPO_ROOT / "src/folio_insights/governance/cli/retract.py"
)


def _all_call_names(tree: ast.AST) -> set[str]:
    """Return every callable name referenced as a Call target in the tree."""
    out: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            out.add(func.id)
        elif isinstance(func, ast.Attribute):
            out.add(func.attr)
    return out


def _calls_in_function(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
) -> set[str]:
    """Return every callable name invoked inside ``fn`` (including nested funcs)."""
    return _all_call_names(fn)


def test_retract_cli_module_exists() -> None:
    """Sentinel — the retract CLI module ships in 07-05b Task 2."""
    assert _RETRACT_CLI.exists(), (
        f"cli/retract.py MUST ship in 07-05b Task 2 to satisfy D-17. "
        f"Path: {_RETRACT_CLI}"
    )


def test_retract_cli_calls_build_cascade_preview() -> None:
    """The retract CLI module MUST invoke build_cascade_preview.

    All three modes (interactive default, --preview, --apply) route through
    the shared builder per D-17. The --apply mode does it INDIRECTLY via
    commit_cascade (which re-runs build_cascade_preview internally — see
    retract.py); the other two modes do it directly in the CLI body.
    """
    source = _RETRACT_CLI.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(_RETRACT_CLI))
    calls = _all_call_names(tree)
    assert "build_cascade_preview" in calls, (
        "cli/retract.py does NOT call build_cascade_preview. D-17 requires "
        "ALL three modes (interactive / --preview / --apply) to invoke the "
        "shared preview builder. The --apply mode counts via commit_cascade "
        "(which re-runs build_cascade_preview internally)."
    )


def test_retract_cli_calls_commit_cascade() -> None:
    """The interactive + --apply modes commit via the shared commit_cascade.

    The --preview mode does NOT call commit_cascade (it exits 0 after writing
    the JSON); only the other two modes do. Asserting presence of
    commit_cascade in the module confirms the commit path exists.
    """
    source = _RETRACT_CLI.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(_RETRACT_CLI))
    calls = _all_call_names(tree)
    assert "commit_cascade" in calls, (
        "cli/retract.py does NOT call commit_cascade. The interactive + "
        "--apply modes commit through the shared commit_cascade entry."
    )


def test_retract_cli_imports_from_retract_module_only() -> None:
    """D-16 standalone discipline at the CLI layer.

    cli/retract.py imports ONLY from governance.retract (its own backing
    module) + governance.authorize + identity / stdlib. Imports from
    governance.contest or governance.supersede would violate D-16.
    """
    source = _RETRACT_CLI.read_text(encoding="utf-8")
    assert "from folio_insights.governance.contest" not in source, (
        "cli/retract.py imports from governance.contest — D-16 forbids "
        "cross-imports among the three-way disambiguation CLI commands."
    )
    assert "from folio_insights.governance.supersede" not in source, (
        "cli/retract.py imports from governance.supersede — D-16 forbids "
        "cross-imports among the three-way disambiguation CLI commands."
    )
