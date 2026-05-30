"""Phase-13 dep-leak guard for src/folio_insights/governance/ (D-04 boundary).

Enforces the Phase 7 D-04 boundary: NO module under
``src/folio_insights/governance/`` imports a Phase 13 storage / RDF library
(``aiosqlite``, ``rdflib``, ``pyoxigraph``, ``oxrdflib``). The Phase 13
GovernanceLog backend slots in BEHIND the ``GovernanceLog`` Protocol; the
governance/ package surface stays stdlib + Pydantic only so the seam holds.

Exemption: ``governance/shape_validation.py`` is the lone exempt file (it
hosts the SHACL validator wrapper, mirroring the precedent that
``revision/shape_validation.py`` is exempt from the ``shards/`` dep-leak
boundary). The test skips ``shape_validation.py`` by basename.

This test ALSO walks subdirectories — the ``governance/shapes/`` TTL
directory is scanned, but TTL files have no ``import`` statements, so the
guard is vacuous there. The recursive walk catches any future submodule
(e.g. ``governance/log/store.py``) without further test edits.

Mirrors ``tests/shards/test_dep_leak_guard.py`` (the Phase 2 precedent).
"""
from __future__ import annotations

import pathlib

import pytest

from folio_insights import governance

pytestmark = pytest.mark.governance


FORBIDDEN = ["aiosqlite", "rdflib", "pyoxigraph", "oxrdflib"]

# The single exempt module — mirrors the precedent that
# revision/shape_validation.py is exempt from the shards/ dep-leak boundary.
_EXEMPT_FILENAMES = {"shape_validation.py"}


@pytest.mark.parametrize("module_name", FORBIDDEN)
def test_no_storage_import_in_governance(module_name: str) -> None:
    """D-04 forbids aiosqlite/rdflib/pyoxigraph/oxrdflib imports under
    src/folio_insights/governance/ — Phase 13 backend wires the persistent
    store behind the GovernanceLog Protocol; any direct import here breaks
    the seam discipline.
    """
    governance_dir = pathlib.Path(governance.__file__).parent
    for module_file in governance_dir.rglob("*.py"):
        if module_file.name in _EXEMPT_FILENAMES:
            # shape_validation.py is the lone exempted module (mirrors
            # revision/shape_validation.py against the shards/ boundary).
            continue
        source = module_file.read_text(encoding="utf-8")
        assert f"import {module_name}" not in source, (
            f"{module_file.relative_to(governance_dir)}: D-04 forbids "
            f"`import {module_name}` under governance/ (Phase 13 storage / "
            f"RDF stack lives behind the GovernanceLog Protocol; see "
            f"07-CONTEXT.md D-04)."
        )
        assert f"from {module_name}" not in source, (
            f"{module_file.relative_to(governance_dir)}: D-04 forbids "
            f"`from {module_name} import ...` under governance/ (Phase 13 "
            f"storage / RDF stack lives behind the GovernanceLog Protocol; "
            f"see 07-CONTEXT.md D-04)."
        )


def test_shape_validation_is_exempt() -> None:
    """Sanity check: shape_validation.py exists and IS allowed to import rdflib.

    If the exemption stopped working (e.g. someone renamed the file), this
    test would catch the silent regression by asserting both the file's
    presence AND that it does carry an rdflib import (the exemption is real,
    not vacuous).
    """
    governance_dir = pathlib.Path(governance.__file__).parent
    shape_val = governance_dir / "shape_validation.py"
    assert shape_val.exists(), (
        "governance/shape_validation.py must ship — the lone exempt module."
    )
    source = shape_val.read_text(encoding="utf-8")
    # The exemption is REAL: the file actually imports rdflib (else there's
    # nothing to exempt).
    assert "from rdflib" in source or "import rdflib" in source, (
        "shape_validation.py is exempt from the dep-leak guard but does NOT "
        "import rdflib — the exemption is vacuous. Either remove the exemption "
        "or wire the SHACL validator."
    )
