"""Phase-13 dep-leak guard: no shards/ module imports pyoxigraph/rdflib/etc.

Enforces CONTEXT Integration Points: 'Phase 2 does NOT write through pyoxigraph
yet but defines the data that Phase 13 will serialize. No Phase-13 dep leak.'

Also guards against a lingering PRD-§6.1 ``https://folio-insights.aleainstitute.ai/shard``
IRI prefix anywhere under ``src/folio_insights/shards/`` — CONTEXT D-02
supersedes that with ``urn:folio:shard/``; any residual reference is a
regression.
"""
from __future__ import annotations

import pathlib

import pytest

from folio_insights import shards

pytestmark = pytest.mark.shards


FORBIDDEN_MODULES = ["pyoxigraph", "rdflib", "oxrdflib", "owlready2"]


@pytest.mark.parametrize("module_name", FORBIDDEN_MODULES)
def test_no_storage_import_in_phase2_shards(module_name: str) -> None:
    """No file under src/folio_insights/shards/ imports a Phase-13 storage lib."""
    shards_dir = pathlib.Path(shards.__file__).parent
    for module_file in shards_dir.glob("*.py"):
        source = module_file.read_text(encoding="utf-8")
        assert f"import {module_name}" not in source, (
            f"{module_file.name}: Phase 2 must not `import {module_name}` "
            f"(Phase 13 storage scope; see 02-CONTEXT.md Integration Points)"
        )
        assert f"from {module_name}" not in source, (
            f"{module_file.name}: Phase 2 must not `from {module_name} import ...` "
            f"(Phase 13 storage scope; see 02-CONTEXT.md Integration Points)"
        )


def test_no_http_iri_prefix_regression() -> None:
    """D-02 override guard: PRD §6.1's https://folio-insights.aleainstitute.ai/shard/
    prefix is SUPERSEDED by CONTEXT D-02's urn:folio:shard/. Any lingering http
    prefix in shards/ source is a regression."""
    shards_dir = pathlib.Path(shards.__file__).parent
    for module_file in shards_dir.glob("*.py"):
        source = module_file.read_text(encoding="utf-8")
        assert "folio-insights.aleainstitute.ai/shard" not in source, (
            f"{module_file.name}: D-02 locks urn:folio:shard/ IRI prefix; "
            f"the PRD §6.1 https:// prefix is SUPERSEDED. Remove any reference."
        )
