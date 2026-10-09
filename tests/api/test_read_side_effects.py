"""Reads are side-effect free and corpus identifiers are validated (security review fixes A).

* Every route that takes a corpus name (path ``{corpus_id}`` or query ``?corpus=``) refuses a
  value that is not a corpus ID (``api.services.proposals.CORPUS_ID``) with 422, before the
  handler runs, so ``../escaped`` can never become a path.
* A GET (or HEAD) never creates a directory, database or file under the output dir or the
  corpus storage root: ``review.db`` is opened read-only, and an absent one reads as empty.
  The few GETs that do persist state (export routes that mint IRIs and write export files) are
  an explicit allowlist in ``tests/api/test_auth.py`` and require an operator.

Everything here runs against synthetic data in ``tmp_path``.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import main as api_main
from api.main import app
from api.routes import discovery as discovery_mod
from api.routes import processing as processing_mod
from api.services.job_manager import get_runtime
from folio_insights.persistence.review_db import LEGACY_READ_ONLY_TRIGGERS_SQL, SCHEMA_SQL
from tests.api.test_auth import GET_ROUTES_THAT_WRITE, _api_routes

CORPUS = "seeded-corpus"
UNIT_ID = "unit-0001"
TASK_ID = "task-0001"

#: Corpus names that must never reach the filesystem.
BAD_CORPUS_NAMES = [
    "../escaped",
    "..",
    ".hidden",
    "a/b",
    "a\\b",
    "-leading-dash",
    "x" * 129,
    "name with space",
    "nul\x00byte",
    "%2e%2e",
    "",
]


@pytest.fixture(autouse=True)
def isolated_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A per-test output dir (configured on the app) and a job queue outside it."""
    monkeypatch.setenv("FOLIO_INSIGHTS_QUEUE_DB", str(tmp_path / ".queue" / "jobs.sqlite3"))
    monkeypatch.setenv("FOLIO_INSIGHTS_EMBEDDED_WORKER", "0")
    previous = api_main._output_dir
    api_main.configure(output_dir=tmp_path / "output")
    api_main._extraction_data.clear()
    processing_mod.reset_job_manager()
    discovery_mod.reset_discovery_job_manager()
    yield tmp_path
    get_runtime().secret_store.clear()
    processing_mod.reset_job_manager()
    discovery_mod.reset_discovery_job_manager()
    api_main._extraction_data.clear()
    api_main.configure(output_dir=previous)


def _seed(output: Path) -> None:
    """A complete synthetic corpus: metadata, a source, extraction, and a review.db with an
    approved task linked to one unit (so export routes reach their writing code)."""
    corpus_dir = output / CORPUS
    (corpus_dir / "sources").mkdir(parents=True)
    (corpus_dir / "corpus-meta.json").write_text(
        json.dumps({"id": CORPUS, "name": "Seeded Corpus", "created_at": "2026-01-01T00:00:00Z"}),
        encoding="utf-8",
    )
    (corpus_dir / "sources" / "synthetic.md").write_text(
        "# Synthetic heading\n\nA synthetic sentence for span lookups.\n", encoding="utf-8"
    )
    unit = {
        "id": UNIT_ID,
        "text": "A synthetic knowledge unit.",
        "original_span": {"start": 0, "end": 10, "source_file": "synthetic.md"},
        "unit_type": "best_practice",
        "source_file": "synthetic.md",
        "confidence": 0.9,
        "concept_tags": [],
        "cross_references": [],
    }
    (corpus_dir / "extraction.json").write_text(
        json.dumps({"corpus": CORPUS, "units": [unit], "total_units": 1}), encoding="utf-8"
    )
    conn = sqlite3.connect(corpus_dir / "review.db")
    try:
        conn.executescript(SCHEMA_SQL)
        conn.executescript(LEGACY_READ_ONLY_TRIGGERS_SQL)
        conn.execute(
            "INSERT INTO task_decisions (task_id, corpus_name, label, status, canonical_order) "
            "VALUES (?, ?, ?, 'approved', 1)",
            (TASK_ID, CORPUS, "Synthetic task"),
        )
        conn.execute(
            "INSERT INTO task_unit_links (task_id, unit_id, corpus_name) VALUES (?, ?, ?)",
            (TASK_ID, UNIT_ID, CORPUS),
        )
        conn.commit()
    finally:
        conn.close()


def _tree(*roots: Path) -> dict[str, tuple[int, int]]:
    """Every entry under *roots* with its size and mtime: the state a read must not change."""
    snapshot: dict[str, tuple[int, int]] = {}
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            st = path.lstat()
            snapshot[str(path)] = (st.st_size if path.is_file() else -1, st.st_mtime_ns)
    return snapshot


def _get_routes() -> list[str]:
    return sorted(
        path
        for path, methods, _ in _api_routes(app)
        if "GET" in methods and ("GET", path) not in GET_ROUTES_THAT_WRITE
    )


def _concrete(path: str) -> str:
    path = path.replace("{corpus_id}", CORPUS)
    return re.sub(r"\{[^}]+\}", "synthetic", path)


def _corpus_routes() -> list[tuple[str, str]]:
    """``(method, path)`` of every API route that takes a corpus name."""
    found = []
    for path, methods, dependant in _api_routes(app):
        names = {p.name for p in dependant.path_params} | {p.name for p in dependant.query_params}
        if names & {"corpus", "corpus_id"}:
            found.extend((method, path) for method in sorted(methods - {"HEAD"}))
    return sorted(found)


# ---------------------------------------------------------------------------
# Corpus identifiers
# ---------------------------------------------------------------------------


def test_the_corpus_route_sweep_sees_the_api() -> None:
    routes = _corpus_routes()
    assert len(routes) >= 30, routes
    assert ("GET", "/api/v1/review/stats") in routes
    assert ("GET", "/api/v1/corpus/{corpus_id}/export/owl") in routes


@pytest.mark.parametrize("bad", ["../escaped", "..", "a\\b", "-x", "name with space"])
@pytest.mark.parametrize("method,path", _corpus_routes())
def test_every_corpus_route_refuses_a_bad_corpus_name(
    isolated_api: Path, method: str, path: str, bad: str,
) -> None:
    client = TestClient(app)
    if "{corpus_id}" in path:
        if "/" in bad or "\\" in bad or bad == "..":
            # A slash cannot sit in one path segment, and clients resolve a ".." segment away;
            # the query form and test_path_corpus_traversal_is_refused cover these.
            pytest.skip("not expressible as one path segment")
        url = re.sub(r"\{[^}]+\}", "synthetic", path.replace("{corpus_id}", bad))
        params = {}
    else:
        url = _concrete(path)
        params = {"corpus": bad}
    resp = client.request(method, url, params=params)
    assert resp.status_code == 422, (method, url, resp.status_code, resp.text)
    assert "corpus" in resp.text
    assert not (isolated_api / "escaped").exists()
    assert not (isolated_api / "output").exists()


@pytest.mark.parametrize("bad", BAD_CORPUS_NAMES)
@pytest.mark.parametrize("route", [
    "/api/v1/review/stats", "/api/v1/units", "/api/v1/tree", "/api/v1/tree/flat",
])
def test_query_corpus_traversal_is_refused_and_writes_nothing(
    isolated_api: Path, route: str, bad: str,
) -> None:
    before = _tree(isolated_api)
    resp = TestClient(app).get(route, params={"corpus": bad})
    assert resp.status_code == 422, resp.text
    assert _tree(isolated_api) == before
    assert bad not in api_main._extraction_data


def test_path_corpus_traversal_is_refused(isolated_api: Path) -> None:
    client = TestClient(app)
    for url in (
        "/api/v1/corpus/..%2Fescaped/tasks/tree",
        "/api/v1/corpus/%2E%2E/discovery/stats",
        "/api/v1/corpora/..",
    ):
        resp = client.get(url)
        assert resp.status_code in {404, 422}, (url, resp.status_code, resp.text)
    assert not (isolated_api / "escaped").exists()
    assert not (isolated_api / "output").exists()


def test_a_repeated_corpus_query_is_checked_in_every_value(isolated_api: Path) -> None:
    resp = TestClient(app).get("/api/v1/review/stats?corpus=ok&corpus=../escaped")
    assert resp.status_code == 422
    assert not (isolated_api / "escaped").exists()


def test_helpers_refuse_a_bad_corpus_name_too(isolated_api: Path) -> None:
    """Defence in depth: the server helpers refuse a bad name even without the dependency."""
    import asyncio

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as caught:
        api_main.get_extraction_data("../escaped")
    assert caught.value.status_code == 422
    with pytest.raises(HTTPException):
        asyncio.run(api_main.get_db_for_corpus("../escaped", writable=True))
    assert not (isolated_api / "escaped").exists()


def test_valid_corpus_names_still_work(isolated_api: Path) -> None:
    _seed(isolated_api / "output")
    client = TestClient(app)
    for name in ("default", CORPUS, "v1.2_final", "A" * 128):
        assert client.get("/api/v1/review/stats", params={"corpus": name}).status_code == 200
    assert client.get(f"/api/v1/corpora/{CORPUS}").status_code == 200


# ---------------------------------------------------------------------------
# Reads write nothing
# ---------------------------------------------------------------------------


def test_review_stats_for_an_unknown_corpus_reads_empty_and_creates_nothing(
    isolated_api: Path,
) -> None:
    before = _tree(isolated_api)
    resp = TestClient(app).get("/api/v1/review/stats", params={"corpus": "never-created"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 0
    assert _tree(isolated_api) == before
    assert not (isolated_api / "output" / "never-created").exists()


def test_reading_an_existing_review_db_does_not_add_the_schema(isolated_api: Path) -> None:
    """A GET opens review.db read-only: a database lacking tables is read, never migrated."""
    corpus_dir = isolated_api / "output" / "partial"
    corpus_dir.mkdir(parents=True)
    conn = sqlite3.connect(corpus_dir / "review.db")
    conn.execute("CREATE TABLE unrelated (x INTEGER)")
    conn.commit()
    conn.close()
    before = _tree(isolated_api)
    client = TestClient(app)
    assert client.get("/api/v1/review/stats", params={"corpus": "partial"}).status_code == 200
    assert client.get("/api/v1/corpus/partial/tasks/tree").status_code == 200
    assert client.get("/api/v1/corpus/partial/discovery/stats").status_code == 200
    assert _tree(isolated_api) == before
    conn = sqlite3.connect(corpus_dir / "review.db")
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    conn.close()
    assert names == {"unrelated"}


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_no_other_get_route_creates_or_changes_files(
    isolated_api: Path, method: str,
) -> None:
    """Exercise every GET route (except the asserted writing allowlist) against a seeded
    output dir, and require the output dir and corpus root to be byte-for-byte unchanged."""
    output = isolated_api / "output"
    corpus_root = isolated_api / "corpora"
    _seed(output)
    corpus_root.mkdir()
    routes = _get_routes()
    assert len(routes) >= 25, routes
    before = _tree(output, corpus_root)
    client = TestClient(app)
    seen: dict[str, int] = {}
    # The seeded corpus, then one that was never created (a read must not create it).
    for corpus in (CORPUS, "never-created"):
        for path in routes:
            url = _concrete(path).replace(CORPUS, corpus)
            params = {"corpus": corpus}
            if path == "/api/v1/source":
                params["file"] = f"{corpus}/sources/synthetic.md"
            resp = client.request(method, url, params=params)
            if corpus == CORPUS:
                seen[path] = resp.status_code
            assert resp.status_code < 500, (path, corpus, resp.status_code, resp.text[:300])
            assert _tree(output, corpus_root) == before, f"{method} {path} ({corpus}) wrote"
    if method == "HEAD":
        # FastAPI answers HEAD on a GET-only API route with 405 before any handler runs.
        assert set(seen.values()) <= {405}, seen
        return
    # The sweep really reached the data: the seeded reads answered 200.
    assert seen["/api/v1/review/stats"] == 200
    assert seen["/api/v1/corpus/{corpus_id}/tasks/tree"] == 200
    assert seen["/api/v1/corpus/{corpus_id}/export/markdown"] == 200
