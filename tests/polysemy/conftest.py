"""Shared fixtures for Phase 1 polysemy spike tests.

Session-scoped consideration_fixture_store: empty PyoxigraphStore until
Plan 01-02 lands the hand-curated fixtures under
`.planning/phases/01-polysemy-distinguo-spike/fixtures/consideration/`.

Mirrors the `tests/bench/conftest.py::bench_store` shape established in Phase 0
(session scope because bulk_load cost amortizes across multiple assertions).
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = (
    REPO_ROOT
    / ".planning"
    / "phases"
    / "01-polysemy-distinguo-spike"
    / "fixtures"
    / "consideration"
)


@pytest.fixture(scope="session")
def consideration_fixture_dir() -> Path:
    """Hand-curated consideration shards (JSON, one per file).

    Returns the directory path. Tests that need shards loaded should
    call pytest.skip() if the directory is empty (Phase 0 skip-if-missing
    pattern — see tests/bench/conftest.py::bench_1m_corpus).
    """
    return FIXTURE_DIR


@pytest.fixture(scope="session")
def consideration_fixture_store(consideration_fixture_dir: Path):
    """PyoxigraphStore backing for the consideration spike.

    Named graph target: ``urn:folio:corpus/consideration-spike``.

    Wave-0: returns an empty in-memory PyoxigraphStore. Plan 01-02 adds a
    fixture JSON loader that converts JSON shards to TTL and bulk-loads here.
    Plan 01-04 uses the same store to round-trip distinguo TTL emissions.
    """
    from folio_insights.store.pyoxigraph_store import PyoxigraphStore

    return PyoxigraphStore(path=None)  # in-memory


@pytest.fixture
def registered_polysemy_reviewer(tmp_path, monkeypatch):
    from folio_insights.config import get_settings
    from folio_insights.proposals.signed_decisions import reset_signers_cache
    from tests.polysemy._signed import DID, OTHER_DID

    registry = tmp_path / "public-reviewers.txt"
    registry.write_text(f"{DID} synthetic-reviewer\n{OTHER_DID} second-reviewer\n")
    registry.chmod(0o600)
    monkeypatch.setenv("FOLIO_INSIGHTS_DECISION_SIGNERS_FILE", str(registry))
    get_settings.cache_clear()
    reset_signers_cache()
    yield registry
    get_settings.cache_clear()
    reset_signers_cache()
