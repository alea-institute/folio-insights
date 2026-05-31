"""Phase 8 Plan 08-03 — dep-leak guard for src/folio_insights/temporal/ (D-04 mirror).

Enforces the Phase 8 D-04 / D-10 boundary: NO module under
``src/folio_insights/temporal/`` imports pyoxigraph, oxrdflib, pyshacl, or
any folio_insights subsystem above the rdflib/stdlib quarantine line
(``vocab``, ``revision``, ``store``, ``governance``).

``rdflib`` IS allowed — the as_of helper is rdflib-native by D-10 ("Pure
rdflib-based; no pyoxigraph dependency.") so Phase 11 can widen to a
``Graph | Store`` polymorphic surface without touching this module's
boundary contract.

Modeled on tests/governance/test_dep_leak_guard.py (Phase 7 precedent).
"""

from __future__ import annotations

import pathlib

import pytest

from folio_insights import temporal


# Forbidden modules — both as top-level names and dotted package paths.
# Top-level names are pyshacl-style raw imports; dotted names catch
# cross-subsystem couplings under folio_insights.* that D-10 quarantines.
FORBIDDEN = [
    "pyoxigraph",
    "oxrdflib",
    "pyshacl",
    "folio_insights.vocab",
    "folio_insights.revision",
    "folio_insights.store",
    "folio_insights.governance",
]


@pytest.mark.parametrize("module_name", FORBIDDEN)
def test_no_forbidden_import_in_temporal(module_name: str) -> None:
    """D-10 forbids these modules under src/folio_insights/temporal/. Phase 11
    widens query_as_of to Graph | Store polymorphic when the persistent
    pyoxigraph store lands — until then, the temporal/ surface is rdflib
    only so the seam is honest.
    """
    temporal_dir = pathlib.Path(temporal.__file__).parent
    for module_file in temporal_dir.rglob("*.py"):
        source = module_file.read_text(encoding="utf-8")
        assert f"import {module_name}" not in source, (
            f"{module_file.relative_to(temporal_dir)}: D-10 forbids "
            f"`import {module_name}` under temporal/ (Phase 8 dep-leak "
            f"discipline mirrors Phase 7 governance; see 08-CONTEXT.md D-10)."
        )
        assert f"from {module_name}" not in source, (
            f"{module_file.relative_to(temporal_dir)}: D-10 forbids "
            f"`from {module_name} import ...` under temporal/ (Phase 8 "
            f"dep-leak discipline; see 08-CONTEXT.md D-10)."
        )


def test_temporal_imports_rdflib() -> None:
    """Sanity check: the temporal/ surface IS rdflib-native (D-10). If this
    fails the quarantine is vacuous — either remove the guard or wire the
    SPARQL helper.
    """
    temporal_dir = pathlib.Path(temporal.__file__).parent
    as_of = temporal_dir / "as_of.py"
    assert as_of.exists(), "temporal/as_of.py must ship (Plan 08-03 Task 1)."
    source = as_of.read_text(encoding="utf-8")
    assert "from rdflib" in source or "import rdflib" in source, (
        "temporal/as_of.py is the rdflib-native query surface — if it does "
        "not import rdflib the dep-leak quarantine is vacuous."
    )
